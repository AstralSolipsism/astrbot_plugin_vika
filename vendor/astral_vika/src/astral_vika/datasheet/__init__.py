"""
维格表数据表模块

兼容原vika.py库的datasheet模块
"""
from .datasheet import Datasheet
from .datasheet_manager import DatasheetManager
from .record import Record, RecordBuilder
from .record_manager import RecordManager
from .field_manager import Field, FieldManager
from .view_manager import View, ViewManager
from .query_set import QuerySet
from .attachment_manager import Attachment, AttachmentManager


__all__ = [
    'Datasheet',
    'DatasheetManager',
    'Record',
    'RecordBuilder', 
    'RecordManager',
    'Field',
    'FieldManager',
    'View',
    'ViewManager',
    'QuerySet',
    'Attachment',
    'AttachmentManager'
]
