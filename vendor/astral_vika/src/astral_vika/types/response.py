"""
维格表API响应类型定义

兼容原vika.py库的响应类型
"""
from typing import Annotated, Any, Dict, List, Optional, Union, Mapping, Literal
from enum import Enum
from pydantic import BaseModel
from pydantic import Field as PydanticField
from .field_property import (
    ButtonProperty, CheckboxProperty, CurrencyProperty, DateTimeProperty,
    DefaultValueProperty, EmptyProperty, FormulaProperty, LinkProperty,
    MemberProperty, NumberProperty, PercentProperty, RatingProperty,
    SelectProperty, TwoWayLinkProperty, UserProperty
)


class FieldTypeEnum(str, Enum):
    """字段类型枚举，约束各字段type取值"""
    SingleText = "SingleText"
    Text = "Text"
    SingleSelect = "SingleSelect"
    MultiSelect = "MultiSelect"
    Number = "Number"
    Currency = "Currency"
    Percent = "Percent"
    DateTime = "DateTime"
    CreatedTime = "CreatedTime"
    LastModifiedTime = "LastModifiedTime"
    Attachment = "Attachment"
    Member = "Member"
    Checkbox = "Checkbox"
    Rating = "Rating"
    URL = "URL"
    Phone = "Phone"
    Email = "Email"
    WorkDoc = "WorkDoc"
    OneWayLink = "OneWayLink"
    TwoWayLink = "TwoWayLink"
    Formula = "Formula"
    AutoNumber = "AutoNumber"
    CreatedBy = "CreatedBy"
    LastModifiedBy = "LastModifiedBy"
    Button = "Button"
# 增加枚举约束：统一字段类型枚举


class APIResponse(BaseModel):
    """API响应基类"""
    success: bool
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None  # 收敛响应模型：保持与原有序列化一致


class RecordData(BaseModel):
    """记录数据模型"""
    recordId: Optional[str] = None
    fields: Mapping[str, Any]  # 增加约束：使用Mapping限定键为字符串
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class BaseField(BaseModel):
    """字段基础模型"""
    id: str
    name: str
    desc: Optional[str] = None
    editable: Optional[bool] = None
    isPrimary: Optional[bool] = None


# Text Fields
class SingleTextField(BaseField):
    type: Literal[FieldTypeEnum.SingleText]  # 增加枚举约束
    property: DefaultValueProperty


class TextField(BaseField):
    type: Literal[FieldTypeEnum.Text]  # 增加枚举约束
    property: Optional[EmptyProperty] = None


# Select Fields
class SingleSelectField(BaseField):
    type: Literal[FieldTypeEnum.SingleSelect]  # 增加枚举约束
    property: SelectProperty


class MultiSelectField(BaseField):
    type: Literal[FieldTypeEnum.MultiSelect]  # 增加枚举约束
    property: SelectProperty


# Number Fields
class NumberField(BaseField):
    type: Literal[FieldTypeEnum.Number]  # 增加枚举约束
    property: NumberProperty


class CurrencyField(BaseField):
    type: Literal[FieldTypeEnum.Currency]  # 增加枚举约束
    property: CurrencyProperty


class PercentField(BaseField):
    type: Literal[FieldTypeEnum.Percent]  # 增加枚举约束
    property: PercentProperty


# DateTime Fields
class DateTimeField(BaseField):
    type: Literal[FieldTypeEnum.DateTime]  # 增加枚举约束
    property: DateTimeProperty


class CreatedTimeField(BaseField):
    type: Literal[FieldTypeEnum.CreatedTime]  # 增加枚举约束
    property: DateTimeProperty


class LastModifiedTimeField(BaseField):
    type: Literal[FieldTypeEnum.LastModifiedTime]  # 增加枚举约束
    property: DateTimeProperty


# Other Fields
class AttachmentField(BaseField):
    type: Literal[FieldTypeEnum.Attachment]  # 增加枚举约束
    property: Optional[EmptyProperty] = None


