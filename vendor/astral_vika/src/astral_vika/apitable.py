"""
维格表主入口类

兼容原vika.py库的主类Vika/Apitable
"""
from typing import Optional, Dict, Any, Callable, Awaitable
from .const import DEFAULT_API_BASE
from .request import Session
from .space import SpaceManager
from .datasheet import Datasheet
from .node import NodeManager  
from .utils import get_dst_id, get_space_id
from .exceptions import ParameterException
import asyncio


class Vika:
    """
    维格表主客户端类
    
    兼容原vika.py库的Vika类接口
    """
    
    def __init__(self, token: str, api_base: Optional[str] = None, status_callback: Optional[Callable[[str], Awaitable[None]]] = None):
        """
        初始化维格表客户端
        
        Args:
            token: API Token
            api_base: API基础URL，可选
        """
        self._token = token
        self._api_base = api_base or DEFAULT_API_BASE
        self.status_callback = status_callback
        
        # 创建HTTP会话
        self.request_adapter = Session(token, self._api_base, status_callback=self.status_callback)
        
        # 初始化管理器
        self._space_manager = SpaceManager(self)
        self._node_manager = None  # 延迟初始化
        
        # 缓存
        self._spaces_cache = None
        # 关闭状态
        self._closed = False
    
    @property
    def api_base(self) -> str:
        """API基础URL"""
        return self._api_base
    
    @property
    def token(self) -> str:
        """API Token"""
        return self._token
    
    @property
    def spaces(self) -> SpaceManager:
        """空间管理器"""
        return self._space_manager
    
    @property
    def nodes(self) -> NodeManager:
        """全局节点管理器（需要指定空间）"""
        if self._node_manager is None:
            # 节点管理器需要空间上下文，这里只是为了接口兼容
            raise ParameterException(
                "Global nodes manager requires space context. "
                "Use vika.space(space_id).nodes instead."
            )
        return self._node_manager
    
    def set_api_base(self, api_base: str):
        """
        设置API基础URL
        
        Args:
            api_base: API基础URL
        """
        self._api_base = api_base.rstrip('/')
        # 重新创建HTTP会话
        self.request_adapter = Session(self._token, self._api_base)
    
    async def aauth(self) -> bool:
        """
        验证API Token（异步）
        
        Returns:
            是否认证成功
        """
        try:
            # 通过获取空间列表来验证token
            await self.spaces.alist()
            return True
        except Exception:
            return False
    
    def space(self, space_id: str):
        """
        获取空间实例
        
        Args:
            space_id: 空间站ID或URL
            
        Returns:
            空间实例
        """
        return self._space_manager.get(space_id)
    
    def datasheet(
        self,
        dst_id_or_url: str,
        space_id: Optional[str] = None,
        field_key: str = "name",
        field_key_map: Optional[Dict[str, str]] = None,
    ) -> Datasheet:
        """
        直接获取数据表实例（无需space_id）
        
        Args:
            dst_id_or_url: 数据表ID或URL
            space_id: 空间站ID（可选，仅少数操作需要，如创建字段）
            field_key: 字段键类型
            field_key_map: 字段映射字典
            
        Returns:
            数据表实例
        """
        dst_id = get_dst_id(dst_id_or_url)
        
        return Datasheet(
            apitable=self,
            dst_id=dst_id,
            spc_id=space_id,
            field_key=field_key,
            field_key_map=field_key_map,
            status_callback=self.status_callback
        )
    
    async def aget_spaces(self) -> list:
        """
        获取空间列表（异步）
        
        Returns:
            空间列表
        """
        return await self.spaces.alist()
    
    async def aget_space_info(self, space_id: str) -> Dict[str, Any]:
        """
        获取空间信息（异步）
        
        Args:
            space_id: 空间站ID
            
        Returns:
            空间信息
        """
        space = self.space(space_id)
        return await space.aget_space_info()
    
    async def atest_connection(self) -> bool:
        """
        测试连接（异步）
        
        Returns:
            连接是否正常
        """
        return await self.aauth()
    
    # 避免误导：之前为空实现，改为释放资源并幂等
    async def aclose(self):
        """关闭客户端连接（异步）"""
        if getattr(self, "_closed", False):
            return
        # 关闭底层HTTP会话（Session.client）
        if hasattr(self, "request_adapter") and self.request_adapter is not None:
            await self.request_adapter.close()
        self._closed = True
    
    # 同步上下文管理器支持
    def __enter__(self):
        return self
    
    # 避免误导：之前为空实现，改为同步关闭并遵循事件循环约束
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 无事件循环在运行，安全地同步关闭
            asyncio.run(self.aclose())
        else:
            # 已在事件循环中，避免在同步上下文内强行关闭
            raise RuntimeError("Apitable.__exit__ 检测到活动事件循环；请使用 'async with Vika(...)' 或显式 await vika.aclose() 以正确关闭资源")

    # 异步上下文管理器支持
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
    
    def __str__(self) -> str:
        return f"Vika(api_base='{self._api_base}')"
    
    def __repr__(self) -> str:
        return f"Vika(token='***', api_base='{self._api_base}')"


# 常见 vika.py 使用习惯兼容别名
Apitable = Vika


__all__ = ['Vika', 'Apitable']
