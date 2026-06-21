"""
维格表节点管理器

兼容原vika.py库的NodeManager类
"""
import time
from typing import Dict, Any, Optional, List, TYPE_CHECKING, Union
from ..exceptions import ParameterException, NotFoundException
from ..types.response import NodeData, NodesData
from ..const import NODES_API_V2_PREFIX  # API 版本/前缀常量集中管理

if TYPE_CHECKING:
    from ..space.space import Space

# 分页与计数缓存参数
_NODES_PAGE_SIZE_DEFAULT = 100
_COUNT_CACHE_TTL_SECONDS = 60


class Node:
    """节点类"""
    
    def __init__(self, node_data: Dict[str, Any]):
        self._data = node_data
    
    @property
    def id(self) -> str:
        """节点ID"""
        return self._data.get('id', '')
    
    @property
    def name(self) -> str:
        """节点名"""
        return self._data.get('name', '')
    
    @property
    def type(self) -> str:
        """节点类型"""
        return self._data.get('type', '')
    
    @property
    def icon(self) -> Optional[str]:
        """节点图标"""
        return self._data.get('icon')
    
    @property
    def parent_id(self) -> Optional[str]:
        """父节点ID"""
        return self._data.get('parentId')
    
    @property
    def children(self) -> List['Node']:
        """子节点列表"""
        children_data = self._data.get('children', [])
        return [Node(child_data) for child_data in children_data]

    @property
    def is_fav(self) -> Optional[bool]:
        """是否收藏"""
        return self._data.get('isFav')

    @property
    def permission(self) -> Optional[int]:
        """节点权限"""
        return self._data.get('permission')
    
    @property
    def raw_data(self) -> Dict[str, Any]:
        """原始数据"""
        return self._data
    
    def __str__(self) -> str:
        return f"Node({self.name}, {self.type})"
    
    def __repr__(self) -> str:
        return f"Node(id='{self.id}', name='{self.name}', type='{self.type}')"


