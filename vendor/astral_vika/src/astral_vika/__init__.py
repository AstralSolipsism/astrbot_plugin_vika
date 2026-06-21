"""
Astral Vika 异步优先 Vika Fusion API SDK。

主包提供空间站、数据表、记录、字段、视图、附件、节点和组织单元的
异步 API 封装，并保留常见 vika.py 使用习惯的兼容入口。

作者: AstralSolipsism
版本: 1.1.3
兼容: Python 3.8+
"""

# 主入口类
from .apitable import Vika, Apitable

# 核心模块
from .datasheet import (
    Datasheet, DatasheetManager, Record, RecordManager, 
    Field, FieldManager, View, ViewManager, QuerySet,
    Attachment, AttachmentManager
)
from .space import Space, SpaceManager
from .node import NodeManager
from .unit import Member, Role, Team

# 通配导入→显式导入，保持 API 稳定
from .types.response import (
    APIResponse,
    RecordData,
    FieldData,
    ViewData,
    SpaceData,
    AttachmentData,
    NodeData,
    RecordsResponse,
    FieldsResponse,
    ViewsResponse,
    DatasheetResponse,
    SpaceResponse,
    NodeResponse,
    AttachmentResponse,
    PostDatasheetMetaResponse,
    PostDatasheetMeta,
)
# 通配导入→显式导入，保持 API 稳定
from .types.unit_model import (
    UnitRoleCreateRo,
    UnitRoleUpdateRo,
    UnitMemberCreateRo,
    UnitTeamCreateRo,
    UnitModel,
    MemberModel,
    RoleModel,
    TeamModel,
)

# 通配导入→显式导入，保持 API 稳定
from .exceptions import (
    VikaException,
    ApiException,
    APIException,
    AuthException,
    ParameterException,
    PermissionException,
    RateLimitException,
    ServerException,
    AttachmentException,
    DatasheetNotFoundException,
    FieldNotFoundException,
    RecordNotFoundException,
    create_exception_from_response,
)

# 通配导入→显式导入，保持 API 稳定
from .const import (
    DEFAULT_API_BASE,
    MAX_RECORDS_PER_REQUEST,
    MAX_RECORDS_PER_PROCESS,
    FIELD_TYPE_MAP,
    PYTHON_TYPE_MAP,
)

# 工具函数
from .utils import get_dst_id, get_space_id

# 版本信息
__version__ = "1.1.3"
__author__ = "AstralSolipsism"

# 主要导出（与原库兼容）
__all__ = [
    # 主入口类（兼容原库）
    'Vika',
    'Apitable',
    
    # 核心类
    'Datasheet',
    'DatasheetManager',
    'Record', 
    'RecordManager',
    'Field',
    'FieldManager',
    'View',
    'ViewManager',
    'QuerySet',
    'Attachment',
    'AttachmentManager',
    'Space',
    'SpaceManager',
    'NodeManager',
    'Member',
    'Role',
    'Team',
    
    # 类型定义（从types导入）
    'APIResponse',
    'RecordData',
    'FieldData',
    'ViewData',
    'SpaceData',
    'AttachmentData',
    'NodeData',
    'RecordsResponse',
    'FieldsResponse',
    'ViewsResponse',
    'DatasheetResponse',
    'SpaceResponse',
    'NodeResponse',
    'AttachmentResponse',
    'PostDatasheetMetaResponse',
    'PostDatasheetMeta',
    'UnitRoleCreateRo',
    'UnitRoleUpdateRo',
    'UnitMemberCreateRo',
    'UnitTeamCreateRo',
    'UnitModel',
    'MemberModel',
    'RoleModel',
    'TeamModel',
    
    # 异常类（从exceptions导入）
    'VikaException',
    'ApiException',
    'APIException',
    'AuthException',
    'ParameterException',
    'PermissionException',
    'RateLimitException',
    'ServerException',
    'AttachmentException',
    'DatasheetNotFoundException',
    'FieldNotFoundException',
    'RecordNotFoundException',
    
    # 工具函数
    'get_dst_id',
    'get_space_id',
    
    # 常量
    'DEFAULT_API_BASE',
    'MAX_RECORDS_PER_REQUEST',
    'MAX_RECORDS_PER_PROCESS',
    'FIELD_TYPE_MAP',
    'PYTHON_TYPE_MAP'
]
