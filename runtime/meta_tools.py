from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .artifacts import ArtifactStore
from .registry import ToolRegistry
from .services import RuntimeServices
from .scope import WORKBENCH_BLOCKED_TOOLS, WorkbenchScope
from .types import ToolDefinition


INLINE_MAX_CHARS = 20_000
SEARCH_TOP_K_DEFAULT = 5
SEARCH_TOP_K_MAX = 10
BLOCKED_DIRECT_MODEL_TOOLS = {"vika.records.read_all"}


def _schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "required": required or [],
        "properties": properties,
        "additionalProperties": False,
    }


def visible_meta_tool_definitions() -> List[ToolDefinition]:
    text_prop = {"type": "string"}
    int_prop = {"type": "integer", "minimum": 1}
    object_prop = {"type": "object"}
    bool_prop = {"type": "boolean"}
    return [
        ToolDefinition(
            name="vika_guide",
            description=(
                "Return the Vika MCP operating guide. Start here when unsure. It explains resolve -> schema -> "
                "query/export -> preview/commit and warns against full-table inline reads."
            ),
            input_schema=_schema({}),
            domain="guide",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 4000},
            aliases=["guide", "操作手册", "流程"],
        ),
        ToolDefinition(
            name="vika_resolve_datasheet",
            description=(
                "Resolve a Vika datasheet from a datasheet_id, URL, table name, path, space hint, or natural-language "
                "query within the configured workbench scope. Do not guess when multiple candidates remain."
            ),
            input_schema=_schema(
                {
                    "datasheet_id": text_prop,
                    "url": text_prop,
                    "table_name": text_prop,
                    "space_id": text_prop,
                    "query": text_prop,
                }
            ),
            domain="discovery",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": INLINE_MAX_CHARS},
            aliases=["定位表", "查找表", "resolve"],
        ),
        ToolDefinition(
            name="vika_search_tools",
            description=(
                "Search hidden Vika tools by task words. Returns small candidates only; call vika_describe_tool next "
                "for schema. It never exposes records.read_all as a model entry."
            ),
            input_schema=_schema({"query": text_prop, "domain": text_prop, "top_k": int_prop}),
            domain="guide",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 8000},
            aliases=["search tools", "工具搜索", "检索工具"],
        ),
        ToolDefinition(
            name="vika_route_task",
            description=(
                "Route a natural-language Vika task into recommended MCP steps. It does not execute tools and never "
                "commits writes."
            ),
            input_schema=_schema({"task": text_prop}, ["task"]),
            domain="guide",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 8000},
            aliases=["route", "任务规划", "下一步"],
        ),
        ToolDefinition(
            name="vika_describe_tool",
            description=(
                "Describe one hidden Vika tool after vika_search_tools or vika_route_task. Returns input schema, "
                "risk, result policy, examples, and safe next actions."
            ),
            input_schema=_schema({"tool_name": text_prop}, ["tool_name"]),
            domain="guide",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": INLINE_MAX_CHARS},
            aliases=["describe", "工具说明"],
        ),
        ToolDefinition(
            name="vika_call_tool",
            description=(
                "Execute a hidden Vika tool by name after vika_describe_tool. Use this instead of waiting for the "
                "client tool list to refresh. Write-domain tools only create preview operations; commit requires "
                "operation_id, confirmed_payload_hash, and confirmed_by_user=true after one-sentence user confirmation."
            ),
            input_schema=_schema({"tool_name": text_prop, "arguments": object_prop}, ["tool_name"]),
            domain="guide",
            exposure="visible",
            result_policy={"mode": "inline_or_artifact", "max_chars": INLINE_MAX_CHARS},
            aliases=["call", "调用隐藏工具"],
        ),
        ToolDefinition(
            name="vika_list_domains",
            description="List Vika tool domains, risk posture, and whether a domain can auto-execute.",
            input_schema=_schema({}),
            domain="guide",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 8000},
            aliases=["domains", "能力域"],
        ),
        ToolDefinition(
            name="vika_activate_domain",
            description=(
                "Set a session domain hint for search and routing only. It does not dynamically register business "
                "tools and does not grant write permission."
            ),
            input_schema=_schema({"domain": text_prop}, ["domain"]),
            domain="guide",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 4000},
            aliases=["activate domain", "激活域"],
        ),
        ToolDefinition(
            name="vika_artifact_head",
            description="Read the first lines of a service-created export artifact. Default 20 lines, hard max 100.",
            input_schema=_schema({"artifact_id": text_prop, "lines": int_prop}, ["artifact_id"]),
            domain="export",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 40000},
            aliases=["artifact head", "文件头部", "预览导出"],
        ),
        ToolDefinition(
            name="vika_artifact_search",
            description="Search a service-created export artifact by keyword or field value. Supports CSV by default and JSONL when requested. Hard max 100 hits.",
            input_schema=_schema({"artifact_id": text_prop, "query": text_prop, "max_hits": int_prop}, ["artifact_id", "query"]),
            domain="export",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 40000},
            aliases=["artifact search", "搜索导出", "文件搜索"],
        ),
        ToolDefinition(
            name="vika_artifact_read",
            description="Read a bounded line window from a service-created export artifact. Supports CSV by default and JSONL when requested. Hard max 500 lines and 40000 chars.",
            input_schema=_schema({"artifact_id": text_prop, "start_line": int_prop, "lines": int_prop}, ["artifact_id"]),
            domain="export",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 40000},
            aliases=["artifact read", "读取导出", "按行读取"],
        ),
        ToolDefinition(
            name="vika_artifact_status",
            description="Return manifest/status for a service-created export artifact.",
            input_schema=_schema({"artifact_id": text_prop, "include_manifest": bool_prop}, ["artifact_id"]),
            domain="export",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 8000},
            aliases=["artifact status", "导出状态", "manifest"],
        ),
    ]


