"""
维格表查询集类

兼容原vika.py库的QuerySet类，支持链式调用
"""
import asyncio
import math
import logging
import re
from typing import List, Dict, Any, Optional, Union, AsyncIterator
from .record import Record
from ..const import MAX_RECORDS_PER_REQUEST, MAX_RECORDS_RETURNED_BY_ALL
from ..exceptions import ParameterException, RateLimitException

# 可通过配置/元数据覆写
DEFAULT_CREATED_FIELD_NAME = '创建时间'

# 自适应限流/参数化 sleep
_DEFAULT_PAGE_DELAY_SECONDS = 0.0
_BACKOFF_INITIAL_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 8.0

# 内部工具：字段名校验与安全转义，避免公式注入
_SAFE_FIELD_RE = re.compile(r"^[A-Za-z0-9_ \u4e00-\u9fa5\-\.]+$")


def _validate_field_name(name: str) -> str:
    """校验字段名字符集并用花括号包裹，不合法抛参数异常"""
    if not isinstance(name, str) or not name:
        raise ParameterException("Invalid field name in formula")
    if not _SAFE_FIELD_RE.match(name):
        raise ParameterException("Field name contains illegal characters")
    return f"{{{name}}}"


def _escape_string_value(val: str) -> str:
    """将字符串值用单引号包裹，并对内部单引号做双写转义"""
    # 替换单引号为双写
    escaped = val.replace("'", "''")
    return f"'{escaped}'"


def _build_safe_eq_formula(conditions: Dict[str, Any]) -> str:
    """
    基于等值匹配构造安全公式，仅支持简单 AND 组合：
    {FieldA} = 'value' AND {FieldB} = 123
    """
    parts: List[str] = []
    for field, value in conditions.items():
        lhs = _validate_field_name(field)
        if isinstance(value, str):
            rhs = _escape_string_value(value)
        elif isinstance(value, (int, float)):
            rhs = str(value)
        elif isinstance(value, bool):
            rhs = "TRUE()" if value else "FALSE()"
        else:
            # 不支持的类型，宁可报错
            raise ParameterException(f"Unsupported value type for formula: {type(value).__name__}")
        parts.append(f"{lhs} = {rhs}")
    return " AND ".join(parts)