class MemberField(BaseField):
    type: Literal[FieldTypeEnum.Member]  # 增加枚举约束
    property: MemberProperty


class CheckboxField(BaseField):
    type: Literal[FieldTypeEnum.Checkbox]  # 增加枚举约束
    property: CheckboxProperty


class RatingField(BaseField):
    type: Literal[FieldTypeEnum.Rating]  # 增加枚举约束
    property: RatingProperty


class URLField(BaseField):
    type: Literal[FieldTypeEnum.URL]  # 增加枚举约束
    property: Optional[EmptyProperty] = None


class PhoneField(BaseField):
    type: Literal[FieldTypeEnum.Phone]  # 增加枚举约束
    property: Optional[EmptyProperty] = None


class EmailField(BaseField):
    type: Literal[FieldTypeEnum.Email]  # 增加枚举约束
    property: Optional[EmptyProperty] = None


class WorkDocField(BaseField):
    type: Literal[FieldTypeEnum.WorkDoc]  # 增加枚举约束
    property: Optional[EmptyProperty] = None


# Link Fields
class OneWayLinkField(BaseField):
    type: Literal[FieldTypeEnum.OneWayLink]  # 增加枚举约束
    property: LinkProperty


class TwoWayLinkField(BaseField):
    type: Literal[FieldTypeEnum.TwoWayLink]  # 增加枚举约束
    property: TwoWayLinkProperty


# Formula/Auto Fields
class FormulaField(BaseField):
    type: Literal[FieldTypeEnum.Formula]  # 增加枚举约束
    property: FormulaProperty


class AutoNumberField(BaseField):
    type: Literal[FieldTypeEnum.AutoNumber]  # 增加枚举约束
    property: Optional[EmptyProperty] = None


# User Fields
class CreatedByField(BaseField):
    type: Literal[FieldTypeEnum.CreatedBy]  # 增加枚举约束
    property: UserProperty


class LastModifiedByField(BaseField):
    type: Literal[FieldTypeEnum.LastModifiedBy]  # 增加枚举约束
    property: UserProperty


# Button Field
class ButtonField(BaseField):
    type: Literal[FieldTypeEnum.Button]  # 增加枚举约束
    property: ButtonProperty


Field = Annotated[
    Union[
        SingleTextField,
        TextField,
        SingleSelectField,
        MultiSelectField,
        NumberField,
        CurrencyField,
        PercentField,
        DateTimeField,
        CreatedTimeField,
        LastModifiedTimeField,
        AttachmentField,
        MemberField,
        CheckboxField,
        RatingField,
        URLField,
        PhoneField,
        EmailField,
        WorkDocField,
        OneWayLinkField,
        TwoWayLinkField,
        FormulaField,
        AutoNumberField,
        CreatedByField,
        LastModifiedByField,
        ButtonField,
    ],
    PydanticField(discriminator="type"),
]

# Public compatibility alias used by astral_vika.__all__ and older callers.
FieldData = Field


class ViewData(BaseModel):
    """视图数据模型"""
    id: str
    name: str
    type: str
    property: Optional[Dict[str, Any]] = None


class AttachmentData(BaseModel):
    """附件数据模型"""
    token: str
    name: str
    size: int
    mimeType: str
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


class UrlData(BaseModel):
    """URL数据模型"""
    title: str
    text: str
    favicon: str


class WorkDocData(BaseModel):
    """维格文档数据模型"""
    document_id: str = PydanticField(..., alias="documentId")
    title: str


class NodeData(BaseModel):
    """节点数据模型"""
    id: str
    name: str
    type: str
    icon: Optional[str] = None
    isFav: Optional[bool] = None
    permission: Optional[int] = None
    children: Optional[List['NodeData']] = None
    parentId: Optional[str] = None


class SpaceData(BaseModel):
    """空间数据模型"""
    id: str
    name: str
    description: Optional[str] = None
    logo: Optional[str] = None


class RecordsResponseData(BaseModel):
    """记录响应数据模型（保守增强）"""
    records: List[RecordData]
    pageToken: Optional[str] = None
    total: Optional[int] = None  # 一些接口可能返回总数
# 收敛响应模型：用于替代 Dict[str, Any]


class RecordsResponse(APIResponse):
    """记录响应模型"""
    data: Optional[RecordsResponseData] = None  # 收敛响应模型：默认None以兼容父类默认


class FieldsResponseData(BaseModel):
    fields: List[Field]


class FieldsResponse(APIResponse):
    """字段响应模型"""
    data: Optional[FieldsResponseData] = None  # 收敛响应模型：默认None以兼容父类默认


class CreateFieldResponseData(BaseModel):
    """创建字段响应数据模型"""
    id: str
    name: str


class CreateFieldResponse(APIResponse):
    """创建字段响应模型"""
    data: Optional[CreateFieldResponseData] = None  # 收敛响应模型：默认None以兼容父类默认


class ViewsData(BaseModel):
    """视图列表数据模型"""
    views: List[ViewData]


class ViewsResponse(APIResponse):
    """视图响应模型"""
    data: Optional[ViewsData] = None  # 收敛响应模型：默认None以兼容父类默认


class DatasheetInfo(BaseModel):
    """数据表信息（保守字段定义）"""
    id: Optional[str] = None
    name: Optional[str] = None
# 收敛响应模型：数据表信息尽量不破坏兼容


class DatasheetResponse(APIResponse):
    """数据表响应模型"""
    data: Optional[DatasheetInfo] = None  # 收敛响应模型：默认None以兼容父类默认


class SpacesData(BaseModel):
    """空间列表数据模型"""
    spaces: List[SpaceData]
# 收敛响应模型：统一spaces列表结构


class SpaceResponse(APIResponse):
    """空间响应模型"""
    data: Optional[SpacesData] = None  # 收敛响应模型：默认None以兼容父类默认


class NodesData(BaseModel):
    """节点列表数据模型"""
    nodes: List[NodeData]


class NodeResponse(APIResponse):
    """节点响应模型"""
    data: Optional[NodesData] = None  # 收敛响应模型：默认None以兼容父类默认


class AttachmentResponseData(BaseModel):
    """附件响应数据（保守字段定义）"""
    attachments: Optional[List[AttachmentData]] = None
# 收敛响应模型：附件统一置于attachments列表下


class AttachmentResponse(APIResponse):
    """附件响应模型"""
    data: Optional[AttachmentResponseData] = None  # 收敛响应模型：默认None以兼容父类默认


class PostDatasheetMetaData(BaseModel):
    """创建数据表元数据（保守字段定义）"""
    datasheetId: Optional[str] = None
    defaultViewId: Optional[str] = None
# 收敛响应模型：元数据最小必要字段可选化


class PostDatasheetMetaResponse(APIResponse):
    """创建数据表元数据响应（与原库兼容）"""
    data: Optional[PostDatasheetMetaData] = None  # 收敛响应模型：默认None以兼容父类默认


class PaginationInfo(BaseModel):
    """分页信息"""
    pageToken: Optional[str] = None
    total: Optional[int] = None


class QueryResult(BaseModel):
    """查询结果模型"""
    records: List[RecordData]
    pagination: Optional[PaginationInfo] = None


# 常见 vika.py 使用习惯兼容别名
PostDatasheetMeta = PostDatasheetMetaResponse


__all__ = [
    'APIResponse',
    'RecordData',
    'FieldData',
    'Field',
    'ViewData',
    'AttachmentData',
    'UrlData',
    'WorkDocData',
    'NodeData',
    'SpaceData',
    'RecordsResponse',
    'FieldsResponse',
    'ViewsResponse',
    'DatasheetResponse',
    'SpaceResponse',
    'NodeResponse',
    'AttachmentResponse',
    'PostDatasheetMetaResponse',
    'PostDatasheetMeta',
    'PaginationInfo',
    'QueryResult'
]
