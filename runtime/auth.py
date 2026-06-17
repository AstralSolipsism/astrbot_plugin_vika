from __future__ import annotations

from mcp.server.auth.provider import AccessToken


class StaticBearerTokenVerifier:
    def __init__(self, token: str) -> None:
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != self._token:
            return None
        return AccessToken(token=token, client_id="vika_mcp_static_bearer", scopes=["mcp"])
