"""
维格表字段管理器

兼容原vika.py库的FieldManager类
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from ..utils import timed_lru_cache
from ..exceptions import ParameterException, FieldNotFoundException
from ..types.response import CreateFieldResponseData


class Field:
    """字段类"""
    
    def __init__(self, field_data: Dict[str, Any]):
        self._data = field_data
    
    @property
    def id(self) -> str:
        """字段ID"""
        return self._data.get('id', '')
    
    @property
    def name(self) -> str:
        """字段名"""
        return self._data.get('name', '')
    
    @property
    def type(self) -> str:
        """字段类型"""
        return self._data.get('type', '')
    
    @property
    def properties(self) -> Dict[str, Any]:
        """字段属性"""
        return self._data.get('properties', self._data.get('property', {}))
    
    @property
    def editable(self) -> bool:
        """是否可编辑"""
        return self._data.get('editable', True)
    
    @property
    def is_primary(self) -> bool:
        """是否为主字段"""
        return self._data.get('isPrimary', False)
    
    @property
    def raw_data(self) -> Dict[str, Any]:
        """原始数据"""
        return self._data
    
    def __str__(self) -> str:
        return f"Field({self.name}, {self.type})"
    
    def __repr__(self) -> str:
        return f"Field(id='{self.id}', name='{self.name}', type='{self.type}')"


class FieldManager:
    """
    字段管理器，提供字段相关操作
    
    兼容原vika.py库的FieldManager接口
    """
    
    def __init__(self, datasheet):
        """
        初始化字段管理器
        
        Args:
            datasheet: 数据表实例
        """
        self._datasheet = datasheet
    
    @timed_lru_cache(seconds=300)
    async def aall(self) -> List[Field]:
        """
        获取所有字段（异步）
        
        Returns:
            字段列表
        """
        response = await self._aget_fields()
        fields_data = response.get('data', {}).get('fields', [])
        return [Field(field_data) for field_data in fields_data]
    
    async def aget(self, field_name_or_id: str) -> Field:
        """
        获取指定字段（异步）
        
        Args:
            field_name_or_id: 字段名或字段ID
            
        Returns:
            字段实例
            
        Raises:
            FieldNotFoundException: 字段不存在时
        """
        fields = await self.aall()
        
        for field in fields:
            if field.name == field_name_or_id or field.id == field_name_or_id:
                return field
        
        raise FieldNotFoundException(f"Field '{field_name_or_id}' not found")
    
    async def aget_by_name(self, field_name: str) -> Field:
        """
        根据字段名获取字段（异步）
        
        Args:
            field_name: 字段名
            
        Returns:
            字段实例
        """
        return await self.aget(field_name)
    
    async def aget_by_id(self, field_id: str) -> Field:
        """
        根据字段ID获取字段（异步）
        
        Args:
            field_id: 字段ID
            
        Returns:
            字段实例
        """
        return await self.aget(field_id)
    
    async def aget_primary_field(self, fields: Optional[List[Field]] = None) -> Optional[Field]:
        """
        获取主字段（异步）
        
        Args:
            fields: 可选的字段列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            主字段实例或None
        """
        if fields is None:
            fields = await self.aall()
        for field in fields:
            if field.is_primary:
                return field
        return None
    
    async def afilter_by_type(self, field_type: str, fields: Optional[List[Field]] = None) -> List[Field]:
        """
        根据字段类型过滤字段（异步）
        
        Args:
            field_type: 字段类型
            fields: 可选的字段列表，如果提供则直接使用，否则调用 aall() 获取
            
        Returns:
            匹配的字段列表
        """
        if fields is None:
            fields = await self.aall()
        return [field for field in fields if field.type == field_type]
    
    async def aget_editable_fields(self, fields: Optional[List[Field]] = None) -> List[Field]:
        """
        获取可编辑字段（异步）
        
        Args:
            fields: 可选的字段列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            可编辑字段列表
        """
        if fields is None:
            fields = await self.aall()
        return [field for field in fields if field.editable]
    
    async def aexists(self, field_name_or_id: str) -> bool:
        """
        检查字段是否存在（异步）
        
        Args:
            field_name_or_id: 字段名或字段ID
            
        Returns:
            字段是否存在
        """
        try:
            await self.aget(field_name_or_id)
            return True
        except FieldNotFoundException:
            return False
    
    async def acreate(
        self,
        field_type: str,
        name: str,
        property: Optional[BaseModel] = None
    ) -> CreateFieldResponseData:
        """
        创建字段（异步）

        Args:
            field_type: 字段类型
            name: 字段名
            property: 字段属性，使用Pydantic模型

        Returns:
            包含新字段ID和名称的响应数据
        """
        if not self._datasheet._spc_id:
            raise ParameterException("Space ID is required for field creation")

        response = await self._acreate_field(name, field_type, property)
        
        # 清除缓存以获取最新字段列表
        self.aall.cache_clear()  # type: ignore
        
        return CreateFieldResponseData(**response.get('data', {}))

    # 返回语义与全库删除接口对齐：使用 bool
    async def adelete(self, field_name_or_id: str) -> bool:
        """
        删除字段（异步）

        Args:
            field_name_or_id: 字段名或字段ID

        Returns:
            是否删除成功
        """
        if not self._datasheet._spc_id:
            raise ParameterException("Space ID is required for field deletion")

        field = await self.aget(field_name_or_id)
        await self._adelete_field(field.id)

        # 清除缓存以获取最新字段列表
        self.aall.cache_clear()  # type: ignore
        
        return True
    
    async def aget_field_names(self, fields: Optional[List[Field]] = None) -> List[str]:
        """
        获取所有字段名（异步）
        
        Args:
            fields: 可选的字段列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            字段名列表
        """
        if fields is None:
            fields = await self.aall()
        return [field.name for field in fields]
    
    async def aget_field_ids(self, fields: Optional[List[Field]] = None) -> List[str]:
        """
        获取所有字段ID（异步）
        
        Args:
            fields: 可选的字段列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            字段ID列表
        """
        if fields is None:
            fields = await self.aall()
        return [field.id for field in fields]
    
    async def aget_field_mapping(self, fields: Optional[List[Field]] = None) -> Dict[str, str]:
        """
        获取字段名到字段ID的映射（异步）
        
        Args:
            fields: 可选的字段列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            字段名到字段ID的映射字典
        """
        if fields is None:
            fields = await self.aall()
        return {field.name: field.id for field in fields}
    
    async def aget_id_mapping(self, fields: Optional[List[Field]] = None) -> Dict[str, str]:
        """
        获取字段ID到字段名的映射（异步）
        
        Args:
            fields: 可选的字段列表，如果提供则直接使用，否则调用 aall() 获取
        
        Returns:
            字段ID到字段名的映射字典
        """
        if fields is None:
            fields = await self.aall()
        return {field.id: field.name for field in fields}
    
    # 内部API调用方法
    async def _aget_fields(self) -> Dict[str, Any]:
        """获取字段的内部API调用"""
        endpoint = f"datasheets/{self._datasheet._dst_id}/fields"
        return await self._datasheet._apitable.request_adapter.get(endpoint)
    
    async def _acreate_field(
        self,
        name: str,
        field_type: str,
        property: Optional[BaseModel] = None
    ) -> Dict[str, Any]:
        """创建字段的内部API调用"""
        endpoint = f"spaces/{self._datasheet._spc_id}/datasheets/{self._datasheet._dst_id}/fields"
        
        data: Dict[str, Any] = {
            "name": name,
            "type": field_type
        }
        if property:
            data["property"] = property.model_dump(exclude_none=True)
        
        return await self._datasheet._apitable.request_adapter.post(endpoint, json_body=data)
    
    async def _adelete_field(self, field_id: str) -> Dict[str, Any]:
        """删除字段的内部API调用"""
        endpoint = f"spaces/{self._datasheet._spc_id}/datasheets/{self._datasheet._dst_id}/fields/{field_id}"
        return await self._datasheet._apitable.request_adapter.delete(endpoint)
    
    async def __alen__(self) -> int:
        """返回字段数量"""
        fields = await self.aall()
        return len(fields)
    
    async def __aiter__(self):
        """支持异步迭代"""
        fields = await self.aall()
        for field in fields:
            yield field
    
    async def __acontains__(self, field_name_or_id: str) -> bool:
        """支持in操作符"""
        return await self.aexists(field_name_or_id)
    
    def __str__(self) -> str:
        return f"FieldManager({self._datasheet})"
    
    def __repr__(self) -> str:
        return f"FieldManager(datasheet={self._datasheet._dst_id})"


__all__ = ['Field', 'FieldManager']