class QuerySet:
    """
    查询集类，支持链式调用和Django ORM风格的API
    
    兼容原vika.py库的QuerySet接口
    """
    
    def __init__(self, datasheet):
        """
        初始化查询集
        
        Args:
            datasheet: 数据表实例
        """
        self._datasheet = datasheet
        self._view_id = None
        self._fields = None
        self._filter_formula = None
        self._sort: Optional[List[Dict[str, str]]] = None
        self._max_records = None
        self._record_ids = None
        self._page_size = None
        self._page_num = None
        self._page_token = None
        self._field_key = getattr(datasheet, "_field_key", "name")
        self._cell_format = "json"
        self._cached_records = None
        self._is_evaluated = False
    
    def filter(
        self, 
        formula: Optional[str] = None,
        fields: Optional[List[str]] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
        view_id: Optional[str] = None,
        max_records: Optional[int] = None,
        **kwargs
    ) -> 'QuerySet':
        """
        过滤记录（支持多种过滤条件）
        
        Args:
            formula: 过滤公式
            fields: 返回字段列表
            page_size: 每页记录数
            page_token: 分页标记
            view_id: 视图ID
            max_records: 最大记录数
            **kwargs: 其他参数
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        
        if formula:
            new_qs._filter_formula = formula
        if fields:
            new_qs._fields = fields
        if page_size:
            new_qs._page_size = page_size
        if page_token:
            new_qs._page_token = page_token
        if view_id:
            new_qs._view_id = view_id
        if max_records:
            new_qs._max_records = max_records
            
        # 处理其他关键字参数
        for key, value in kwargs.items():
            if value is not None:
                if key == 'filter_by_formula':
                    new_qs._filter_formula = value
                else:
                    setattr(new_qs, f'_{key}', value)
                
        return new_qs
    
    def filter_by_formula(self, formula: str) -> 'QuerySet':
        """
        按公式过滤记录（原库兼容方法）
        
        Args:
            formula: 过滤公式，如：{标题}="标题1"
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        new_qs._filter_formula = formula
        return new_qs
    
    def order_by(self, *fields) -> 'QuerySet':
        """
        排序
        
        Args:
            *fields: 排序字段，支持'-'前缀表示降序
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        sort_list = []
        
        for field in fields:
            if field.startswith('-'):
                sort_list.append({"field": field[1:], "order": "desc"})
            else:
                sort_list.append({"field": field, "order": "asc"})
        
        new_qs._sort = sort_list
        return new_qs
    
    def sort(self, sort_config: List[Dict[str, str]]) -> 'QuerySet':
        """
        排序（原库兼容方法）
        
        Args:
            sort_config: 排序配置列表
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        new_qs._sort = sort_config
        return new_qs
    
    def fields(self, *field_names) -> 'QuerySet':
        """
        指定返回的字段
        
        Args:
            *field_names: 字段名列表
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        new_qs._fields = list(field_names)
        return new_qs
    
    def view(self, view_id: str) -> 'QuerySet':
        """
        指定视图
        
        Args:
            view_id: 视图ID
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        new_qs._view_id = view_id
        return new_qs
    
    def limit(self, max_records: int) -> 'QuerySet':
        """
        限制返回记录数
        
        Args:
            max_records: 最大记录数
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        new_qs._max_records = max_records
        return new_qs
    
    def page_size(self, size: int) -> 'QuerySet':
        """
        设置分页大小
        
        Args:
            size: 分页大小
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        new_qs._page_size = min(size, MAX_RECORDS_PER_REQUEST)
        return new_qs
    
    def page_num(self, page_number: int) -> 'QuerySet':
        """
        设置页码
        
        Args:
            page_number: 页码
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        new_qs._page_num = page_number
        return new_qs

    def filter_by_ids(self, record_ids: List[str]) -> 'QuerySet':
        """
        按记录ID列表过滤记录
        
        Args:
            record_ids: 记录ID列表
            
        Returns:
            新的QuerySet实例
        """
        new_qs = self._clone()
        new_qs._record_ids = record_ids
        return new_qs

    def field_key(self, key: str) -> 'QuerySet':
        """
        设置字段键类型
        
        Args:
            key: 字段键类型 ("name" 或 "id")
            
        Returns:
            新的QuerySet实例
        """
        if key not in ["name", "id"]:
            raise ParameterException("field_key must be 'name' or 'id'")
        
        new_qs = self._clone()
        new_qs._field_key = key
        return new_qs
    
    def cell_format(self, format_type: str) -> 'QuerySet':
        """
        设置单元格格式
        
        Args:
            format_type: 格式类型 ("json" 或 "string")
            
        Returns:
            新的QuerySet实例
        """
        if format_type not in ["json", "string"]:
            raise ParameterException("cell_format must be 'json' or 'string'")
        
        new_qs = self._clone()
        new_qs._cell_format = format_type
        return new_qs
    
    async def aall(self, max_count: Optional[int] = None) -> List[Record]:
        """
        获取所有记录（异步，自动处理分页）
        
        Args:
            max_count: 最大记录数
            
        Returns:
            记录列表
        """
        limits = [limit for limit in (self._max_records, max_count) if limit is not None]
        effective_limit = min(limits) if limits else None
        if effective_limit is not None and effective_limit <= 0:
            return []

        # 首次请求，获取第一页数据和总记录数
        page_size = self._page_size or MAX_RECORDS_PER_REQUEST
        if effective_limit is not None:
            page_size = min(page_size, effective_limit)
        backoff_delay = 0.0  # 自适应限流/参数化 sleep：遇到限流时指数退避，成功后重置
        while True:
            try:
                first_page_response = await self._datasheet.records._aget_records(
                    view_id=self._view_id,
                    fields=self._fields,
                    filterByFormula=self._filter_formula,
                    max_records=effective_limit,
                    page_size=page_size,
                    page_num=1,  # 强制从第一页开始
                    page_token=self._page_token,
                    sort=self._sort,
                    field_key=self._field_key,
                    cell_format=self._cell_format
                )
                break
            except RateLimitException:
                backoff_delay = _BACKOFF_INITIAL_SECONDS if backoff_delay == 0.0 else min(_BACKOFF_MAX_SECONDS, backoff_delay * 2)
                await asyncio.sleep(backoff_delay)
        
        data = first_page_response.get('data', {})
        total = data.get('total', 0)
        records_data = data.get('records', [])
        
        if not records_data:
            return []
            
        all_records = [Record(record_data, self._datasheet) for record_data in records_data]
        if effective_limit is not None:
            all_records = all_records[:effective_limit]
            if len(all_records) >= effective_limit:
                return all_records
        
        total_pages = math.ceil(total / page_size)
        
        if total_pages > 1:
            # 独立请求并发 gather 降低总RTT —— 不适用此处；逐页拉取以保持顺序与内存可控
            for page_num in range(2, int(total_pages) + 1):
                # 自适应限流/参数化 sleep：仅在限流时退避；否则按参数化的极小延迟
                while True:
                    try:
                        next_page_size = page_size
                        if effective_limit is not None:
                            next_page_size = min(next_page_size, effective_limit - len(all_records))
                            if next_page_size <= 0:
                                return all_records
                        response = await self._datasheet.records._aget_records(
                            view_id=self._view_id,
                            fields=self._fields,
                            filterByFormula=self._filter_formula,
                            page_size=next_page_size,
                            page_num=page_num,
                            sort=self._sort,
                            field_key=self._field_key,
                            cell_format=self._cell_format
                        )
                        # 成功后重置退避
                        backoff_delay = 0.0
                        break
                    except RateLimitException:
                        backoff_delay = _BACKOFF_INITIAL_SECONDS if backoff_delay == 0.0 else min(_BACKOFF_MAX_SECONDS, backoff_delay * 2)
                        await asyncio.sleep(backoff_delay)
                
                new_records_data = response.get('data', {}).get('records', [])
                if new_records_data:
                    all_records.extend([Record(record_data, self._datasheet) for record_data in new_records_data])
                    if effective_limit is not None and len(all_records) >= effective_limit:
                        return all_records[:effective_limit]
                
                # 参数化的可调延迟，默认极小（0）
                if _DEFAULT_PAGE_DELAY_SECONDS > 0:
                    await asyncio.sleep(_DEFAULT_PAGE_DELAY_SECONDS)
                
        return all_records
    
    async def afirst(self) -> Optional[Record]:
        """
        获取第一条记录（异步）
        
        Returns:
            第一条记录或None
        """
        records = await self.limit(1)._aevaluate()
        return records[0] if records else None
    
    async def alast(self) -> Optional[Record]:
        """
        获取最后一条记录（异步）
        
        Returns:
            最后一条记录或None
        """
        # 反转排序并获取第一条
        reversed_qs = self._clone()
        if reversed_qs._sort:
            # 反转现有排序
            new_sort = []
            for sort_item in reversed_qs._sort:
                new_order = "desc" if sort_item.get("order") == "asc" else "asc"
                new_sort.append({"field": sort_item["field"], "order": new_order})
            reversed_qs._sort = new_sort
        else:
            # 默认按创建时间降序
            reversed_qs._sort = [{"field": DEFAULT_CREATED_FIELD_NAME, "order": "desc"}]
        
        records = await reversed_qs.limit(1)._aevaluate()
        return records[0] if records else None
    
    async def acount(self) -> int:
        """
        获取记录总数（异步）
        
        Returns:
            记录总数
        """
        # 获取第一页数据来获取总数信息
        # 使用空字段列表来减少数据传输，只获取total信息
        response = await self._datasheet.records._aget_records(
            view_id=self._view_id,
            fields=self._fields[:1] if self._fields else None,
            filterByFormula=self._filter_formula,
            max_records=1,
            sort=self._sort,
            field_key=self._field_key,
            cell_format=self._cell_format
        )
        
        # 如果API返回总数信息，使用它；否则需要获取所有记录来计算
        data = response.get('data', {})
        if 'total' in data:
            return data['total']
        else:
            # 需要获取所有记录来计算总数
            all_records = await self.aall()
            return len(all_records)
    
    async def aexists(self) -> bool:
        """
        检查是否存在匹配的记录（异步）
        
        Returns:
            是否存在记录
        """
        return await self.afirst() is not None
    
    async def aget(self, **kwargs) -> Record:
        """
        获取单条记录（异步，如果有多条或没有记录会抛出异常）
        
        Args:
            **kwargs: 过滤条件
            
        Returns:
            单条记录
            
        Raises:
            ParameterException: 没有找到记录或找到多条记录
        """
        if kwargs:
            # 使用安全构造器构建过滤公式，避免公式注入
            formula = _build_safe_eq_formula(kwargs)
            queryset = self.filter(formula)
        else:
            queryset = self
        
        records = await queryset.limit(2)._aevaluate()
        
        if not records:
            raise ParameterException("Record matching query does not exist")
        elif len(records) > 1:
            raise ParameterException("Query returned more than one record")
        
        return records[0]
    
    async def _aevaluate(self) -> List[Record]:
        """执行查询并返回记录列表（异步）"""
        if self._is_evaluated and self._cached_records is not None:
            return self._cached_records
        
        response = await self._datasheet.records._aget_records(
            view_id=self._view_id,
            fields=self._fields,
            filterByFormula=self._filter_formula,
            max_records=self._max_records,
            page_size=self._page_size,
            page_num=self._page_num,
            page_token=self._page_token,
            sort=self._sort,
            record_ids=self._record_ids,
            field_key=self._field_key,
            cell_format=self._cell_format
        )
        
        records_data = response.get('data', {}).get('records', [])
        self._cached_records = [Record(record_data, self._datasheet) for record_data in records_data]
        self._is_evaluated = True
        
        return self._cached_records
    
    def _clone(self) -> 'QuerySet':
        """克隆QuerySet"""
        new_qs = QuerySet(self._datasheet)
        new_qs._view_id = self._view_id
        new_qs._fields = self._fields
        new_qs._filter_formula = self._filter_formula
        new_qs._sort = self._sort
        new_qs._max_records = self._max_records
        new_qs._record_ids = self._record_ids
        new_qs._page_size = self._page_size
        new_qs._page_num = self._page_num
        new_qs._page_token = self._page_token
        new_qs._field_key = self._field_key
        new_qs._cell_format = self._cell_format
        # 复制评估/缓存状态保持一致
        new_qs._is_evaluated = self._is_evaluated
        new_qs._cached_records = list(self._cached_records) if self._cached_records is not None else None
        return new_qs
    
    # 支持异步迭代器接口
    async def __aiter__(self) -> AsyncIterator[Record]:
        """异步迭代器支持"""
        records = await self._aevaluate()
        for record in records:
            yield record
    
    async def __alen__(self) -> int:
        """支持异步len()函数"""
        records = await self._aevaluate()
        return len(records)
    
    async def __agetitem__(self, key) -> Union[Record, List[Record]]:
        """支持异步索引和切片访问"""
        records = await self._aevaluate()
        return records[key]
    
    async def __abool__(self) -> bool:
        """支持异步bool()判断"""
        return await self.aexists()
    
    def __repr__(self) -> str:
        """字符串表示"""
        return f"<QuerySet: {self._datasheet}>"


__all__ = ['QuerySet']
