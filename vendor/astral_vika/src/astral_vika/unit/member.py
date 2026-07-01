"""
维格表成员管理

兼容原vika.py库的Member类
"""
from typing import Dict, Any, Optional, List
from ..types.unit_model import UnitMemberCreateRo, UnitMemberUpdateRo
from ..exceptions import ParameterException, NotFoundException
from ..utils import handle_response


class Member:
    """
    成员管理类，提供成员相关操作
    
    兼容原vika.py库的Member接口
    """
    
    def __init__(self, space):
        """
        初始化成员管理器
        
        Args:
            space: 空间实例
        """
        self._space = space
    
    async def aget(self, unit_id: str) -> Dict[str, Any]:
        """
        获取成员信息（异步）
        
        Args:
            unit_id: 成员单元ID
            
        Returns:
            成员信息
        """
        response = await self._aget_member(unit_id)
        return response.get('data', {})
    
    async def alist(self) -> List[Dict[str, Any]]:
        """
        获取成员列表（异步）
        
        Returns:
            成员列表
        """
        response = await self._alist_members()
        return response.get('data', {}).get('members', [])
    
    async def acreate(self, member_data: UnitMemberCreateRo) -> Dict[str, Any]:
        """
        创建成员（异步）
        
        Args:
            member_data: 成员创建数据
            
        Returns:
            创建结果
        """
        response = await self._acreate_member(member_data.model_dump(exclude_none=True))
        return response.get('data', {})
    
    async def aupdate(self, unit_id: str, member_data: UnitMemberUpdateRo) -> Dict[str, Any]:
        """
        更新成员信息（异步）
        
        Args:
            unit_id: 成员单元ID
            member_data: 成员更新数据
            
        Returns:
            更新结果
        """
        response = await self._aupdate_member(unit_id, member_data.model_dump(exclude_none=True))
        return response.get('data', {})
    
    async def adelete(self, unit_id: str) -> bool:
        """
        删除成员（异步）
        
        Args:
            unit_id: 成员单元ID
            
        Returns:
            是否删除成功
        """
        # 依赖统一异常处理：非2xx或success=False将抛异常，避免错误返回True
        resp = await self._adelete_member(unit_id)
        handle_response(resp)
        return True
    
    async def aactivate(self, unit_id: str) -> Dict[str, Any]:
        """
        激活成员（异步）
        
        Args:
            unit_id: 成员单元ID
            
        Returns:
            更新结果
        """
        update_data = UnitMemberUpdateRo(isActive=True)
        return await self.aupdate(unit_id, update_data)
    
    async def adeactivate(self, unit_id: str) -> Dict[str, Any]:
        """
        停用成员（异步）
        
        Args:
            unit_id: 成员单元ID
            
        Returns:
            更新结果
        """
        update_data = UnitMemberUpdateRo(isActive=False)
        return await self.aupdate(unit_id, update_data)
    
    async def aexists(self, unit_id: str) -> bool:
        """
        检查成员是否存在（异步）
        
        Args:
            unit_id: 成员单元ID
            
        Returns:
            成员是否存在
        """
        try:
            await self.aget(unit_id)
            return True
        # 收窄异常：仅将未找到/参数问题视为不存在
        except (NotFoundException, ParameterException):
            return False
    
    # 内部API调用方法
    async def _aget_member(self, unit_id: str) -> Dict[str, Any]:
        """获取成员的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/members/{unit_id}"
        return await self._space._apitable.request_adapter.get(endpoint)
    
    async def _acreate_member(self, member_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建成员的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/members"
        return await self._space._apitable.request_adapter.post(endpoint, json_body=member_data)
    
    async def _aupdate_member(self, unit_id: str, member_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新成员的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/members/{unit_id}"
        return await self._space._apitable.request_adapter.put(endpoint, json_body=member_data)
    
    async def _alist_members(self) -> Dict[str, Any]:
        """获取成员列表的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/members"
        return await self._space._apitable.request_adapter.get(endpoint)
    
    async def _adelete_member(self, unit_id: str) -> Dict[str, Any]:
        """删除成员的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/members/{unit_id}"
        return await self._space._apitable.request_adapter.delete(endpoint)
    
    def __str__(self) -> str:
        return f"Member({self._space})"
    
    def __repr__(self) -> str:
        return f"Member(space={self._space._space_id})"


__all__ = ['Member']
