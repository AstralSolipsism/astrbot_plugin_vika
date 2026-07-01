"""
维格表空间类

兼容原vika.py库的Space类
"""
from typing import Dict, Any, Optional
from ..datasheet import DatasheetManager
from ..node import NodeManager
from ..unit import Member, Role, Team
from ..utils import get_space_id
from ..exceptions import ParameterException, NotFoundException


class Space:
    """
    空间类，表示维格表中的一个空间站
    
    兼容原vika.py库的Space接口
    """
    
    def __init__(self, apitable, space_id: str):
        """
        初始化空间
        
        Args:
            apitable: Apitable实例
            space_id: 空间站ID或URL
        """
        self._apitable = apitable
        self._space_id = get_space_id(space_id)
        
        # 初始化管理器
        self._datasheet_manager = DatasheetManager(self)
        self._node_manager = NodeManager(self)
        self._member = Member(self)
        self._role = Role(self)
        self._team = Team(self)
    
    @property
    def space_id(self) -> str:
        """空间站ID"""
        return self._space_id
    
    @property
    def datasheets(self) -> DatasheetManager:
        """数据表管理器"""
        return self._datasheet_manager
    
    @property
    def nodes(self) -> NodeManager:
        """节点管理器"""
        return self._node_manager
    
    @property
    def member(self) -> Member:
        """成员管理器"""
        return self._member
    
    @property
    def role(self) -> Role:
        """角色管理器"""
        return self._role
    
    @property
    def team(self) -> Team:
        """团队管理器"""
        return self._team
    
    def datasheet(
        self,
        dst_id_or_url: str,
        field_key: str = "name",
        field_key_map: Optional[Dict[str, str]] = None
    ):
        """
        获取数据表实例（便捷方法）
        
        Args:
            dst_id_or_url: 数据表ID或URL
            field_key: 字段键类型 ("name" 或 "id")
            field_key_map: 字段映射字典
            
        Returns:
            数据表实例
        """
        return self._datasheet_manager.get(dst_id_or_url, field_key, field_key_map)
    
    async def acreate_datasheet(
        self,
        name: str,
        description: Optional[str] = None,
        folder_id: Optional[str] = None,
        pre_filled_records: Optional[list] = None
    ):
        """
        创建数据表（异步）
        
        Args:
            name: 数据表名称
            description: 数据表描述
            folder_id: 文件夹ID
            pre_filled_records: 预填充记录
            
        Returns:
            创建的数据表实例
        """
        return await self._datasheet_manager.acreate(name, description, folder_id, pre_filled_records)
    
    async def aget_datasheet_list(self) -> list:
        """
        获取数据表列表（异步）
        
        Returns:
            数据表列表
        """
        return await self._datasheet_manager.alist()
    
    async def aget_node_list(self) -> list:
        """
        获取节点列表（异步）
        
        Returns:
            节点列表
        """
        # 关键路径异常边界：仅收敛预期异常
        try:
            nodes = await self._node_manager.alist()
        except (ParameterException, NotFoundException):
            return []
        return [node.raw_data for node in nodes]
    
    async def asearch_nodes(self, query: Optional[str] = None, node_type: Optional[str] = None) -> list:
        """
        搜索节点（异步）
        
        Args:
            query: 搜索关键词
            node_type: 节点类型
            
        Returns:
            搜索结果列表
        """
        nodes = await self._node_manager.asearch(query=query, node_type=node_type)
        return [node.raw_data for node in nodes]
    
    async def aget_space_info(self) -> Dict[str, Any]:
        """
        获取空间信息（异步）
        
        Returns:
            空间信息
        """
        spaces = await self._apitable.spaces.alist()
        for space in spaces:
            if space.get("id") == self._space_id:
                return space
        raise NotFoundException(f"Space '{self._space_id}' not found")
    
    def __str__(self) -> str:
        return f"Space({self._space_id})"
    
    def __repr__(self) -> str:
        return f"Space(space_id='{self._space_id}')"
    
    def __eq__(self, other) -> bool:
        """相等比较"""
        if not isinstance(other, Space):
            return False
        return self._space_id == other._space_id
    
    def __hash__(self) -> int:
        """哈希值"""
        return hash(self._space_id)


__all__ = ['Space']
