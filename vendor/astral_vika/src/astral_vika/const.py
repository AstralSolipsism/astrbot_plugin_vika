"""
维格表API常量定义

兼容原vika.py库的常量定义
"""

# API版本和端点
DEFAULT_API_BASE = "https://vika.cn"
API_VERSION = "v1"
FUSION_API_PREFIX = f"/fusion/{API_VERSION}"
API_VERSION_V2 = "v2"
NODES_API_V2_PREFIX = f"/fusion/{API_VERSION_V2}"  # 集中常量：v2 API 前缀

# 请求限制
MAX_RECORDS_PER_REQUEST = 1000
MAX_RECORDS_PER_PROCESS = 10
MAX_RECORDS_RETURNED_BY_ALL = 5000
MAX_RECORDS_PER_TABLE = 50000

# 字段类型映射（与原库兼容）
FIELD_TYPE_MAP = {
    "SingleText": "单行文本",
    "Text": "多行文本", 
    "SingleSelect": "单选",
    "MultiSelect": "多选",
    "Number": "数字",
    "Currency": "货币",
    "Percent": "百分比",
    "DateTime": "日期",
    "Attachment": "附件",
    "Member": "成员",
    "Checkbox": "勾选",
    "Rating": "评分",
    "URL": "网址",
    "Phone": "电话",
    "Email": "邮箱",
    "AutoNumber": "自增数字",
    "CreatedTime": "创建时间",
    "LastModifiedTime": "修改时间",
    "CreatedBy": "创建人",
    "LastModifiedBy": "修改人",
    "Formula": "智能公式",
    "Lookup": "神奇关联",
    "Reference": "神奇引用",
    "OneWayLink": "单向关联",
    "TwoWayLink": "双向关联",
    "WorkDoc": "文档",
    "Button": "按钮"
}

# 数据类型映射
PYTHON_TYPE_MAP = {
    "SingleText": str,
    "Text": str,
    "SingleSelect": str,
    "MultiSelect": list,
    "URL": str,
    "Phone": str,
    "Email": str,
    "Number": (int, float),
    "Currency": (int, float),
    "Percent": (int, float),
    "AutoNumber": int,
    "DateTime": int,
    "CreatedTime": int,
    "LastModifiedTime": int,
    "Attachment": list,
    "Member": list,
    "Checkbox": bool,
    "Rating": int,
    "CreatedBy": dict,
    "LastModifiedBy": dict,
    "Formula": (str, bool, int, float),
    "Lookup": list,
    "Reference": list
}

# HTTP状态码
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429
HTTP_INTERNAL_SERVER_ERROR = 500

# 错误码映射
ERROR_CODE_MAP = {
    301: "找不到指定维格表",
    400: "参数异常/数据验证异常", 
    401: "身份认证失败",
    403: "禁止访问/超出限制",
    404: "接口不存在",
    426: "附件上传失败",
    428: "附件个数超出限制",
    429: "操作太频繁",
    500: "服务器内部错误",
    602: "无节点权限操作"
}

# 字段键类型
FIELD_KEY_NAME = "name"
FIELD_KEY_ID = "id"

# 单元格格式
CELL_FORMAT_JSON = "json"
CELL_FORMAT_STRING = "string"

# 排序方向
ORDER_ASC = "asc"
ORDER_DESC = "desc"

# 视图类型
VIEW_TYPE_GRID = "Grid"
VIEW_TYPE_GALLERY = "Gallery"
VIEW_TYPE_KANBAN = "Kanban"
VIEW_TYPE_FORM = "Form"
VIEW_TYPE_CALENDAR = "Calendar"
VIEW_TYPE_GANTT = "Gantt"

# 单元类型
UNIT_TYPE_MEMBER = "Member"
UNIT_TYPE_TEAM = "Team"  
UNIT_TYPE_ROLE = "Role"

# 缓存配置
CACHE_TTL = 300  # 5分钟缓存
