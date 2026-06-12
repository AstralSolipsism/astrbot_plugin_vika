from typing import Any, Dict
from datetime import datetime

from ..mcp.registry import ToolRegistry
from ..mcp.types import ToolSpec


def time_now(args: Dict[str, Any]) -> str:
    """返回当前时间的格式化字符串。可选参数：
    - timezone_str: IANA 时区名称（例如 "Asia/Shanghai"）。若不可用则回退为系统本地时间。
    - format_str: strftime 格式串，默认 "%Y-%m-%d %H:%M:%S%z"
    """
    tz_name = (args or {}).get("timezone_str")
    fmt = (args or {}).get("format_str") or "%Y-%m-%d %H:%M:%S%z"

    dt: datetime
    if tz_name:
        try:
            # Python 3.9+ 提供 zoneinfo；若不可用或时区名无效则回退本地时间
            from zoneinfo import ZoneInfo  # type: ignore
            dt = datetime.now(ZoneInfo(tz_name))
        except Exception:
            dt = datetime.now()
    else:
        dt = datetime.now()

    try:
        return dt.strftime(fmt)
    except Exception:
        # 格式串非法时，回退默认格式
        return dt.strftime("%Y-%m-%d %H:%M:%S%z")


def register(registry: ToolRegistry) -> int:
    """注册内置零依赖工具集，当前仅包含 time.now"""
    spec = ToolSpec(
        name="time.now",
        description="获取当前时间并按给定格式输出。用于需要日志/时间戳或人类可读时间时。返回字符串（与 output_schema 一致），默认使用系统时区，可指定 IANA 时区。",
        input_schema={
            "type": "object",
            "properties": {
                "timezone_str": {
                    "type": "string",
                    "description": "IANA 时区名称（如 'Asia/Shanghai'）；不可用或无效时回退为系统本地时间。",
                },
                "format_str": {
                    "type": "string",
                    "description": "strftime 格式串，默认 '%Y-%m-%d %H:%M:%S%z'；非法格式将回退为默认格式。",
                },
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "string",
            "description": "格式化后的时间字符串（例如 '2025-01-01 12:00:00+0800'）",
        },
        examples=[
            {"arguments": {}, "result": "2025-01-01 12:00:00+0800"},
            {"arguments": {"timezone_str": "Asia/Shanghai"}, "result": "2025-01-01 12:00:00+0800"},
        ],
        available=True,
        tags=["builtin", "time"],
    )
    registry.register(spec, time_now)
    return 1