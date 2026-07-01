"""
维格表视图管理器

兼容原vika.py库的ViewManager类
"""
from typing import List, Dict, Any, Optional
from ..utils import timed_lru_cache
from ..exceptions import ParameterException


class View:
    """视图类"""
    
    def __init__(self, view_data: Dict[str, Any]):
        self._data = view_data
    
    @property
    def id(self) -> str:
        """视图ID"""
        return self._data.get('id', '')
    
    @property
    def name(self) -> str:
        """视图名"""
        return self._data.get('name', '')
    
    @property
    def type(self) -> str:
        """视图类型"""
        return self._data.get('type', '')
    
    @property
    def properties(self) -> Dict[str, Any]:
        """视图属性"""
        return self._data.get('properties', {})
    
    @property
    def raw_data(self) -> Dict[str, Any]:
        """原始数据"""
        return self._data
    
    def __str__(self) -> str:
        return f"View({self.name}, {self.type})"
    
    def __repr__(self) -> str:
        return f"View(id='{self.id}', name='{self.name}', type='{self.type}')"


class ViewManager:
    """
    视图管理器，提供视图相关操作
    
    兼容原vika.py库的ViewManager接口
    """
    
    def __init__(self, datasheet):
        """
        初始化视图管理器
        
        Args:
            datasheet: 数据表实例
        """
        self._datasheet = datasheet
    
    @timed_lru_cache(seconds=300)
    async def aall(self) -> List[View]:
        """
        获取所有视图（异步）
        
        Returns:
            视图列表
        """
        response = await self._aget_views()
        views_data = response.get('data', {}).get('views', [])
        return [View(view_data) for view_data in views_data]
    
    async def aget(self, view_name_or_id: str) -> View:
        """
        获取指定视图（异步）
        
        Args:
            view_name_or_id: 视图名或视图ID
            
        Returns:
            视图实例
            
        Raises:
            ParameterException: 视图不存在时
        """
        views = await self.aall()
        
        for view in views:
            if view.name == view_name_or_id or view.id == view_name_or_id:
                return view
        
        raise ParameterException(f"View '{view_name_or_id}' not found")
    
    async def aget_by_name(self, view_name: str) -> View:
        """
        根据视图名获取视图（异步）
        
        Args:
            view_name: 视图名
            
        Returns:
            视图实例
        """
        return await self.aget(view_name)
    
    async def aget_by_id(self, view_id: str) -> View:
        """
        根据视图ID获取视图（异步）
        
        Args:
            view_id: 视图ID
            
        Returns:
            视图实例
        """
        return await self.aget(view_id)
    
    async def aget_default_view(self, views: Optional[List[View]] = None) -> Optional[View]:
        """
        获取默认视图（通常是第一个视图）（异步）
        
        Args:
            views: 可选的视图列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            默认视图实例或None
        """
        if views is None:
            views = await self.aall()
        return views[0] if views else None
    
    async def afilter_by_type(self, view_type: str, views: Optional[List[View]] = None) -> List[View]:
        """
        根据视图类型过滤视图（异步）
        
        Args:
            view_type: 视图类型
            views: 可选的视图列表，如果提供则直接使用，否则调用 aall() 获取
            
        Returns:
            匹配的视图列表
        """
        if views is None:
            views = await self.aall()
        return [view for view in views if view.type == view_type]
    
    async def aexists(self, view_name_or_id: str) -> bool:
        """
        检查视图是否存在（异步）
        
        Args:
            view_name_or_id: 视图名或视图ID
            
        Returns:
            视图是否存在
        """
        try:
            await self.aget(view_name_or_id)
            return True
        except ParameterException:
            return False
    
    async def aget_view_names(self, views: Optional[List[View]] = None) -> List[str]:
        """
        获取所有视图名（异步）
        
        Args:
            views: 可选的视图列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            视图名列表
        """
        if views is None:
            views = await self.aall()
        return [view.name for view in views]
    
    async def aget_view_ids(self, views: Optional[List[View]] = None) -> List[str]:
        """
        获取所有视图ID（异步）
        
        Args:
            views: 可选的视图列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            视图ID列表
        """
        if views is None:
            views = await self.aall()
        return [view.id for view in views]
    
    async def aget_view_mapping(self, views: Optional[List[View]] = None) -> Dict[str, str]:
        """
        获取视图名到视图ID的映射（异步）
        
        Args:
            views: 可选的视图列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            视图名到视图ID的映射字典
        """
        if views is None:
            views = await self.aall()
        return {view.name: view.id for view in views}
    
    async def aget_id_mapping(self, views: Optional[List[View]] = None) -> Dict[str, str]:
        """
        获取视图ID到视图名的映射（异步）
        
        Args:
            views: 可选的视图列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            视图ID到视图名的映射字典
        """
        if views is None:
            views = await self.aall()
        return {view.id: view.name for view in views}
    
    async def aget_grid_views(self) -> List[View]:
        """
        获取表格视图（异步）
        
        Returns:
            表格视图列表
        """
        return await self.afilter_by_type("Grid")
    
    async def aget_gallery_views(self) -> List[View]:
        """
        获取画廊视图（异步）
        
        Returns:
            画廊视图列表
        """
        return await self.afilter_by_type("Gallery")
    
    async def aget_kanban_views(self) -> List[View]:
        """
        获取看板视图（异步）
        
        Returns:
            看板视图列表
        """
        return await self.afilter_by_type("Kanban")
    
    async def aget_form_views(self) -> List[View]:
        """
        获取表单视图（异步）
        
        Returns:
            表单视图列表
        """
        return await self.afilter_by_type("Form")
    
    async def aget_calendar_views(self) -> List[View]:
        """
        获取日历视图（异步）
        
        Returns:
            日历视图列表
        """
        return await self.afilter_by_type("Calendar")
    
    async def aget_gantt_views(self) -> List[View]:
        """
        获取甘特视图（异步）
        
        Returns:
            甘特视图列表
        """
        return await self.afilter_by_type("Gantt")
    
    # 内部API调用方法
    async def _aget_views(self) -> Dict[str, Any]:
        """获取视图的内部API调用"""
        endpoint = f"datasheets/{self._datasheet._dst_id}/views"
        return await self._datasheet._apitable.request_adapter.get(endpoint)
    
    async def __alen__(self) -> int:
        """返回视图数量"""
        views = await self.aall()
        return len(views)
    
    async def __aiter__(self):
        """支持异步迭代"""
        views = await self.aall()
        for view in views:
            yield view
    
    async def __acontains__(self, view_name_or_id: str) -> bool:
        """支持in操作符"""
        return await self.aexists(view_name_or_id)
    
    def __str__(self) -> str:
        return f"ViewManager({self._datasheet})"
    
    def __repr__(self) -> str:
        return f"ViewManager(datasheet={self._datasheet._dst_id})"


__all__ = ['View', 'ViewManager']
