"""
维格表数据表类

兼容原vika.py库的Datasheet类
"""
from typing import Dict, Any, Optional, List, Callable, Awaitable
from .record_manager import RecordManager
from .field_manager import FieldManager, Field
from .view_manager import ViewManager, View
from .attachment_manager import AttachmentManager
from ..utils import get_dst_id, timed_lru_cache
from ..exceptions import ParameterException


class Datasheet:
    """
    数据表类，表示维格表中的一个数据表
    
    兼容原vika.py库的Datasheet接口
    """
    
    def __init__(
        self,
        apitable,
        dst_id: str,
        spc_id: Optional[str] = None,
        field_key: str = "name",
        field_key_map: Optional[Dict[str, str]] = None,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None
    ):
        """
        初始化数据表
        
        Args:
            apitable: Apitable实例
            dst_id: 数据表ID或URL
            spc_id: 空间站ID
            field_key: 字段键类型 ("name" 或 "id")
            field_key_map: 字段映射字典
        """
        self._apitable = apitable
        self._dst_id = get_dst_id(dst_id)
        self._spc_id = spc_id
        self._field_key = field_key
        self._field_key_map = field_key_map or {}
        self._status_callback = status_callback
        
        # 初始化管理器
        self._record_manager = RecordManager(self)
        self._field_manager = FieldManager(self)
        self._view_manager = ViewManager(self)
        self._attachment_manager = AttachmentManager(self, status_callback=self._status_callback)
        
        # 缓存
        self._meta_cache = None
    
    @property
    def dst_id(self) -> str:
        """数据表ID"""
        return self._dst_id
    
    @property
    def datasheet_id(self) -> str:
        """数据表ID（别名）"""
        return self._dst_id
    
    @property
    def space_id(self) -> Optional[str]:
        """空间站ID"""
        return self._spc_id
    
    @property
    def field_key(self) -> str:
        """字段键类型"""
        return self._field_key
    
    @property
    def field_key_map(self) -> Dict[str, str]:
        """字段映射字典"""
        return self._field_key_map
    
    @property
    def records(self) -> RecordManager:
        """记录管理器"""
        return self._record_manager
    
    @property
    def fields(self) -> FieldManager:
        """字段管理器"""
        return self._field_manager
    
    @property
    def views(self) -> ViewManager:
        """视图管理器"""
        return self._view_manager
    
    @property
    def attachments(self) -> AttachmentManager:
        """附件管理器"""
        return self._attachment_manager
    
    async def aget_primary_field(self) -> Optional[Field]:
        """主字段（异步）"""
        return await self.fields.aget_primary_field()
    
    async def arefresh(self):
        """
        刷新数据表缓存（异步）
        """
        # 清除所有缓存
        if hasattr(self.fields, 'cache_clear'):
            self.fields.cache_clear()
        if hasattr(self._field_manager.aall, 'cache_clear'):
            self._field_manager.aall.cache_clear()
        if hasattr(self._view_manager.aall, 'cache_clear'):
            self._view_manager.aall.cache_clear()
        
        self._meta_cache = None
    
    async def aget_fields(self) -> List[Field]:
        """
        获取字段列表（异步）
        
        Returns:
            字段列表
        """
        return await self.fields.aall()
    
    async def aget_field(self, field_name_or_id: str) -> Field:
        """
        获取指定字段（异步）
        
        Args:
            field_name_or_id: 字段名或字段ID
            
        Returns:
            字段实例
        """
        return await self.fields.aget(field_name_or_id)
    
    async def aget_views(self) -> List[View]:
        """
        获取视图列表（异步）
        
        Returns:
            视图列表
        """
        return await self.views.aall()
    
    async def aget_view(self, view_name_or_id: str) -> View:
        """
        获取指定视图（异步）
        
        Args:
            view_name_or_id: 视图名或视图ID
            
        Returns:
            视图实例
        """
        return await self.views.aget(view_name_or_id)
    
    def set_field_key(self, field_key: str):
        """
        设置字段键类型
        
        Args:
            field_key: 字段键类型 ("name" 或 "id")
        """
        if field_key not in ["name", "id"]:
            raise ParameterException("field_key must be 'name' or 'id'")
        self._field_key = field_key
    
    def set_field_key_map(self, field_key_map: Dict[str, str]):
        """
        设置字段映射
        
        Args:
            field_key_map: 字段映射字典
        """
        self._field_key_map = field_key_map or {}
    
    def add_field_key_map(self, original_name: str, mapped_name: str):
        """
        添加字段映射
        
        Args:
            original_name: 原字段名
            mapped_name: 映射后的字段名
        """
        self._field_key_map[original_name] = mapped_name
    
    def remove_field_key_map(self, original_name: str):
        """
        移除字段映射
        
        Args:
            original_name: 原字段名
        """
        self._field_key_map.pop(original_name, None)
    
    def clear_field_key_map(self):
        """清除所有字段映射"""
        self._field_key_map.clear()
    
    def get_mapped_field_name(self, original_name: str) -> str:
        """
        获取映射后的字段名
        
        Args:
            original_name: 原字段名
            
        Returns:
            映射后的字段名或原字段名
        """
        return self._field_key_map.get(original_name, original_name)
    
    async def aupload_file(self, file_path: str) -> Dict[str, Any]:
        """
        上传文件到数据表（异步，原库兼容方法）
        
        Args:
            file_path: 文件路径
            
        Returns:
            上传后的附件信息
        """
        attachment = await self.attachments.aupload(file_path)
        return attachment.raw_data
    
    async def aget_meta(self) -> Dict[str, Any]:
        """
        获取数据表元数据（异步）
        
        Returns:
            数据表元数据
        """
        if self._meta_cache is None:
            # 合并字段和视图信息作为元数据
            fields = await self.aget_fields()
            views = await self.aget_views()
            self._meta_cache = {
                "datasheet": {
                    "id": self._dst_id,
                    "spaceId": self._spc_id
                },
                "fields": [field.raw_data for field in fields],
                "views": [view.raw_data for view in views]
            }
        
        return self._meta_cache
    
    def __str__(self) -> str:
        return f"Datasheet({self._dst_id})"
    
    def __repr__(self) -> str:
        return f"Datasheet(dst_id='{self._dst_id}', space_id='{self._spc_id}')"
    
    def __eq__(self, other) -> bool:
        """相等比较"""
        if not isinstance(other, Datasheet):
            return False
        return self._dst_id == other._dst_id
    
    def __hash__(self) -> int:
        """哈希值"""
        return hash(self._dst_id)


__all__ = ['Datasheet']
