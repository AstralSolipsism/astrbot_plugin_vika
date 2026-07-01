"""
维格表HTTP请求处理模块

兼容原vika.py库的请求处理方式

Transport note: this module prefers ``curl_cffi`` when available so that the
TLS ClientHello (JA3/JA4) and HTTP/2 settings/priority frames match a real
Chrome browser, and the default request headers are sent in Chrome's order.
This keeps the SDK's network fingerprint identical to the Vika web client,
which is what the deployment's risk-control layer expects. When
``curl_cffi`` is not installed, it transparently falls back to ``httpx``.
"""
import asyncio
import json
import os
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple, Union

import httpx

from .const import DEFAULT_API_BASE, FUSION_API_PREFIX
from .exceptions import VikaException, create_exception_from_response
from .utils import build_api_url, handle_response

QueryParams = Union[Dict[str, Any], Iterable[Tuple[str, Any]]]

try:  # pragma: no cover - import guard for the optional browser-impersonation backend
    from curl_cffi.requests import AsyncSession as _CurlAsyncSession  # type: ignore

    _HAS_CURL_CFFI = True
except Exception:  # pragma: no cover
    _CurlAsyncSession = None  # type: ignore
    _HAS_CURL_CFFI = False

# Chrome/BoringSSL impersonation target. curl_cffi 0.15 ships up to chrome146;
# pick the closest available to the real Chrome 149 the web client runs.
_IMPERSONATE_TARGET = os.getenv("VIKA_IMPERSONATE", "chrome146")

# Real Chrome 149 / Windows headers (captured from the live web client) for a
# same-origin XHR to the Vika API. Order matters: Chrome emits client-hints,
# then User-Agent, then fetch-metadata, then content negotiation headers.
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)


