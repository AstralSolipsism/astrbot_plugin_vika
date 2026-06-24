from __future__ import annotations

import copy
import hashlib
import inspect
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional


DEFAULT_WRITE_PLAN_TTL = timedelta(minutes=15)
MAX_WRITE_PLAN_TTL = timedelta(minutes=60)
MAX_DIRECT_RECORDS = 500
MAX_DIRECT_PAYLOAD_BYTES = 1_000_000

ExecuteWrite = Callable[[Dict[str, Any]], Any]


class WritePlanStore:
    def __init__(self, default_ttl: timedelta = DEFAULT_WRITE_PLAN_TTL) -> None:
        self.default_ttl = min(default_ttl, MAX_WRITE_PLAN_TTL)
        self._operations: Dict[str, Dict[str, Any]] = {}

    def preview(
        self,
        operation_type: str,
        datasheet_id: str,
        target_label: str,
        payload: Dict[str, Any],
        field_names: list[str],
        record_count: int,
        execute: ExecuteWrite,
        risk_level: Optional[str] = None,
        confirmation_details: Optional[Dict[str, Any]] = None,
        confirmation_brief_suffix: Optional[str] = None,
    ) -> Dict[str, Any]:
        stored_payload = copy.deepcopy(payload)
        payload_bytes = self._payload_bytes(stored_payload)
        if record_count > MAX_DIRECT_RECORDS or len(payload_bytes) > MAX_DIRECT_PAYLOAD_BYTES:
            return {
                "error": {
                    "code": "payload_too_large",
                    "message": "Direct MCP write payload exceeds limits; stage it as an artifact before preview.",
                    "details": {
                        "max_direct_records": MAX_DIRECT_RECORDS,
                        "max_direct_payload_bytes": MAX_DIRECT_PAYLOAD_BYTES,
                        "record_count": record_count,
                        "payload_bytes": len(payload_bytes),
                    },
                }
            }

        operation_id = f"op_{uuid.uuid4().hex}"
        payload_hash = self._payload_hash(stored_payload)
        expires_at = datetime.now(timezone.utc) + self.default_ttl
        risk_level = risk_level or self._risk_level(operation_type)
        operation_label = self._operation_label(operation_type)
        item_label = self._item_label(operation_type)
        confirmation_context = self._confirmation_context(
            operation_id=operation_id,
            operation_type=operation_type,
            target_label=target_label or datasheet_id,
            record_count=record_count,
            risk_level=risk_level,
            payload_hash=payload_hash,
            expires_at=expires_at.isoformat(),
            operation_label=operation_label,
            confirmation_details=confirmation_details,
        )
        public_operation = {
            "operation_id": operation_id,
            "operation_type": operation_type,
            "datasheet_id": datasheet_id,
            "target_label": target_label or datasheet_id,
            "record_count": record_count,
            "validation_summary": "payload accepted for preview",
            "risk_level": risk_level,
            "payload_hash": payload_hash,
            "expires_at": expires_at.isoformat(),
            "confirmation_context": confirmation_context,
            "confirmation_brief": self._confirmation_brief(
                target_label=target_label or datasheet_id,
                operation_label=operation_label,
                record_count=record_count,
                item_label=item_label,
                risk_level=risk_level,
                suffix=confirmation_brief_suffix,
            ),
            "ask_user_instruction": self._ask_user_instruction(payload_hash),
            "preview_only": True,
            "requires_confirmation": True,
        }
        self._operations[operation_id] = {
            **copy.deepcopy(public_operation),
            "field_names": list(field_names),
            "sample_records": self._sample_records(stored_payload),
            "payload": stored_payload,
            "execute": execute,
            "expires_at_dt": expires_at,
            "committed": False,
            "result": None,
            "user_confirmation_summary": None,
        }
        return copy.deepcopy(public_operation)

    async def commit(
        self,
        operation_id: str,
        confirmed_payload_hash: Optional[str],
        confirmed_by_user: bool,
        user_confirmation_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        operation = self._operations.get(operation_id)
        if operation is None:
            return {"error": {"code": "operation_not_found", "message": f"Operation not found: {operation_id}"}}
        if not confirmed_by_user:
            return {"error": {"code": "user_confirmation_required", "message": "confirmed_by_user must be true."}}
        if operation["expires_at_dt"] < datetime.now(timezone.utc):
            return {"error": {"code": "operation_expired", "message": "Write operation preview has expired."}}
        if not confirmed_payload_hash:
            return {"error": {"code": "confirmed_payload_hash_required", "message": "confirmed_payload_hash is required."}}
        current_payload_hash = self._payload_hash(operation["payload"])
        if current_payload_hash != operation["payload_hash"]:
            return {
                "error": {
                    "code": "payload_hash_mismatch",
                    "message": "Stored write payload no longer matches the preview hash; create a new preview operation.",
                    "details": {
                        "operation_id": operation_id,
                        "expected_payload_hash": operation["payload_hash"],
                        "actual_payload_hash": current_payload_hash,
                    },
                }
            }
        if confirmed_payload_hash != operation["payload_hash"]:
            return {
                "error": {
                    "code": "confirmed_payload_hash_mismatch",
                    "message": "confirmed_payload_hash must match the preview payload_hash.",
                    "details": {
                        "operation_id": operation_id,
                        "expected_payload_hash": operation["payload_hash"],
                        "confirmed_payload_hash": confirmed_payload_hash,
                    },
                }
            }
        if operation["committed"]:
            return {
                "operation_id": operation_id,
                "already_committed": True,
                "committed": True,
                "result": operation["result"],
                "user_confirmation_summary": operation.get("user_confirmation_summary"),
            }

        result = operation["execute"](self._execution_operation(operation))
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict) and "error" in result:
            return {
                "operation_id": operation_id,
                "committed": False,
                "error": result["error"],
            }
        operation["committed"] = True
        operation["result"] = result
        operation["user_confirmation_summary"] = user_confirmation_summary
        return {
            "operation_id": operation_id,
            "already_committed": False,
            "committed": True,
            "result": result,
            "user_confirmation_summary": user_confirmation_summary,
        }

    def _operation_label(self, operation_type: str) -> str:
        return {
            "records.create": "新增",
            "records.update": "更新",
            "records.delete": "删除",
            "fields.create": "新增字段",
            "fields.delete": "删除字段",
            "datasheets.create": "创建",
            "attachments.upload": "上传附件",
            "nodes.embedlinks.create": "创建嵌入链接",
            "nodes.embedlinks.delete": "删除嵌入链接",
        }.get(operation_type, operation_type)

    def _item_label(self, operation_type: str) -> str:
        if operation_type.startswith("records."):
            return "条记录"
        if operation_type.startswith("fields."):
            return "个字段"
        if operation_type.startswith("datasheets."):
            return "个数据表"
        if operation_type.startswith("attachments."):
            return "个附件"
        if operation_type.startswith("nodes.embedlinks."):
            return "个嵌入链接"
        return "项"

    def _confirmation_context(
        self,
        operation_id: str,
        operation_type: str,
        target_label: str,
        record_count: int,
        risk_level: str,
        payload_hash: str,
        expires_at: str,
        operation_label: str,
        confirmation_details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = {
            "operation_id": operation_id,
            "operation_type": operation_type,
            "target_label": target_label,
            "record_count": record_count,
            "risk_level": risk_level,
            "payload_hash": payload_hash,
            "expires_at": expires_at,
            "operation_label": operation_label,
        }
        if confirmation_details:
            context.update(copy.deepcopy(confirmation_details))
        return context

    def _confirmation_brief(
        self,
        target_label: str,
        operation_label: str,
        record_count: int,
        item_label: str,
        risk_level: str,
        suffix: Optional[str] = None,
    ) -> str:
        brief = f"将对《{target_label}》{operation_label} {record_count} {item_label}，风险等级 {risk_level}。"
        if suffix:
            brief = f"{brief}{suffix}"
        return brief

    def _ask_user_instruction(self, payload_hash: str) -> str:
        return (
            "请用一句自然语言向用户确认此次写入计划；不要展示原始 payload、样本记录、完整字段列表或调试结构。"
            f"用户确认后调用 vika.write.commit，并传入 confirmed_payload_hash={payload_hash}。"
        )

    def _risk_level(self, operation_type: str) -> str:
        if "delete" in operation_type:
            return "high"
        return "medium"

    def _sample_records(self, payload: Dict[str, Any]) -> list[Any]:
        records = payload.get("records") or payload.get("record_ids") or []
        if isinstance(records, list):
            return copy.deepcopy(records[:3])
        return [copy.deepcopy(records)]

    def _payload_bytes(self, payload: Dict[str, Any]) -> bytes:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _payload_hash(self, payload: Dict[str, Any]) -> str:
        return hashlib.sha256(self._payload_bytes(payload)).hexdigest()

    def _execution_operation(self, operation: Dict[str, Any]) -> Dict[str, Any]:
        fields = [
            "operation_id",
            "operation_type",
            "datasheet_id",
            "target_label",
            "record_count",
            "field_names",
            "risk_level",
            "payload_hash",
            "confirmation_context",
            "confirmation_brief",
        ]
        execution_operation = {key: copy.deepcopy(operation[key]) for key in fields if key in operation}
        execution_operation["payload"] = copy.deepcopy(operation["payload"])
        return execution_operation
