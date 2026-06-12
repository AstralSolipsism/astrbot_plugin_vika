from typing import Any, Dict, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import require_api_key
from .mcp.executor import JobManager
from .mcp.registry import ToolRegistry
from .mcp.types import ExecuteAccepted, ExecuteRequest


router = APIRouter(prefix="/mcp/v1", dependencies=[Depends(require_api_key)])


async def _get_registry(request: Request) -> ToolRegistry:
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        raise HTTPException(status_code=500, detail="Registry not initialized")
    return cast(ToolRegistry, registry)


async def _get_job_manager(request: Request) -> JobManager:
    jm = getattr(request.app.state, "job_manager", None)
    if jm is None:
        raise HTTPException(status_code=500, detail="Job manager not initialized")
    return cast(JobManager, jm)


# tools_list: GET /mcp/v1/tools
@router.get("/tools")
async def tools_list(request: Request, include_unavailable: bool = False) -> Dict[str, Any]:
    registry = await _get_registry(request)
    tools = [t.dict() for t in registry.list_tools(include_unavailable=include_unavailable)]
    return {"tools": tools}


# execute_tool: POST /mcp/v1/execute
@router.post("/execute", status_code=status.HTTP_202_ACCEPTED)
async def execute_tool(request: Request, payload: ExecuteRequest) -> JSONResponse:
    jm = await _get_job_manager(request)
    try:
        accepted: ExecuteAccepted = jm.create_job(
            tool=payload.tool,
            arguments=payload.arguments or {},
            idempotency_key=payload.idempotency_key,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tool not found: {payload.tool}")

    if payload.stream is not False:
        accepted.stream_url = f"/mcp/v1/stream/{accepted.job_id}"

    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.dict())


# stream_events: GET /mcp/v1/stream/{job_id}
@router.get("/stream/{job_id}")
async def stream_events(
    request: Request,
    job_id: str,
    from_seq: int = Query(0, alias="from"),
) -> StreamingResponse:
    jm = await _get_job_manager(request)

    try:
        agen = jm.stream(job_id, from_seq=from_seq)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_iter():
        try:
            async for chunk in agen:
                yield chunk
        except KeyError:
            # 作业不存在时返回 404 已在上方处理，这里防御性忽略
            return

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)