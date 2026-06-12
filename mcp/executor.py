import asyncio
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, Optional

from .registry import ToolRegistry, HandlerType
from .types import ExecuteAccepted, ErrorDTO, ToolSpec
from .validation import ToolInputInvalid


class JobManager:
    def __init__(self, registry: ToolRegistry, max_workers: int = 4, heartbeat_interval: int = 15) -> None:
        self.registry = registry
        self.heartbeat_interval = heartbeat_interval
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def _stable_job_id(self, tool: str, arguments: Dict[str, Any], idempotency_key: Optional[str]) -> str:
        if idempotency_key:
            payload = {
                "tool": tool,
                "arguments": arguments or {},
                "idempotency_key": idempotency_key,
            }
            s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(s.encode("utf-8")).hexdigest()
        return uuid.uuid4().hex

    def _build_sse(self, name: str, seq: int, data: Dict[str, Any]) -> bytes:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        chunk = f"event: {name}\nid: {seq}\ndata: {payload}\n\n"
        return chunk.encode("utf-8")

    async def _maybe_await(self, handler: HandlerType, args: Dict[str, Any]) -> Any:
        if asyncio.iscoroutinefunction(handler):
            return await handler(args)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: handler(args))

    async def _emit(self, job_id: str, name: str, data: Dict[str, Any]) -> None:
        job = self._jobs[job_id]
        job["seq"] += 1
        seq = job["seq"]
        event = {"seq": seq, "name": name, "data": data}
        job["events"].append(event)
        job["updated_at"] = datetime.utcnow().isoformat() + "Z"

        sse = self._build_sse(name, seq, data)
        for q in list(job["subscribers"]):
            try:
                q.put_nowait(sse)
            except Exception:
                # 忽略单个订阅者队列失败
                pass

    async def _run_handler(self, job_id: str) -> None:
        job = self._jobs[job_id]
        spec: ToolSpec = job["spec"]
        handler: HandlerType = job["handler"]

        job["status"] = "running"
        job["started_at"] = datetime.utcnow().isoformat() + "Z"

        # 工具信息事件
        await self._emit(job_id, "tool_info", {"tool": spec.dict()})

        try:
            args = job["arguments"] or {}
            result = await self._maybe_await(handler, args)
            job["status"] = "completed"
            job["result"] = result
            await self._emit(job_id, "result", {"result": result})
        except ToolInputInvalid as e:
            job["status"] = "error"
            err = ErrorDTO(
                code="tool_input_invalid",
                message=str(e),
                retryable=False,
                details={"errors": e.errors},
            ).dict()
            job["error"] = err
            await self._emit(job_id, "error", {"error": err})
        except Exception as e:
            job["status"] = "error"
            err = ErrorDTO(code="tool_error", message=str(e), retryable=False).dict()
            job["error"] = err
            await self._emit(job_id, "error", {"error": err})
        finally:
            job["finished_at"] = datetime.utcnow().isoformat() + "Z"
            await self._emit(job_id, "end", {"job_id": job_id, "status": job["status"]})

    def create_job(self, tool: str, arguments: Dict[str, Any], idempotency_key: Optional[str] = None) -> ExecuteAccepted:
        job_id = self._stable_job_id(tool, arguments or {}, idempotency_key)

        # 幂等：已有作业直接返回
        if job_id in self._jobs:
            existing = self._jobs[job_id]
            return ExecuteAccepted(job_id=job_id, status=existing.get("status", "queued"))

        # 查找工具
        spec, handler = self.registry.get(tool)

        # 初始化作业
        job = {
            "job_id": job_id,
            "tool": tool,
            "arguments": arguments or {},
            "idempotency_key": idempotency_key,
            "status": "queued",
            "result": None,
            "error": None,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "started_at": None,
            "finished_at": None,
            "updated_at": None,
            "seq": 0,
            "events": [],  # 事件缓冲
            "subscribers": [],  # 订阅者队列集合
            "spec": spec,
            "handler": handler,
        }
        self._jobs[job_id] = job

        # 预先发送 open 事件
        open_payload = {"job_id": job_id, "status": job["status"], "seq": 1}
        asyncio.create_task(self._emit(job_id, "open", open_payload))

        # 后台执行处理器
        asyncio.create_task(self._run_handler(job_id))

        return ExecuteAccepted(job_id=job_id, status="queued")

    async def stream(self, job_id: str, from_seq: int = 0):
        """
        返回一个异步生成器，产出 SSE 帧（bytes）：
        event: <name>\n
        id: <seq>\n
        data: <json>\n
        \n
        - 心跳事件：event: heartbeat，每 self.heartbeat_interval 秒一次
        """
        if job_id not in self._jobs:
            raise KeyError("job not found")

        job = self._jobs[job_id]
        q: asyncio.Queue = asyncio.Queue()
        job["subscribers"].append(q)

        last_seq = from_seq

        # 先补发历史事件
        for ev in job["events"]:
            if ev["seq"] > from_seq:
                q.put_nowait(self._build_sse(ev["name"], ev["seq"], ev["data"]))
                last_seq = ev["seq"]

        try:
            while True:
                try:
                    sse: bytes = await asyncio.wait_for(q.get(), timeout=self.heartbeat_interval)
                    # 已发送事件后，更新 last_seq 为当前作业序号
                    last_seq = job["seq"]
                    yield sse
                except asyncio.TimeoutError:
                    # 心跳帧，不计入事件序列
                    hb = {"job_id": job_id, "ts": datetime.utcnow().isoformat() + "Z"}
                    yield self._build_sse("heartbeat", last_seq, hb)

                # 在 'end' 已经发送且队列为空后结束流
                if job["status"] in ("completed", "error") and q.empty():
                    if job["events"] and job["events"][-1]["name"] == "end" and last_seq >= job["events"][-1]["seq"]:
                        break
        finally:
            try:
                job["subscribers"].remove(q)
            except ValueError:
                pass
