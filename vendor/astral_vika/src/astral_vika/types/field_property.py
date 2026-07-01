# -*- coding: utf-8 -*-
# 清理未使用导入
from typing import List, Optional, Union

# 清理未使用导入
from pydantic import BaseModel
from enum import Enum


# Basic Property Models
class EmptyProperty(BaseModel):
    """For fields without properties, such as Text, Attachment, etc."""
    pass


class DefaultValueProperty(BaseModel):
    defaultValue: Optional[str] = None


# Select Properties
class Color(BaseModel):
    name: str
    value: str


class SelectOption(BaseModel):
    id: str
    name: str
    color: Color


class SelectProperty(BaseModel):
    options: List[SelectOption]


# Number Properties
class NumberProperty(BaseModel):
    defaultValue: Optional[str] = None
    precision: int
    commaStyle: Optional[str] = None
    symbol: Optional[str] = None


# 增加枚举约束：货币符号对齐
class SymbolAlignEnum(str, Enum):
    Default = "Default"
    Left = "Left"
    Right = "Right"

class CurrencyProperty(BaseModel):
    defaultValue: Optional[str] = None
    precision: int
    symbol: str
    symbolAlign: Optional[Union[SymbolAlignEnum, str]] = SymbolAlignEnum.Default  # 增加枚举约束（保守接受字符串）


class PercentProperty(BaseModel):
    defaultValue: Optional[str] = None
    precision: int


# DateTime Properties
class DateTimeProperty(BaseModel):
    dateFormat: str
    includeTime: bool
    timeFormat: Optional[str] = None
    autoFill: bool
    timeZone: Optional[str] = None
    includeTimeZone: Optional[bool] = False


# Member/User Properties
class MemberProperty(BaseModel):
    isMulti: bool
    shouldSendMsg: bool


class UserOption(BaseModel):
    id: str
    name: str
    avatar: str


class UserProperty(BaseModel):
    options: List[UserOption]


# Other Simple Properties
class CheckboxProperty(BaseModel):
    icon: str


class RatingProperty(BaseModel):
    icon: str
    max: int


# Link Properties
class LinkProperty(BaseModel):
    foreignDatasheetId: str
    limitToViewId: Optional[str] = None
    limitSingleRecord: Optional[bool] = False


class TwoWayLinkProperty(LinkProperty):
    brotherFieldId: str


# Formula Property
# 增加枚举约束：公式格式类型（保守）
class FormulaFormatType(str, Enum):
    DateTime = "DateTime"
    Number = "Number"
    Currency = "Currency"
    Percent = "Percent"
    Text = "Text"

class FormulaFormat(BaseModel):
    type: Optional[Union[FormulaFormatType, str]] = None  # 增加枚举约束（未知值回退为字符串）
    # Specific format properties depend on the type
    dateFormat: Optional[str] = None
    timeFormat: Optional[str] = None
    includeTime: Optional[bool] = None
    precision: Optional[int] = None
    symbol: Optional[str] = None


class FormulaProperty(BaseModel):
    expression: str
    valueType: str
    hasError: Optional[bool] = False
    format: Optional[FormulaFormat] = None


# Button Property
class ButtonStyle(BaseModel):
    color: Optional[str] = None
    fill: Optional[bool] = None
    bold: Optional[bool] = None


class ButtonAction(BaseModel):
    type: str
    # Action properties depend on the type
    url: Optional[str] = None
    openInNewTab: Optional[bool] = None
    datasheetId: Optional[str] = None
    viewId: Optional[str] = None
    fieldId: Optional[str] = None
    recordId: Optional[str] = None
    automationId: Optional[str] = None


class ButtonProperty(BaseModel):
    text: str
    style: Optional[ButtonStyle] = None
    action: Optional[ButtonAction] = None