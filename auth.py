from typing import Optional

from fastapi import Header, HTTPException, Request
from starlette.status import HTTP_401_UNAUTHORIZED


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
) -> None:
    """
    基于应用状态配置进行鉴权：
    - 从 request.app.state.config.auth 读取 enabled 与 api_keys。
    - 若未配置、禁用，或无 key，则放行。
    - 否则优先校验请求头 X-API-Key，其次 Authorization: Bearer <token>。
    """
    config = getattr(request.app.state, "config", None)

    keys = []
    enabled = False

    if config is not None:
        auth = getattr(config, "auth", None)
        if auth is not None:
            keys = list(getattr(auth, "api_keys", []) or [])
            enabled = bool(getattr(auth, "enabled", bool(keys)))
        else:
            # 兼容旧字段：顶层 api_keys
            keys = list(getattr(config, "api_keys", []) or [])
            enabled = bool(keys)

    if not enabled or not keys:
        return

    token: Optional[str] = None

    # 优先使用 X-API-Key
    if x_api_key:
        token = x_api_key.strip()

    # 其次尝试 Authorization: Bearer XXX
    if not token and authorization:
        auth_header = authorization.strip()
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if token and token in keys:
        return

    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )
