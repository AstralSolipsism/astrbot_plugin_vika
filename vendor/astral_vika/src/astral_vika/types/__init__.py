"""
维格表类型定义模块

兼容原vika.py库的类型系统
"""
# 通配导出→显式导出，便于维护
from .response import (
    APIResponse,
    FieldData,
    DatasheetResponse,
    RecordsResponse,
    FieldsResponse,
    ViewsResponse,
    SpaceResponse,
    NodeResponse,
    AttachmentResponse,
)
# 通配导出→显式导出，便于维护
from .unit_model import (
    UnitRoleCreateRo,
    UnitRoleUpdateRo,
    UnitMemberCreateRo,
    UnitTeamCreateRo,
    UnitModel,
    MemberModel,
    RoleModel,
    TeamModel,
)


__all__ = [
    # Response types
    'APIResponse',
    'FieldData',
    'DatasheetResponse',
    'RecordsResponse',
    'FieldsResponse',
    'ViewsResponse',
    'SpaceResponse',
    'NodeResponse',
    'AttachmentResponse',
    
    # Unit types
    'UnitRoleCreateRo',
    'UnitRoleUpdateRo',
    'UnitMemberCreateRo',
    'UnitTeamCreateRo',
    'UnitModel',
    'MemberModel',
    'RoleModel',
    'TeamModel'
]