def _browser_headers(referer: Optional[str]) -> Dict[str, str]:
    """Build the Chrome/Windows XHR header set in Chrome's emission order.

    Args:
        referer: Origin/referer URL for the request, or ``None`` to omit.

    Returns:
        Ordered dict of browser-matching headers (excluding Authorization,
        which is injected per-request by the session).
    """
    headers: Dict[str, str] = {
        "sec-ch-ua-platform": '"Windows"',
        "User-Agent": _CHROME_UA,
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "Accept": "application/json, text/plain, */*",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _serialize_params(params: Optional[QueryParams]) -> List[Tuple[str, Any]]:
    """Serialize Vika query params, including repeated and nested values."""
    if not params:
        return []

    items = params.items() if isinstance(params, dict) else params
    serialized: List[Tuple[str, Any]] = []

    def append_value(key: str, value: Any) -> None:
        if value is None:
            return
        if key == "sort" and isinstance(value, list):
            for index, item in enumerate(value):
                if not isinstance(item, dict):
                    serialized.append((key, item))
                    continue
                for nested_key in ("field", "order"):
                    nested_value = item.get(nested_key)
                    if nested_value is not None:
                        serialized.append((f"sort[{index}][{nested_key}]", nested_value))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                if item is not None:
                    serialized.append((key, item))
            return
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                append_value(f"{key}[{nested_key}]", nested_value)
            return
        serialized.append((key, value))

    for key, value in items:
        append_value(str(key), value)

    return serialized


class Session:
    """
    一个原生异步的HTTP请求会话。

    When ``curl_cffi`` is available the session impersonates Chrome at the TLS
    (JA3/JA4) and HTTP/2 layers and sends the browser's default header set in
    Chrome order, so the wire fingerprint is indistinguishable from the Vika
    web client. It falls back to a plain ``httpx.AsyncClient`` otherwise.
    """

    def __init__(self, token: str, api_base: str = DEFAULT_API_BASE, status_callback: Optional[Callable[[str], Awaitable[None]]] = None):
        # 将token存为私有字段以避免泄露
        self._token = token
        self.api_base = api_base.rstrip('/')
        self.status_callback = status_callback
        self.rate_limit_retries = 3
        self.rate_limit_base_delay = 0.6
        # Authoritative header set + order is assembled per-request so the
        # bearer token and referer are placed exactly where Chrome puts them.
        self._auth_header = f'Bearer {self._token}'
        # Whether the TLS/HTTP2 fingerprint is browser-impersonated.
        self._impersonated = _HAS_CURL_CFFI
        # Allow self-signed/private-CA deployments (e.g. :7886) to be reachable
        # without forcing every caller to pass verify=False explicitly.
        self._verify = os.getenv("VIKA_VERIFY_TLS", "1") not in ("0", "false", "False")
        if self._impersonated:
            # default_headers=False: we provide the full Chrome header set
            # ourselves below; only borrow curl_cffi's TLS + H2 fingerprint.
            self.client = _CurlAsyncSession(
                impersonate=_IMPERSONATE_TARGET,
                default_headers=False,
                timeout=30.0,
                verify=self._verify,
            )
        else:
            headers = {
                'Authorization': self._auth_header,
                'Content-Type': 'application/json',
                'User-Agent': 'vika-py/2.0.0',
            }
            self.client = httpx.AsyncClient(headers=headers, timeout=30.0, verify=self._verify)

    def _default_headers(self, extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        """Compose the request header set for the impersonated transport.

        Args:
            extra: Per-call headers (e.g. ``X-Front-Version``) to merge in.

        Returns:
            Headers including Authorization, browser defaults, and any extras.
        """
        headers = _browser_headers(referer=f"{self.api_base}/")
        # Authorization sits with the content-negotiation group, matching the
        # axios client used by the Vika web app.
        headers['Authorization'] = self._auth_header
        if extra:
            headers.update(extra)
        return headers

    def _build_url(self, endpoint: str) -> str:
        """构建完整URL"""
        if endpoint.startswith('http'):
            return endpoint

        if not endpoint.startswith('/fusion'):
            endpoint = f"{FUSION_API_PREFIX.rstrip('/')}/{endpoint.lstrip('/')}"
        else:
            # 如果已经是完整的 /fusion/vX/ 路径，则直接使用
            pass

        return build_api_url(self.api_base, endpoint)

    async def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[QueryParams] = None,
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        发送HTTP请求（异步）
        """
        url = self._build_url(endpoint)
        final_params = _serialize_params(params)

        # Compose headers. For the impersonated transport we rebuild the full
        # Chrome header set per call (curl_cffi was created with
        # default_headers=False). For the httpx fallback the client already
        # carries Authorization/Content-Type/User-Agent, so only extras apply.
        if self._impersonated:
            request_headers = self._default_headers(headers)
        else:
            request_headers = headers  # httpx client defaults already set

        for attempt in range(self.rate_limit_retries + 1):
            try:
                if self.status_callback:
                    await self.status_callback(f"正在向 {url} 发送 {method} 请求...")
                response = await self.client.request(
                    method=method.upper(),
                    url=url,
                    params=final_params,  # 使用副本
                    json=json_body,
                    data=data,
                    files=files,
                    headers=request_headers,  # 允许覆盖默认头
                )

                try:
                    response_data = response.json()
                except (json.JSONDecodeError, ValueError):
                    # 解析失败时抛异常以统一错误语义并避免返回临时结构
                    raw_text = response.text or ""
                    snippet = raw_text[:128]
                    message = f"Response parsing error: {snippet}"
                    raise create_exception_from_response({'message': message, 'code': response.status_code}, response.status_code)

                if response.status_code == 429 and attempt < self.rate_limit_retries:
                    await asyncio.sleep(self._rate_limit_delay(response, attempt))
                    continue

                if self.status_callback and response.status_code < 400:
                    await self.status_callback(f"成功接收到来自 {url} 的响应。")

                return handle_response(response_data, response.status_code)

            except httpx.RequestError as e:
                raise VikaException(f"Network error: {str(e)}") from e
            except Exception as e:
                # curl_cffi raises its own CurlError; normalize to VikaException
                # so callers always see a single error type on transport failure.
                if self._impersonated and not isinstance(e, VikaException):
                    raise VikaException(f"Network error: {str(e)}") from e
                raise

        raise VikaException("Request retry loop exited unexpectedly")

    def _rate_limit_delay(self, response: Any, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return self.rate_limit_base_delay * (attempt + 1)

    async def get(self, endpoint: str, params: Optional[QueryParams] = None) -> Dict[str, Any]:
        return await self.request('GET', endpoint, params=params)

    async def aget(
        self,
        endpoint: str,
        params: Optional[QueryParams] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return await self.request('GET', endpoint, params=params, headers=headers)

    async def post(
        self,
        endpoint: str,
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict] = None
    ) -> Dict[str, Any]:
        return await self.request('POST', endpoint, json_body=json_body, data=data, files=files)

    async def patch(self, endpoint: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request('PATCH', endpoint, json_body=json_body)

    async def put(self, endpoint: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request('PUT', endpoint, json_body=json_body)

    async def delete(self, endpoint: str, params: Optional[QueryParams] = None) -> Dict[str, Any]:
        return await self.request('DELETE', endpoint, params=params)

    async def close(self) -> None:
        """关闭客户端会话"""
        # curl_cffi uses ``close()``; httpx uses ``aclose()``.
        if self._impersonated:
            await self.client.close()
        else:
            await self.client.aclose()

    async def __aenter__(self) -> 'Session':
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def __repr__(self) -> str:
        # 避免在调试/日志中泄露敏感token，仅展示非敏感状态
        return f"Session(api_base='{self.api_base}')"

    def __str__(self) -> str:
        # 仅展示非敏感信息
        return f"Session({self.api_base})"


__all__ = ['Session']
