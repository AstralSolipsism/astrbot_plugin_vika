from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import load_config, AppConfig
from .mcp.registry import ToolRegistry
from .mcp.executor import JobManager
from .routes import router
from .tools import builtin as builtin_tools
from .tools import vika_tools as optional_vika


def create_app() -> FastAPI:
    # 加载配置
    config = load_config()

    # 组装注册表并注册工具
    registry = ToolRegistry()
    builtin_tools.register(registry)
    try:
        optional_vika.try_register_vika_tools(registry)
    except Exception:
        # 占位注册器失败不影响服务可用性
        pass

    # 创建执行管理器
    job_manager = JobManager(
        registry=registry,
        max_workers=config.executor_max_workers,
        heartbeat_interval=config.sse_heartbeat_interval_secs,
    )

    # 创建 FastAPI 应用
    app = FastAPI(title="vika_mcp", version="0.1.0")

    # 注入状态
    app.state.config = config
    app.state.registry = registry
    app.state.job_manager = job_manager

    # 健康检查
    @app.get("/.well-known/healthz")
    async def healthz(request: Request) -> JSONResponse:
        try:
            reg = request.app.state.registry
            tools_count = len(reg.list_tools(include_unavailable=True))
        except Exception:
            tools_count = 0
        return JSONResponse(content={"status": "ok", "tools": tools_count})

    # 挂载 MCP 路由
    app.include_router(router)

    return app


# 导出默认应用实例
app = create_app()