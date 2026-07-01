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


def test_build_hidden_registry_honors_vika_and_builtin_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    monkeypatch.setenv("VIKAMCP_REGISTRY__ENABLE_VIKA_TOOLS", "false")
    monkeypatch.setenv("VIKAMCP_REGISTRY__ENABLE_BUILTIN", "true")

    registry = build_hidden_registry()
    names = {tool.name for tool in registry.list_hidden_tools(include_unavailable=True)}

    assert "time.now" in names
    assert "vika.status" not in names


def test_build_hidden_registry_enabled_toolsets_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    monkeypatch.setenv("VIKAMCP_REGISTRY__ENABLE_VIKA_TOOLS", "true")
    monkeypatch.setenv("VIKAMCP_REGISTRY__ENABLE_BUILTIN", "true")
    monkeypatch.setenv("VIKAMCP_REGISTRY__ENABLED_TOOLSETS", "builtin")

    registry = build_hidden_registry()
    names = {tool.name for tool in registry.list_hidden_tools(include_unavailable=True)}

    assert "time.now" in names
    assert "vika.status" not in names


@pytest.mark.anyio
async def test_build_hidden_registry_handlers_use_captured_vika_client() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.services import RuntimeServices

    class FakeClient:
        configured = True

        def __init__(self, name: str) -> None:
            self.name = name

        async def status(self):
            return {"client": self.name}

    registry_a = build_hidden_registry(services=RuntimeServices(), vika_client=FakeClient("a"))
    registry_b = build_hidden_registry(services=RuntimeServices(), vika_client=FakeClient("b"))

    _spec_a, status_a = registry_a.get("vika.status")
    _spec_b, status_b = registry_b.get("vika.status")

    assert await status_a({}) == {"client": "a"}
    assert await status_b({}) == {"client": "b"}
