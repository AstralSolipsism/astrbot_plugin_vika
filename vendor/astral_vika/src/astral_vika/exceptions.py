"""
维格表API异常类定义

兼容原vika.py库的异常结构
"""
from typing import Optional, Dict, Any


class VikaException(Exception):
    """维格表API基础异常类"""
    
    def __init__(self, message: str, code: Optional[int] = None, response: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.response = response

    def __str__(self):
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message


class ApiException(VikaException):
    """API异常（与原库兼容的别名）"""
    pass


class AuthException(VikaException):
    """认证异常。对应官方错误 "INVALID_API_KEY"(201) 或 "API_KEY_EMPTY"(202)"""
    pass


class InvalidRequestException(VikaException):
    """无效请求异常。通常由不合法的参数或请求体导致。"""
    pass


class ParameterException(InvalidRequestException):
    """参数异常。对应官方错误 "INVALID_PARAMETER"(901) 或 "INVALID_REQUEST_BODY"(900)"""
    pass


class InvalidFieldException(ParameterException):
    """无效字段异常。对应官方错误 "FIELD_NOT_EXIST"(205)"""
    pass


class InvalidRecordException(ParameterException):
    """无效记录异常。"""
    pass


class InvalidViewException(ParameterException):
    """无效视图异常。对应官方错误 "INVALID_VIEW_ID"(304)"""
    pass


class InvalidFormulaException(ParameterException):
    """公式错误异常。对应官方错误 "INVALID_FORMULA"(902)"""
    pass


class PermissionException(VikaException):
    """权限异常。对应官方错误 "NODE_OPERATION_DENIED"(401) 或 "READ_ONLY_NODE"(403)"""
    pass


class RateLimitException(VikaException):
    """频率限制异常。"""
    pass


class ServerException(VikaException):
    """服务器异常。"""
    pass


class AttachmentException(VikaException):
    """附件异常。对应官方错误 "UPLOAD_FAILED"(426) 或 "ATTACHMENT_PARSE_ERROR"(428)"""
    pass


class NotFoundException(VikaException):
    """资源未找到异常。"""
    pass


class DatasheetNotFoundException(NotFoundException):
    """数据表未找到异常。对应官方错误 "INVALID_DATASHEET_ID"(301)"""
    pass


class FieldNotFoundException(NotFoundException):
    """字段未找到异常。对应官方错误 "INVALID_FIELD_ID"(302)"""
    pass


class RecordNotFoundException(NotFoundException):
    """记录未找到异常。对应官方错误 "INVALID_RECORD_ID"(303)"""
    pass


# 常见 vika.py 使用习惯兼容别名
class APIException(ApiException):
    """API异常别名"""
    pass


# 映射：API业务错误码 -> 异常类
# 更多错误码请参考维格表API文档
CODE_TO_EXCEPTION_MAP = {
    # 认证/权限
    201: AuthException,             # 无效的API Key (INVALID_API_KEY)
    202: AuthException,             # API Key不能为空 (API_KEY_EMPTY)
    401: PermissionException,       # 无权操作此节点 (NODE_OPERATION_DENIED)
    402: PermissionException,       # 无权操作此空间站 (SPACE_OPERATION_DENIED)
    403: PermissionException,       # 只读节点不可操作 (READ_ONLY_NODE)
    
    # 资源未找到
    301: DatasheetNotFoundException,# 无效的数据表ID (INVALID_DATASHEET_ID)
    302: FieldNotFoundException,    # 无效的字段ID (INVALID_FIELD_ID)
    303: RecordNotFoundException,   # 无效的记录ID (INVALID_RECORD_ID)
    304: InvalidViewException,      # 无效的视图ID (INVALID_VIEW_ID)
    
    # 参数错误
    205: InvalidFieldException,     # 字段不存在 (FIELD_NOT_EXIST)
    900: ParameterException,        # 无效的请求体 (INVALID_REQUEST_BODY)
    901: ParameterException,        # 无效的URL参数 (INVALID_PARAMETER)
    902: InvalidFormulaException,   # 无效的公式 (INVALID_FORMULA)
    903: ParameterException,        # 无效的排序参数 (INVALID_SORT_FIELD)
    904: ParameterException,        # 无效的字段名 (INVALID_FIELD_NAME)
    
    # 附件
    426: AttachmentException,       # 附件上传失败 (UPLOAD_FAILED)
    428: AttachmentException,       # 附件解析失败 (ATTACHMENT_PARSE_ERROR)
}


def create_exception_from_response(response_data: Dict[str, Any], status_code: int) -> VikaException:
    """根据响应数据创建相应的异常"""
    message = response_data.get('message', f'HTTP {status_code} Error')
    code = response_data.get('code', status_code)

    # 优先根据业务错误码匹配
    if code in CODE_TO_EXCEPTION_MAP:
        exception_class = CODE_TO_EXCEPTION_MAP[code]
        return exception_class(message, code, response_data)

    # 其次根据HTTP状态码匹配
    if status_code == 401:
        return AuthException(message, code, response_data)
    if status_code == 403:
        return PermissionException(message, code, response_data)
    if status_code == 404:
        return NotFoundException(message, code, response_data)
    if status_code == 400:
        return InvalidRequestException(message, code, response_data)
    if status_code == 429:
        return RateLimitException(message, code, response_data)
    if status_code >= 500:
        return ServerException(message, code, response_data)

    # 默认异常
    return ApiException(message, code, response_data)


__all__ = [
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
    'create_exception_from_response'
]
