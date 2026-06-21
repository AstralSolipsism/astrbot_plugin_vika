"""
维格表HTTP请求处理模块

兼容原vika.py库的请求处理方式
"""
import asyncio
import httpx
import json
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple, Union

from .const import DEFAULT_API_BASE, FUSION_API_PREFIX
from .exceptions import VikaException, create_exception_from_response
from .utils import build_api_url, handle_response

QueryParams = Union[Dict[str, Any], Iterable[Tuple[str, Any]]]


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
    一个原生异步的HTTP请求会话，使用httpx库。
    """

    def __init__(self, token: str, api_base: str = DEFAULT_API_BASE, status_callback: Optional[Callable[[str], Awaitable[None]]] = None):
        # 将token存为私有字段以避免泄露
        self._token = token
        self.api_base = api_base.rstrip('/')
        self.status_callback = status_callback
        self.rate_limit_retries = 3
        self.rate_limit_base_delay = 0.6
        headers = {
            # 仅用于请求头注入，不在属性/日志中明文暴露
            'Authorization': f'Bearer {self._token}',
            'Content-Type': 'application/json',
            'User-Agent': 'vika-py/2.0.0'
        }
        self.client = httpx.AsyncClient(headers=headers, timeout=30.0)

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
                    headers=headers,  # 允许覆盖默认头
                )

                try:
                    response_data = response.json()
                except json.JSONDecodeError:
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

        raise VikaException("Request retry loop exited unexpectedly")

    def _rate_limit_delay(self, response: httpx.Response, attempt: int) -> float:
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
