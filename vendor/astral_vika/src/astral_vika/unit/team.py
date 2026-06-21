"""
维格表团队管理

兼容原vika.py库的Team类
"""
from typing import Dict, Any, Optional, List, Set
from ..types.unit_model import UnitTeamCreateRo, UnitTeamUpdateRo
from ..exceptions import ParameterException, NotFoundException
from ..utils import handle_response
import re
from urllib.parse import quote


class Team:
    """
    团队管理类，提供团队相关操作
    
    兼容原vika.py库的Team接口
    """
    
    def __init__(self, space):
        """
        初始化团队管理器
        
        Args:
            space: 空间实例
        """
        self._space = space
    
    async def aget(self, unit_id: str) -> Dict[str, Any]:
        """
        获取团队信息（异步）
        
        Args:
            unit_id: 团队单元ID
            
        Returns:
            团队信息
        """
        try:
            # 优先使用团队信息API
            response = await self._aget_team(unit_id)
            return response.get('data', {})
        except Exception:
            # 如果团队信息API失败（可能是权限问题），降级到使用团队成员接口
            # 注意：此方法返回的数据可能不完整
            response = await self._aget_team_members(unit_id)
            return response.get('data', {})
    
    async def alist(
        self,
        parent_unit_id: Optional[str] = None,
        recursive: bool = True,
        page_size: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        获取团队列表（异步）

        Vika 的团队列表以父团队为入口。默认从根团队 ``0`` 开始递归读取子团队。
        
        Args:
            parent_unit_id: 父团队 unit_id；为空时从根团队 ``0`` 读取空间下团队
            recursive: 是否递归读取子团队
            page_size: 单页大小

        Returns:
            团队列表
        """
        if page_size <= 0:
            raise ParameterException("page_size must be greater than 0")

        root_unit_id = parent_unit_id or "0"
        return await self._alist_children_recursive(root_unit_id, recursive=recursive, page_size=page_size)
    
    async def acreate(self, team_data: UnitTeamCreateRo) -> Dict[str, Any]:
        """
        创建团队（异步）
        
        Args:
            team_data: 团队创建数据
            
        Returns:
            创建结果
        """
        response = await self._acreate_team(team_data.model_dump(exclude_none=True))
        return response.get('data', {})
    
    async def aupdate(self, unit_id: str, team_data: UnitTeamUpdateRo) -> Dict[str, Any]:
        """
        更新团队信息（异步）
        
        Args:
            unit_id: 团队单元ID
            team_data: 团队更新数据
            
        Returns:
            更新结果
        """
        response = await self._aupdate_team(unit_id, team_data.model_dump(exclude_none=True))
        return response.get('data', {})
    
    async def adelete(self, unit_id: str) -> bool:
        """
        删除团队（异步）
        
        Args:
            unit_id: 团队单元ID
            
        Returns:
            是否删除成功
        """
        # 依赖统一异常处理：非2xx或success=False将抛异常，避免错误返回True
        resp = await self._adelete_team(unit_id)
        handle_response(resp)
        return True
    
    async def aget_members(self, unit_id: str) -> List[Dict[str, Any]]:
        """
        获取团队成员列表（异步）
        
        Args:
            unit_id: 团队单元ID
            
        Returns:
            团队成员列表
        """
        response = await self._aget_team_members(unit_id)
        members_data = response.get('data', {}).get('members', [])
        return members_data
    
    async def aget_children(self, unit_id: str) -> List[Dict[str, Any]]:
        """
        获取子团队列表（异步）
        
        Args:
            unit_id: 团队单元ID
            
        Returns:
            子团队列表
        """
        return await self._alist_direct_children(unit_id, page_size=1000)
    
    async def aexists(self, unit_id: str) -> bool:
        """
        检查团队是否存在（异步）
        
        Args:
            unit_id: 团队单元ID
            
        Returns:
            团队是否存在
        """
        try:
            await self.aget(unit_id)
            return True
        except NotFoundException:
            # 仅在资源确实不存在时返回 False
            return False
    
    async def afind_by_name(self, team_name: str) -> Optional[Dict[str, Any]]:
        """
        根据团队名查找团队（异步）
        
        Args:
            team_name: 团队名称
            
        Returns:
            团队信息或None
        """
        teams = await self.alist()
        for team in teams:
            if team.get('name') == team_name:
                return team
        return None
    
    async def aget_team_by_name(self, team_name: str) -> Dict[str, Any]:
        """
        根据团队名获取团队（异步）
        
        Args:
            team_name: 团队名称
            
        Returns:
            团队信息
            
        Raises:
            ParameterException: 团队不存在时
        """
        team = await self.afind_by_name(team_name)
        if not team:
            raise ParameterException(f"Team '{team_name}' not found")
        return team
    
    async def aadd_member(self, unit_id: str, member_id: str) -> bool:
        """
        向团队添加成员（异步）
        
        Args:
            unit_id: 团队单元ID
            member_id: 成员ID
            
        Returns:
            是否添加成功
        """
        team_ids = await self._aget_member_team_ids(member_id)
        if unit_id not in team_ids:
            team_ids.append(unit_id)
            await self._space.member._aupdate_member(member_id, {"teams": team_ids})
        return True
    
    async def aremove_member(self, unit_id: str, member_id: str) -> bool:
        """
        从团队移除成员（异步）
        
        Args:
            unit_id: 团队单元ID
            member_id: 成员ID
            
        Returns:
            是否移除成功
        """
        team_ids = await self._aget_member_team_ids(member_id)
        if unit_id in team_ids:
            await self._space.member._aupdate_member(
                member_id,
                {"teams": [team_id for team_id in team_ids if team_id != unit_id]}
            )
        return True
    
    # 内部API调用方法
    def _normalize_unit_id(self, unit_id: str) -> str:
        """
        校验并URL编码团队unit_id，仅允许字母/数字/_-，长度1-64。
        返回经 quote(..., safe="") 编码后的路径段。
        """
        if not isinstance(unit_id, str) or not unit_id:
            raise ParameterException("unit_id cannot be empty")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", unit_id):
            raise ParameterException("Invalid unit_id format")
        return quote(unit_id, safe="")

    def _extract_team_list(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = response.get('data', response)
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        teams = data.get('teams')
        if teams is None:
            teams = data.get('children')
        if teams is None:
            teams = data.get('units')
        return teams if isinstance(teams, list) else []

    async def _alist_direct_children(self, unit_id: str, page_size: int) -> List[Dict[str, Any]]:
        page_num = 1
        teams: List[Dict[str, Any]] = []
        while True:
            response = await self._aget_team_children(unit_id, page_num=page_num, page_size=page_size)
            page = self._extract_team_list(response)
            teams.extend(page)

            data = response.get('data', {}) if isinstance(response, dict) else {}
            total = data.get('total') if isinstance(data, dict) else None
            has_more = data.get('hasMore') if isinstance(data, dict) else None
            if has_more is False:
                break
            if total is not None and len(teams) >= int(total):
                break
            if len(page) < page_size:
                break
            page_num += 1
        return teams

    async def _alist_children_recursive(self, unit_id: str, recursive: bool, page_size: int) -> List[Dict[str, Any]]:
        seen: Set[str] = set()
        result: List[Dict[str, Any]] = []

        async def walk(parent_id: str) -> None:
            children = await self._alist_direct_children(parent_id, page_size)
            for child in children:
                child_id = child.get('unitId') or child.get('id') or child.get('teamId')
                if child_id and child_id in seen:
                    continue
                if child_id:
                    seen.add(child_id)
                result.append(child)
                if recursive and child_id:
                    await walk(child_id)

        await walk(unit_id)
        return result

    def _extract_member_team_ids(self, member: Dict[str, Any]) -> List[str]:
        teams = member.get('teams') or member.get('teamIds') or []
        team_ids: List[str] = []
        for team in teams:
            if isinstance(team, str):
                team_id = team
            elif isinstance(team, dict):
                team_id = team.get('unitId') or team.get('id') or team.get('teamId')
            else:
                team_id = None
            if team_id and team_id not in team_ids:
                team_ids.append(team_id)
        return team_ids

    async def _aget_member_team_ids(self, member_id: str) -> List[str]:
        member = await self._space.member.aget(member_id)
        return self._extract_member_team_ids(member)
    
    async def _aget_team(self, unit_id: str) -> Dict[str, Any]:
        """获取团队信息的内部API调用（异步）"""
        safe_id = self._normalize_unit_id(unit_id)
        endpoint = f"spaces/{self._space._space_id}/teams/{safe_id}"
        return await self._space._apitable.request_adapter.get(endpoint)
    
    async def _aget_team_members(self, unit_id: str) -> Dict[str, Any]:
        """获取团队成员的内部API调用（异步）"""
        safe_id = self._normalize_unit_id(unit_id)
        endpoint = f"spaces/{self._space._space_id}/teams/{safe_id}/members"
        return await self._space._apitable.request_adapter.get(endpoint)
    
    async def _aget_team_children(
        self,
        unit_id: str,
        page_num: Optional[int] = None,
        page_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """获取子团队的内部API调用（异步）"""
        safe_id = self._normalize_unit_id(unit_id)
        endpoint = f"spaces/{self._space._space_id}/teams/{safe_id}/children"
        params = {}
        if page_num is not None:
            params["pageNum"] = page_num
        if page_size is not None:
            params["pageSize"] = page_size
        return await self._space._apitable.request_adapter.get(endpoint, params=params or None)

    async def _acreate_team(self, team_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建团队的内部API调用（异步）"""
        endpoint = f"spaces/{self._space._space_id}/teams"
        return await self._space._apitable.request_adapter.post(endpoint, json_body=team_data)
    
    async def _aupdate_team(self, unit_id: str, team_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新团队的内部API调用（异步）"""
        safe_id = self._normalize_unit_id(unit_id)
        endpoint = f"spaces/{self._space._space_id}/teams/{safe_id}"
        return await self._space._apitable.request_adapter.put(endpoint, json_body=team_data)
    
    async def _adelete_team(self, unit_id: str) -> Dict[str, Any]:
        """删除团队的内部API调用（异步）"""
        safe_id = self._normalize_unit_id(unit_id)
        endpoint = f"spaces/{self._space._space_id}/teams/{safe_id}"
        return await self._space._apitable.request_adapter.delete(endpoint)
    
    def __str__(self) -> str:
        return f"Team({self._space})"
    
    def __repr__(self) -> str:
        return f"Team(space={self._space._space_id})"


__all__ = ['Team']
