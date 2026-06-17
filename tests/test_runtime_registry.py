from __future__ import annotations

import pytest


def test_registry_separates_visible_meta_tools_from_hidden_business_tools() -> None:
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="vika_guide",
            description="Guide the model through the safe Vika workflow.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            domain="guide",
            risk="low",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 4000},
            aliases=["guide", "操作手册"],
        ),
        lambda args: {"ok": True},
    )
    registry.register(
        ToolDefinition(
            name="vika.records.query",
            description="Query a small page of records.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            domain="query",
            risk="low",
            exposure="hidden",
            result_policy={"mode": "inline", "max_chars": 20000},
            aliases=["查询", "记录"],
        ),
        lambda args: {"records": []},
    )

    assert [tool.name for tool in registry.list_visible_tools()] == ["vika_guide"]
    assert [tool.name for tool in registry.list_hidden_tools()] == ["vika.records.query"]
    assert [tool.name for tool in registry.list_tools(exposure="visible")] == ["vika_guide"]
    assert [tool.name for tool in registry.list_tools(exposure="hidden")] == ["vika.records.query"]


def test_registry_rejects_unknown_tool_exposure() -> None:
    from vika_mcp.runtime.types import ToolDefinition

    with pytest.raises(ValueError, match="exposure"):
        ToolDefinition(
            name="bad.tool",
            description="Bad exposure.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            domain="query",
            risk="low",
            exposure="full",
            result_policy={"mode": "inline"},
        )
