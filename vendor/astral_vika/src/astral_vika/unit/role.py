"""
维格表角色管理

兼容原vika.py库的Role类
"""
from typing import Dict, Any, Optional, List
from ..types.unit_model import UnitRoleCreateRo, UnitRoleUpdateRo
from ..exceptions import ParameterException, NotFoundException


class Role:
    """
    角色管理类，提供角色相关操作
    
    兼容原vika.py库的Role接口
    """
    
    def __init__(self, space):
        """
        初始化角色管理器
        
        Args:
            space: 空间实例
        """
        self._space = space
    
    async def aget(self, unit_id: str) -> Dict[str, Any]:
        """
        获取角色信息（异步）
        
        Args:
            unit_id: 角色单元ID
            
        Returns:
            角色信息
        """
        # 通过获取角色成员列表来获取角色信息
        response = await self._aget_role_members(unit_id)
        return response.get('data', {})
    
    async def alist(self) -> List[Dict[str, Any]]:
        """
        获取角色列表（异步）
        
        Returns:
            角色列表
        """
        response = await self._aget_roles()
        roles_data = response.get('data', {}).get('roles', [])
        return roles_data
    
    async def acreate(self, role_data: UnitRoleCreateRo) -> Dict[str, Any]:
        """
        创建角色（异步）
        
        Args:
            role_data: 角色创建数据
            
        Returns:
            创建结果
        """
        response = await self._acreate_role(role_data.model_dump())
        return response.get('data', {})
    
    async def aupdate(self, unit_id: str, role_data: UnitRoleUpdateRo) -> Dict[str, Any]:
        """
        更新角色信息（异步）
        
        Args:
            unit_id: 角色单元ID
            role_data: 角色更新数据
            
        Returns:
            更新结果
        """
        response = await self._aupdate_role(unit_id, role_data.model_dump())
        return response.get('data', {})
    
    async def adelete(self, unit_id: str) -> bool:
        """
        删除角色（异步）
        
        Args:
            unit_id: 角色单元ID
            
        Returns:
            是否删除成功
        """
        await self._adelete_role(unit_id)
        return True
    
    async def aget_members(self, unit_id: str) -> List[Dict[str, Any]]:
        """
        获取角色成员列表（异步）
        
        Args:
            unit_id: 角色单元ID
            
        Returns:
            角色成员列表
        """
        response = await self._aget_role_members(unit_id)
        members_data = response.get('data', {}).get('members', [])
        return members_data
    
    async def aget_teams(self, unit_id: str) -> List[Dict[str, Any]]:
        """
        获取角色关联的团队列表（异步）
        
        Args:
            unit_id: 角色单元ID
            
        Returns:
            角色团队列表
        """
        response = await self._aget_role_members(unit_id)
        teams_data = response.get('data', {}).get('teams', [])
        return teams_data
    
    async def aexists(self, unit_id: str) -> bool:
        """
        检查角色是否存在（异步）
        
        Args:
            unit_id: 角色单元ID
            
        Returns:
            角色是否存在
        """
        try:
            await self.aget(unit_id)
            return True
        # 收窄异常：仅将未找到/参数问题视为不存在
        except (NotFoundException, ParameterException):
            return False
    
    async def afind_by_name(self, role_name: str) -> Optional[Dict[str, Any]]:
        """
        根据角色名查找角色（异步）
        
        Args:
            role_name: 角色名称
            
        Returns:
            角色信息或None
        """
        roles = await self.alist()
        for role in roles:
            if role.get('name') == role_name:
                return role
        return None
    
    async def aget_role_by_name(self, role_name: str) -> Dict[str, Any]:
        """
        根据角色名获取角色（异步）
        
        Args:
            role_name: 角色名称
            
        Returns:
            角色信息
            
        Raises:
            ParameterException: 角色不存在时
        """
        role = await self.afind_by_name(role_name)
        if not role:
            raise ParameterException(f"Role '{role_name}' not found")
        return role
    
    # 内部API调用方法
    async def _aget_roles(self) -> Dict[str, Any]:
        """获取角色列表的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/roles"
        return await self._space._apitable.request_adapter.get(endpoint)
    
    async def _aget_role_members(self, unit_id: str) -> Dict[str, Any]:
        """获取角色成员的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/roles/{unit_id}/members"
        return await self._space._apitable.request_adapter.get(endpoint)
    
    async def _acreate_role(self, role_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建角色的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/roles"
        return await self._space._apitable.request_adapter.post(endpoint, json_body=role_data)
    
    async def _aupdate_role(self, unit_id: str, role_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新角色的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/roles/{unit_id}"
        return await self._space._apitable.request_adapter.put(endpoint, json_body=role_data)
    
    async def _adelete_role(self, unit_id: str) -> Dict[str, Any]:
        """删除角色的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/roles/{unit_id}"
        return await self._space._apitable.request_adapter.delete(endpoint)
    
    def __str__(self) -> str:
        return f"Role({self._space})"
    
    def __repr__(self) -> str:
        return f"Role(space={self._space._space_id})"


__all__ = ['Role']