class NodeManager:
    """
    节点管理器，提供文件节点相关操作
    
    兼容原vika.py库的NodeManager接口
    """
    
    def __init__(self, space: "Space"):
        """
        初始化节点管理器
        
        Args:
            space: 空间实例
        """
        self._space = space
        # 单实例生命周期内的全量结果缓存
        self._all_nodes_cache: Optional[List[Node]] = None
        # 计数短期缓存
        self._count_cache: Optional[int] = None
        self._count_cache_ts: float = 0.0
    
    async def alist(self) -> List[Node]:
        """
        获取节点列表（异步）
        
        Returns:
            节点列表
        """
        # 命中缓存直接返回
        if self._all_nodes_cache is not None:
            return self._all_nodes_cache
        response = await self._aget_nodes()
        nodes_data = response.get('data', {}).get('nodes', [])
        self._all_nodes_cache = [Node(node_data) for node_data in nodes_data]
        return self._all_nodes_cache
    
    async def aall(self) -> List[Node]:
        """
        获取所有节点（异步，别名方法）
        
        Returns:
            节点列表
        """
        return await self.alist()
    
    async def aget(self, node_id: str) -> Node:
        """
        获取指定节点（异步）
        
        Args:
            node_id: 节点ID
            
        Returns:
            节点实例
        """
        response = await self._aget_node_detail(node_id)
        node_data = response.get('data', {})
        return Node(node_data)
    
    async def asearch(
        self,
        node_type: Optional[str] = None,
        permission: Optional[int] = None,
        query: Optional[str] = None,
        permissions: Optional[Union[int, str, List[Union[int, str]]]] = None
    ) -> List[Node]:
        """
        根据类型和权限搜索节点（异步），使用v2 API。
        
        Args:
            node_type: 节点类型，例如 'Datasheet'
            permission: 权限级别
            query: 搜索关键词
            permissions: 权限级别，支持逗号字符串或列表
            
        Returns:
            匹配的节点列表
        """
        params = {}
        if node_type:
            params['type'] = node_type
        if query:
            params['query'] = query
        if permissions is None and permission is not None:
            permissions = permission
        if permissions is not None:
            if isinstance(permissions, list):
                params['permissions'] = ",".join(str(item) for item in permissions)
            else:
                params['permissions'] = permissions
        
        response = await self._asearch_nodes(params)
        nodes_data = response.get('data', {}).get('nodes', [])
        return [Node(node_data) for node_data in nodes_data]
    
    async def afilter_by_type(self, node_type: str) -> List[Node]:
        """
        根据节点类型过滤节点（异步）
        
        Args:
            node_type: 节点类型
            
        Returns:
            匹配的节点列表
        """
        # 优先尝试服务端过滤
        try:
            nodes = await self.asearch(node_type=node_type)
            return nodes
        except Exception:
            # 无法确认后端支持时，回退到本地过滤并复用缓存
            pass
        nodes = await self.alist()
        return [node for node in nodes if node.type == node_type]
    
    async def aget_datasheets(self) -> List[Node]:
        """
        获取数据表节点（异步）
        
        Returns:
            数据表节点列表
        """
        return await self.afilter_by_type("Datasheet")
    
    async def aget_folders(self) -> List[Node]:
        """
        获取文件夹节点（异步）
        
        Returns:
            文件夹节点列表
        """
        return await self.afilter_by_type("Folder")
    
    async def aget_forms(self) -> List[Node]:
        """
        获取表单节点（异步）
        
        Returns:
            表单节点列表
        """
        return await self.afilter_by_type("Form")
    
    async def aexists(self, node_id: str) -> bool:
        """
        检查节点是否存在（异步）
        
        Args:
            node_id: 节点ID
            
        Returns:
            节点是否存在
        """
        try:
            await self.aget(node_id)
            return True
        # 收窄异常：仅将未找到/参数问题视为不存在
        except (NotFoundException, ParameterException):
            return False
    
    async def afind_by_name(self, node_name: str, node_type: Optional[str] = None) -> Optional[Node]:
        """
        根据节点名查找节点（异步）
        
        Args:
            node_name: 节点名称
            node_type: 节点类型（可选）
            
        Returns:
            节点实例或None
        """
        nodes = await self.alist()
        for node in nodes:
            if node.name == node_name:
                if node_type is None or node.type == node_type:
                    return node
        return None
    
    async def aget_node_by_name(self, node_name: str, node_type: Optional[str] = None) -> Node:
        """
        根据节点名获取节点（异步）
        
        Args:
            node_name: 节点名称
            node_type: 节点类型（可选）
            
        Returns:
            节点实例
            
        Raises:
            ParameterException: 节点不存在时
        """
        node = await self.afind_by_name(node_name, node_type)
        if not node:
            type_info = f" of type '{node_type}'" if node_type else ""
            raise ParameterException(f"Node '{node_name}'{type_info} not found")
        return node
    
    async def acreate_embed_link(
        self,
        node_id: str,
        theme: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        创建嵌入链接（异步）
        
        Args:
            node_id: 节点ID
            theme: 主题
            payload: 额外参数
            
        Returns:
            创建结果
        """
        response = await self._acreate_embed_link(node_id, theme, payload)
        return response.get('data', {})
    
    async def aget_embed_links(self, node_id: str) -> List[Dict[str, Any]]:
        """
        获取嵌入链接列表（异步）
        
        Args:
            node_id: 节点ID
            
        Returns:
            嵌入链接列表
        """
        response = await self._aget_embed_links(node_id)
        links_data = response.get('data', {}).get('embedLinks', [])
        return links_data
    
    async def adelete_embed_link(self, node_id: str, link_id: str) -> bool:
        """
        删除嵌入链接（异步）
        
        Args:
            node_id: 节点ID
            link_id: 链接ID
            
        Returns:
            是否删除成功
        """
        await self._adelete_embed_link(node_id, link_id)
        return True
    
    # 内部API调用方法
    async def _aget_nodes(self) -> Dict[str, Any]:
        """获取节点列表的内部API调用"""
        endpoint = f"spaces/{self._space._space_id}/nodes"
        return await self._space._apitable.request_adapter.get(endpoint)

    async def _asearch_nodes(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """搜索节点的内部API调用 (v2)"""
        # API 版本/前缀常量集中管理
        v2_endpoint = f"{NODES_API_V2_PREFIX}/spaces/{self._space._space_id}/nodes"
        return await self._space._apitable.request_adapter.aget(v2_endpoint, params=params)
    
    async def _aget_node_detail(self, node_id: str) -> Dict[str, Any]:
        """获取节点详情的内部API调用"""
        endpoint = f"spaces/{self._space._space_id}/nodes/{node_id}"
        return await self._space._apitable.request_adapter.get(endpoint)
    
    
    async def _acreate_embed_link(
        self,
        node_id: str,
        theme: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """创建嵌入链接的内部API调用"""
        endpoint = f"spaces/{self._space._space_id}/nodes/{node_id}/embedlinks"
        
        data = {}
        if theme:
            data['theme'] = theme
        if payload:
            data['payload'] = payload
        
        return await self._space._apitable.request_adapter.post(endpoint, json_body=data)
    
    async def _aget_embed_links(self, node_id: str) -> Dict[str, Any]:
        """获取嵌入链接的内部API调用"""
        endpoint = f"spaces/{self._space._space_id}/nodes/{node_id}/embedlinks"
        return await self._space._apitable.request_adapter.get(endpoint)
    
    async def _adelete_embed_link(self, node_id: str, link_id: str) -> Dict[str, Any]:
        """删除嵌入链接的内部API调用"""
        endpoint = f"spaces/{self._space._space_id}/nodes/{node_id}/embedlinks/{link_id}"
        return await self._space._apitable.request_adapter.delete(endpoint)
    
    async def __len__(self) -> int:
        """返回节点数量"""
        # 计数端点/缓存避免全量请求
        now = time.monotonic()
        if self._count_cache is not None and (now - self._count_cache_ts) < _COUNT_CACHE_TTL_SECONDS:
            return self._count_cache
        # 优先使用已存在的全量缓存
        if self._all_nodes_cache is not None:
            count = len(self._all_nodes_cache)
            self._count_cache = count
            self._count_cache_ts = now
            return count
        # 尝试最小页请求以获取统计信息（若后端不返回统计，则保守返回）
        try:
            resp = await self._asearch_nodes({'pageNum': 1, 'pageSize': 1})
            data = resp.get('data', {}) or {}
            if 'total' in data:
                count = int(data.get('total') or 0)
                self._count_cache = count
                self._count_cache_ts = now
                return count
            # 若无total，尽量避免全量请求；保守返回近似或0（局限已注释）
            nodes_data = data.get('nodes', []) or []
            has_more = data.get('hasMore')
            if has_more is False:
                count = len(nodes_data)
            else:
                # 无明确统计字段；返回缓存值或0，并标注局限
                count = 0
            self._count_cache = count
            self._count_cache_ts = now
            return count
        except Exception:
            # 失败时不触发全量下载，返回缓存值或0
            return self._count_cache if self._count_cache is not None else 0
    
    async def __aiter__(self):
        """支持异步迭代"""
        # 分页流式yield降低内存峰值
        page_num = 1
        page_size = _NODES_PAGE_SIZE_DEFAULT
        while True:
            try:
                resp = await self._asearch_nodes({'pageNum': page_num, 'pageSize': page_size})
            except Exception:
                # 回退：若v2分页不可用，使用全量缓存一次性遍历
                nodes = await self.alist()
                for node in nodes:
                    yield node
                return
            data = resp.get('data', {}) or {}
            nodes_data = data.get('nodes', []) or []
            if not nodes_data:
                return
            for nd in nodes_data:
                yield Node(nd)
            has_more = data.get('hasMore')
            if has_more is False:
                return
            if len(nodes_data) < page_size:
                return
            page_num += 1
    
    def __str__(self) -> str:
        return f"NodeManager({self._space})"
    
    def __repr__(self) -> str:
        return f"NodeManager(space={self._space._space_id})"


__all__ = ['Node', 'NodeManager']