class MetaToolRuntime:
    def __init__(
        self,
        hidden_registry: ToolRegistry,
        workbench_url: Optional[str] = None,
        workbench_space_id: Optional[str] = None,
        artifact_store: Optional[ArtifactStore] = None,
    ) -> None:
        self.hidden_registry = hidden_registry
        self.workbench_url = workbench_url
        self.workbench_space_id = workbench_space_id
        self.artifact_store = artifact_store or RuntimeServices().artifact_store
        self.active_domains: set[str] = set()
        self.scope = WorkbenchScope(
            workbench_url=workbench_url,
            workbench_space_id=workbench_space_id,
            hidden_caller=self._call_hidden_raw,
        )
        self.resolved_datasheet_ids = self.scope.resolved_datasheet_ids

    async def guide(self) -> Dict[str, Any]:
        return {
            "default_flow": [
                "不知道 datasheet_id 时先调用 vika_resolve_datasheet.",
                "定位表后先获取 schema.",
                "只需要少量样本时用 query.",
                "需要大范围读取时用 export, 再 artifact_search/read.",
                "写入先 preview, 根据 confirmation_context/brief 用一句自然语言向用户确认, 再用 payload hash commit.",
                "不要调用 read_all 获取大表.",
                "不要猜 datasheet_id.",
            ],
            "visible_tools": [tool.name for tool in visible_meta_tool_definitions()],
            "workbench_scope": self.workbench_url,
            "output_limits": {
                "inline_max_chars": INLINE_MAX_CHARS,
                "search_top_k_max": SEARCH_TOP_K_MAX,
            },
        }

    async def list_domains(self) -> Dict[str, Any]:
        return {
            "domains": [
                {"name": "connection", "default_visible": False, "auto_execute": "read_only"},
                {"name": "discovery", "default_visible": "vika_resolve_datasheet", "auto_execute": "read_only"},
                {"name": "schema", "default_visible": False, "auto_execute": "read_only_with_limits"},
                {"name": "query", "default_visible": False, "auto_execute": "read_only_with_limits"},
                {"name": "export", "default_visible": False, "auto_execute": "artifact_only"},
                {"name": "write", "default_visible": False, "auto_execute": "preview_only"},
                {"name": "admin", "default_visible": False, "auto_execute": False},
            ],
            "active_domain_hints": sorted(self.active_domains),
        }

    async def activate_domain(self, domain: str) -> Dict[str, Any]:
        known = {item["name"] for item in (await self.list_domains())["domains"]}
        if domain not in known:
            return {"error": {"code": "unknown_domain", "message": f"Unknown domain: {domain}"}}
        self.active_domains.add(domain)
        return {
            "activated": domain,
            "effect": "search_and_route_hint_only",
            "permissions_changed": False,
            "active_domain_hints": sorted(self.active_domains),
        }

    async def search_tools(self, query: str = "", domain: Optional[str] = None, top_k: int = SEARCH_TOP_K_DEFAULT) -> Dict[str, Any]:
        top_k = min(max(int(top_k or SEARCH_TOP_K_DEFAULT), 1), SEARCH_TOP_K_MAX)
        query_text = (query or "").strip().lower()
        candidates: List[Dict[str, Any]] = []
        for spec in self.hidden_registry.list_hidden_tools(include_unavailable=True):
            if spec.name in BLOCKED_DIRECT_MODEL_TOOLS:
                continue
            if self.workbench_url and spec.name in WORKBENCH_BLOCKED_TOOLS:
                continue
            if domain and spec.domain != domain:
                continue
            score = self._score_tool(spec, query_text)
            if query_text and score <= 0:
                continue
            candidates.append(
                {
                    "name": spec.name,
                    "domain": spec.domain,
                    "brief": spec.description,
                    "risk": spec.risk,
                    "active": spec.available,
                    "hidden": True,
                    "next_step": f"Call vika_describe_tool with tool_name='{spec.name}'.",
                    "score": score,
                    "unavailable_reason": spec.unavailable_reason,
                }
            )
        candidates.sort(key=lambda item: (-item["score"], item["name"]))
        for candidate in candidates:
            candidate.pop("score", None)
        return {
            "query": query,
            "domain": domain,
            "top_k": top_k,
            "candidates": candidates[:top_k],
        }

    async def route_task(self, task: str) -> Dict[str, Any]:
        text = (task or "").lower()
        sequence = ["vika_guide", "vika_resolve_datasheet"]
        if any(word in text for word in ["字段", "列", "schema", "视图"]):
            sequence.extend(["vika_search_tools(domain='schema')", "vika_describe_tool", "vika_call_tool"])
        elif any(word in text for word in ["导出", "全量", "批量"]):
            sequence.extend(["vika_search_tools(domain='export')", "vika_describe_tool", "vika_call_tool"])
        elif any(word in text for word in ["新增", "写入", "创建", "更新", "修改", "删除"]):
            sequence.extend(["vika_search_tools(domain='write')", "vika_describe_tool", "vika_call_tool preview", "user confirmation", "vika_call_tool commit"])
        else:
            sequence.extend(["vika_search_tools(domain='query')", "vika_describe_tool", "vika_call_tool"])
        return {"task": task, "recommended_sequence": sequence, "auto_commits_write": False}

    async def describe_tool(self, tool_name: str) -> Dict[str, Any]:
        if tool_name in BLOCKED_DIRECT_MODEL_TOOLS:
            return {
                "error": {
                    "code": "tool_not_model_entry",
                    "message": "records.read_all is internal export implementation only; use vika_export_records when available.",
                }
            }
        if self.workbench_url and tool_name in WORKBENCH_BLOCKED_TOOLS:
            return {
                "error": {
                    "code": "workbench_scope_required",
                    "message": "Use vika_resolve_datasheet; token-wide space/node/catalog exploration is disabled for the configured workbench scope.",
                }
            }
        try:
            spec, _handler = self.hidden_registry.get(tool_name)
        except KeyError:
            return {"error": {"code": "tool_not_found", "message": f"Tool not found: {tool_name}"}}
        return {
            "name": spec.name,
            "domain": spec.domain,
            "description": spec.description,
            "input_schema": spec.input_schema,
            "examples": spec.examples or [],
            "risk_level": spec.risk,
            "read_only": spec.read_only,
            "write": spec.write,
            "destructive": spec.destructive,
            "available": spec.available,
            "unavailable_reason": spec.unavailable_reason,
            "result_policy": spec.result_policy,
            "failure_recovery": "Check arguments against input_schema, then retry. For unavailable Vika tools, configure the Vika API token.",
            "suggested_next_actions": [f"Call vika_call_tool with tool_name='{spec.name}' and validated arguments."],
        }

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if tool_name in BLOCKED_DIRECT_MODEL_TOOLS:
            return {
                "error": {
                    "code": "tool_not_model_entry",
                    "message": "records.read_all is internal export implementation only; use vika_export_records when available.",
                }
            }
        try:
            _spec, handler = self.hidden_registry.get(tool_name)
        except KeyError:
            return {"error": {"code": "tool_not_found", "message": f"Tool not found: {tool_name}"}}
        scope_error = await self.scope.check_tool_call(tool_name, arguments or {})
        if scope_error is not None:
            return scope_error
        return await handler(arguments or {})

    async def resolve_datasheet(
        self,
        datasheet_id: Optional[str] = None,
        url: Optional[str] = None,
        table_name: Optional[str] = None,
        space_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        parsed_id = datasheet_id or self.scope.extract_datasheet_id(url or "")
        if self.scope.enabled:
            scoped = await self.scope.resolve_datasheet(parsed_id=parsed_id, table_name=table_name, query=query, space_id=space_id)
            if scoped is not None:
                return scoped

        if parsed_id:
            self.resolved_datasheet_ids.add(parsed_id)
            return {
                "selected": {
                    "datasheet_id": parsed_id,
                    "space_id": space_id,
                    "name": table_name,
                    "source": "explicit_id_or_url",
                },
                "candidates": [],
                "need_user_choice": False,
                "match_basis": "datasheet_id" if datasheet_id else "url",
                "workbench_scope": self.workbench_url,
                "next_actions": ["vika_search_tools(domain='schema')", "vika_describe_tool", "vika_call_tool"],
            }
        return {
            "selected": None,
            "candidates": [],
            "need_user_choice": True,
            "match_basis": "no_explicit_datasheet_id",
            "query": query or table_name,
            "workbench_scope": self.workbench_url,
            "next_actions": ["Ask the user for a datasheet URL/id or refresh/search the scoped catalog."],
        }

    def _score_tool(self, spec: ToolDefinition, query_text: str) -> int:
        if not query_text:
            return 1
        haystack = " ".join(
            [
                spec.name,
                spec.domain,
                spec.description or "",
                " ".join(spec.tags),
                " ".join(spec.aliases),
                " ".join((spec.input_schema or {}).get("properties", {}).keys()),
            ]
        ).lower()
        score = 0
        for token in re.findall(r"[\w.]+", query_text):
            if token and token in haystack:
                score += 1
        for alias in spec.aliases:
            if alias and alias.lower() in query_text:
                score += 3
        if spec.domain in self.active_domains:
            score += 1
        return score

    async def _call_hidden_raw(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            _spec, handler = self.hidden_registry.get(tool_name)
        except KeyError:
            return {}
        result = handler(arguments)
        if hasattr(result, "__await__"):
            result = await result
        return result if isinstance(result, dict) else {}

    async def artifact_head(self, artifact_id: str, lines: int = 20) -> Dict[str, Any]:
        return self.artifact_store.head(artifact_id, lines=lines)

    async def artifact_search(self, artifact_id: str, query: str, max_hits: int = 20) -> Dict[str, Any]:
        return self.artifact_store.search(artifact_id, query=query, max_hits=max_hits)

    async def artifact_read(self, artifact_id: str, start_line: int = 1, lines: int = 100) -> Dict[str, Any]:
        return self.artifact_store.read(artifact_id, start_line=start_line, lines=lines)

    async def artifact_status(self, artifact_id: str, include_manifest: bool = True) -> Dict[str, Any]:
        status = self.artifact_store.status(artifact_id)
        if include_manifest:
            return status
        return {
            "artifact_id": status.get("artifact_id"),
            "record_count": status.get("record_count"),
            "format": status.get("format"),
            "created_at": status.get("created_at"),
        }
