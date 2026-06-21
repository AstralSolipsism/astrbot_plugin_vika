"""
维格表记录管理器

兼容原vika.py库的RecordManager类
"""
from typing import List, Dict, Any, Optional, Union, Sequence
from .record import Record
from .query_set import QuerySet
from ..const import MAX_RECORDS_PER_PROCESS
from ..utils import format_records_for_api, chunk_list
from ..exceptions import ParameterException


class RecordManager:
    """
    记录管理器，提供记录的CRUD操作
    
    兼容原vika.py库的RecordManager接口
    """
    
    def __init__(self, datasheet):
        """
        初始化记录管理器
        
        Args:
            datasheet: 数据表实例
        """
        self._datasheet = datasheet
    
    def get_queryset(self) -> QuerySet:
        """
        获取查询集
        
        Returns:
            QuerySet实例
        """
        return QuerySet(self._datasheet)
    
    def all(self) -> QuerySet:
        """
        获取所有记录的查询集
        
        Returns:
            QuerySet实例
        """
        return self.get_queryset()
    
    def filter(
        self, 
        formula: Optional[str] = None,
        fields: Optional[List[str]] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
        view_id: Optional[str] = None,
        max_records: Optional[int] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        **kwargs
    ) -> QuerySet:
        """
        过滤记录（支持多种过滤条件）
        
        Args:
            formula: 过滤公式
            fields: 返回字段列表
            page_size: 每页记录数
            page_token: 分页标记
            view_id: 视图ID
            max_records: 最大记录数
            sort: 排序设置
            **kwargs: 其他参数
            
        Returns:
            QuerySet实例
        """
        query = self.get_queryset()
        
        if formula:
            query = query.filter(formula)
        if fields:
            query = query.filter(fields=fields)
        if page_size:
            query = query.filter(page_size=page_size)
        if page_token:
            query = query.filter(page_token=page_token)
        if view_id:
            query = query.filter(view_id=view_id)
        if max_records:
            query = query.filter(max_records=max_records)
        if sort:
            query = query.sort(sort)
        
        # 处理其他关键字参数
        for key, value in kwargs.items():
            if value is not None:
                query = query.filter(**{key: value})
                
        return query
    
    def filter_by_formula(self, formula: str) -> QuerySet:
        """
        按公式过滤记录（别名方法）
        
        Args:
            formula: 过滤公式
            
        Returns:
            QuerySet实例
        """
        return self.filter(formula)
    
    def order_by(self, *fields) -> QuerySet:
        """
        排序
        
        Args:
            *fields: 排序字段
            
        Returns:
            QuerySet实例
        """
        return self.get_queryset().order_by(*fields)
    
    def fields(self, *field_names) -> QuerySet:
        """
        指定返回字段
        
        Args:
            *field_names: 字段名列表
            
        Returns:
            QuerySet实例
        """
        return self.get_queryset().fields(*field_names)
    
    def view(self, view_id: str) -> QuerySet:
        """
        指定视图
        
        Args:
            view_id: 视图ID
            
        Returns:
            QuerySet实例
        """
        return self.get_queryset().view(view_id)
    
    async def aget(self, record_id: Optional[str] = None, **kwargs) -> Record:
        """
        获取单条记录（异步）
        
        Args:
            record_id: 记录ID
            **kwargs: 过滤条件
            
        Returns:
            记录实例
        """
        if record_id:
            # 通过记录ID获取
            response = await self._aget_records(record_ids=[record_id])
            records_data = response.get('data', {}).get('records', [])
            if not records_data:
                raise ParameterException(f"Record with ID '{record_id}' not found")
            return Record(records_data[0], self._datasheet)
        else:
            # 通过过滤条件获取
            return await self.get_queryset().aget(**kwargs)
    
    async def acreate(self, records: Union[List[Dict[str, Any]], Dict[str, Any]]) -> List[Record]:
        """
        创建记录（异步）
        
        Args:
            records: 记录数据，可以是单条记录或记录列表
            
        Returns:
            创建的记录列表
        """
        if isinstance(records, dict):
            records = [records]
        
        # 格式化记录数据
        formatted_records = format_records_for_api(records, self._datasheet._field_key)
        
        # 分批创建（每批最多10条）
        created_records = []
        for batch in chunk_list(formatted_records, MAX_RECORDS_PER_PROCESS):
            response = await self._acreate_records(batch)
            batch_records = response.get('data', {}).get('records', [])
            for record_data in batch_records:
                created_records.append(Record(record_data, self._datasheet))
        
        return created_records
    
    async def abulk_create(self, records: List[Dict[str, Any]]) -> List[Record]:
        """
        批量创建记录（异步，别名方法）
        
        Args:
            records: 记录数据列表
            
        Returns:
            创建的记录列表
        """
        return await self.acreate(records)
    
    async def aupdate(self, records: Union[List[Union[Record, Dict[str, Any]]], Union[Record, Dict[str, Any]]]) -> List[Record]:
        """
        更新记录（异步）
        
        Args:
            records: 要更新的记录，可以是Record对象或包含recordId的字典
            
        Returns:
            更新后的记录列表
        """
        if not isinstance(records, list):
            records = [records]
        
        # 转换为API格式
        update_data = []
        for record in records:
            if isinstance(record, Record):
                if not record.record_id:
                    raise ParameterException("Record must have recordId for update")
                update_data.append(record.to_dict())
            elif isinstance(record, dict):
                if 'recordId' not in record:
                    raise ParameterException("Record dict must contain 'recordId' for update")
                update_data.append(record)
            else:
                raise ParameterException("Record must be Record object or dict")
        
        # 分批更新
        updated_records = []
        for batch in chunk_list(update_data, MAX_RECORDS_PER_PROCESS):
            response = await self._aupdate_records(batch)
            batch_records = response.get('data', {}).get('records', [])
            for record_data in batch_records:
                updated_records.append(Record(record_data, self._datasheet))
        
        return updated_records
    
    async def abulk_update(self, records: List[Union[Record, Dict[str, Any]]]) -> List[Record]:
        """
        批量更新记录（异步，别名方法）
        
        Args:
            records: 记录列表
            
        Returns:
            更新后的记录列表
        """
        return await self.aupdate(records)
    
    async def adelete(self, records: Union[Sequence[Union[str, Record]], str, Record]) -> bool:
        """
        删除记录（异步）
        
        Args:
            records: 要删除的记录ID或Record对象
            
        Returns:
            是否删除成功
        """
        if isinstance(records, (str, Record)):
            records = [records]
        
        # 提取记录ID
        record_ids = []
        for record in records:
            if isinstance(record, str):
                record_ids.append(record)
            elif isinstance(record, Record):
                if not record.record_id:
                    raise ParameterException("Record must have recordId for deletion")
                record_ids.append(record.record_id)
            else:
                raise ParameterException("Record must be string ID or Record object")
        
        # 分批删除
        for batch in chunk_list(record_ids, MAX_RECORDS_PER_PROCESS):
            await self._adelete_records(batch)
        
        return True
    
    async def abulk_delete(self, record_ids: List[str]) -> bool:
        """
        批量删除记录（异步，别名方法）
        
        Args:
            record_ids: 记录ID列表
            
        Returns:
            是否删除成功
        """
        return await self.adelete(record_ids)
    
    # 内部API调用方法
    async def _aget_records(
        self,
        view_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
        filterByFormula: Optional[str] = None,
        max_records: Optional[int] = None,
        page_size: Optional[int] = None,
        page_num: Optional[int] = None,
        page_token: Optional[str] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        record_ids: Optional[List[str]] = None,
        field_key: Optional[str] = None,
        cell_format: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """获取记录的内部API调用"""
        endpoint = f"datasheets/{self._datasheet._dst_id}/records"
        
        params = {
            "viewId": view_id,
            "fields": fields,
            "filterByFormula": filterByFormula,
            "maxRecords": max_records,
            "pageSize": page_size,
            "pageToken": page_token,
            "pageNum": page_num,
            "sort": sort,
            "recordIds": record_ids,
            "fieldKey": field_key,
            "cellFormat": cell_format,
            **kwargs
        }
        # 清理掉值为 None 的参数
        params = {k: v for k, v in params.items() if v is not None}
        
        return await self._datasheet._apitable.request_adapter.get(endpoint, params=params)
    
    async def _acreate_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """创建记录的内部API调用"""
        endpoint = f"datasheets/{self._datasheet._dst_id}/records"
        
        data = {
            "records": records,
            "fieldKey": self._datasheet._field_key
        }
        
        return await self._datasheet._apitable.request_adapter.post(endpoint, json_body=data)
    
    async def _aupdate_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """更新记录的内部API调用"""
        endpoint = f"datasheets/{self._datasheet._dst_id}/records"
        
        data = {
            "records": records,
            "fieldKey": self._datasheet._field_key
        }
        
        return await self._datasheet._apitable.request_adapter.patch(endpoint, json_body=data)
    
    async def _adelete_records(self, record_ids: List[str]) -> Dict[str, Any]:
        """删除记录的内部API调用"""
        endpoint = f"datasheets/{self._datasheet._dst_id}/records"
        
        # 参数校验：record_ids 不可为空
        if not record_ids:
            raise ParameterException("record_ids cannot be empty for deletion")
        
        # Vika expects repeated query params: recordIds=recA&recordIds=recB.
        params = {"recordIds": record_ids}
        
        return await self._datasheet._apitable.request_adapter.delete(endpoint, params=params)
    
    def __str__(self) -> str:
        return f"RecordManager({self._datasheet})"
    
    def __repr__(self) -> str:
        return f"RecordManager(datasheet={self._datasheet._dst_id})"


__all__ = ['RecordManager']
