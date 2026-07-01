"""
维格表记录类

兼容原vika.py库的Record类
"""
from typing import Dict, Any, Optional, Union, List
from datetime import datetime
from pydantic import parse_obj_as
# 引入模块级 logger
import logging
import asyncio
from ..exceptions import ParameterException, FieldNotFoundException
from ..types.response import AttachmentData, UrlData, WorkDocData, Field
from ..types.unit_model import MemberModel
from ..utils import run_sync
logger = logging.getLogger(__name__)

# 字段类型到Pydantic模型的映射
FIELD_TYPE_MAP = {
    "Attachment": AttachmentData,
    "Member": MemberModel,
    "URL": UrlData,
    "WorkDoc": WorkDocData,
}

# 需要解析为列表的字段类型
LIST_FIELD_TYPES = {"Attachment", "Member", "WorkDoc", "MultiSelect"}


class Record:
    """
    记录类，表示数据表中的一条记录
    
    兼容原vika.py库的Record类接口
    """
    
    def __init__(self, record_data: Dict[str, Any], datasheet=None):
        """
        初始化记录
        
        Args:
            record_data: 记录原始数据
            datasheet: 所属数据表实例
        """
        self._data = record_data
        self._datasheet = datasheet
        self._field_cache: Dict[str, Any] = {}
    
    @property
    def record_id(self) -> Optional[str]:
        """记录ID"""
        return self._data.get('recordId')
    
    @property
    def id(self) -> Optional[str]:
        """记录ID（别名）"""
        return self.record_id
    
    @property
    def fields(self) -> Dict[str, Any]:
        """记录字段数据"""
        return self._data.get('fields', {})
    
    @property
    def created_at(self) -> Optional[str]:
        """创建时间"""
        return self._data.get('createdAt')
    
    @property
    def updated_at(self) -> Optional[str]:
        """更新时间"""
        return self._data.get('updatedAt')
    
    @property
    def raw_data(self) -> Dict[str, Any]:
        """原始数据"""
        return self._data
    
    def get(self, field_name: str) -> Any:
        """
        获取经过类型解析后的字段值。
        结果会被缓存，后续访问将直接返回缓存值。

        Args:
            field_name: 字段名

        Returns:
            解析后的字段值

        Raises:
            FieldNotFoundException: 如果数据表中不存在该字段。
            ParameterException: 在无 datasheet 上下文时访问依赖元数据的字段。
        """
        if field_name in self._field_cache:
            return self._field_cache[field_name]

        # 依赖 datasheet 元信息时做显式校验，避免 AttributeError
        if self._datasheet is None:
            raise ParameterException("Cannot access record fields requiring datasheet context")

        field_meta = self._datasheet.fields.get(field_name)
        if not field_meta:
            raise FieldNotFoundException(f"Field '{field_name}' not found in datasheet.")

        raw_value = self.fields.get(field_name)
        if raw_value is None:
            return None

        field_type = field_meta.type
        parsed_value = raw_value

        try:
            if field_type in FIELD_TYPE_MAP:
                model = FIELD_TYPE_MAP[field_type]
                if field_type in LIST_FIELD_TYPES:
                    parsed_value = parse_obj_as(List[model], raw_value)
                else:
                    parsed_value = parse_obj_as(model, raw_value)
            elif field_type == "DateTime" and isinstance(raw_value, int):
                # Vika时间戳是毫秒，需要转换为秒
                parsed_value = datetime.fromtimestamp(raw_value / 1000)
        except Exception as e:
            # 如果解析失败，返回原始值并打印警告
            # 在实际应用中可能需要更完善的日志记录
            # print→logger，遵循日志规范
            logger.warning(
                "Warning: Failed to parse field '%s' with type '%s'. Returning raw value. Error: %s",
                field_name,
                field_type,
                e,
            )
            parsed_value = raw_value

        self._field_cache[field_name] = parsed_value
        return parsed_value

    def __getattr__(self, name: str) -> Any:
        """
        允许通过属性访问字段，例如：record.title
        """
        try:
            # 将驼峰命名转换为下划线命名，以匹配可能的字段名
            # 例如：record.recordId -> self.get("recordId")
            # 注意：这里仅为示例，实际字段名以datasheet中的为准
            return self.get(name)
        except FieldNotFoundException:
            # 如果字段不存在，则抛出标准的AttributeError
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def get_field(self, field_name: str, default=None) -> Any:
        """
        获取字段值（兼容旧版，建议使用 record.get(field_name) 或 record.field_name）
        """
        try:
            return self.get(field_name)
        except FieldNotFoundException:
            return default

    def set_field(self, field_name: str, value: Any):
        """
        设置字段值
        
        Args:
            field_name: 字段名
            value: 字段值
        """
        if 'fields' not in self._data:
            self._data['fields'] = {}
        self._data['fields'][field_name] = value
    
    def __getitem__(self, field_name: str) -> Any:
        """支持下标访问字段"""
        return self.get(field_name)
    
    def __setitem__(self, field_name: str, value: Any):
        """支持下标设置字段"""
        self.set_field(field_name, value)
    
    def __contains__(self, field_name: str) -> bool:
        """支持in操作符检查字段是否存在"""
        return field_name in self.fields
    
    def keys(self):
        """返回字段名列表"""
        return self.fields.keys()
    
    def values(self):
        """返回字段值列表"""
        return self.fields.values()
    
    def items(self):
        """返回字段名值对"""
        return self.fields.items()
    
    def to_dict(self, include_meta: bool = True) -> Dict[str, Any]:
        """
        转换为字典格式
        
        Args:
            include_meta: 是否包含元数据（recordId等）
            
        Returns:
            字典格式的记录数据
        """
        if include_meta:
            return self._data.copy()
        else:
            return self.fields.copy()
    
    def update_fields(self, fields: Dict[str, Any]):
        """
        批量更新字段
        
        Args:
            fields: 要更新的字段字典
        """
        if 'fields' not in self._data:
            self._data['fields'] = {}
        self._data['fields'].update(fields)
    
    async def asave(self):
        """
        保存记录到数据表（异步）
        
        Returns:
            更新结果
        """
        if not self._datasheet:
            raise ParameterException("Cannot save record without datasheet reference")
        
        if not self.record_id:
            # 新记录，执行创建
            return await self._datasheet.records.acreate([self.to_dict(include_meta=False)])
        else:
            # 更新现有记录
            return await self._datasheet.records.aupdate([self.to_dict()])
    
    def save(self):
        """
        保存记录到数据表（同步兼容包装）。

        在已有事件循环中请使用 await record.asave()。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run_sync(self.asave())
        raise RuntimeError("Record.save() cannot be called within a running event loop; use 'await record.asave()' instead.")
    
    async def adelete(self):
        """
        删除记录（异步）
        
        Returns:
            删除结果
        """
        if not self._datasheet:
            raise ParameterException("Cannot delete record without datasheet reference")
        
        if not self.record_id:
            raise ParameterException("Cannot delete record without record_id")
        
        return await self._datasheet.records.adelete([self.record_id])
    
    def delete(self):
        """
        删除记录（同步兼容包装）。

        在已有事件循环中请使用 await record.adelete()。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run_sync(self.adelete())
        raise RuntimeError("Record.delete() cannot be called within a running event loop; use 'await record.adelete()' instead.")
    
    def __str__(self) -> str:
        """字符串表示"""
        return f"Record(id='{self.record_id}')"
    
    def __repr__(self) -> str:
        """详细字符串表示"""
        # 为了避免在repr中触发所有字段的解析，我们只显示原始字段
        return f"Record(record_id='{self.record_id}', raw_fields={self.fields})"
    
    def __eq__(self, other) -> bool:
        """相等比较"""
        if not isinstance(other, Record):
            return False
        return self.record_id == other.record_id
    
    def __hash__(self) -> int:
        """哈希值"""
        return hash(self.record_id) if self.record_id else hash(id(self))


class RecordBuilder:
    """
    记录构建器，用于创建新记录
    """
    
    def __init__(self, datasheet=None):
        self._fields = {}
        self._datasheet = datasheet
    
    def set_field(self, field_name: str, value: Any):
        """设置字段值"""
        self._fields[field_name] = value
        return self
    
    def set_fields(self, fields: Dict[str, Any]):
        """批量设置字段"""
        self._fields.update(fields)
        return self
    
    def build(self) -> Record:
        """构建记录对象"""
        record_data = {'fields': self._fields.copy()}
        return Record(record_data, self._datasheet)
    
    async def asave(self):
        """构建并保存记录（异步）"""
        record = self.build()
        if self._datasheet:
            return await self._datasheet.records.acreate([record.to_dict(include_meta=False)])
        else:
            raise ParameterException("Cannot save record without datasheet reference")
    
    def save(self):
        """构建并保存记录（同步兼容包装）"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run_sync(self.asave())
        raise RuntimeError("RecordBuilder.save() cannot be called within a running event loop; use 'await builder.asave()' instead.")


__all__ = ['Record', 'RecordBuilder']
