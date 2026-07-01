from __future__ import annotations

from dataclasses import dataclass
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
MAINTENANCE_MODEL_BLOCKED_TOOLS = {"vika.catalog.refresh", "vika.catalog.clear"}
LIVE_DISCOVERY_MODEL_BLOCKED_TOOLS = {
    "vika.spaces.list",
    "vika.nodes.list",
    "vika.nodes.search",
    "vika.nodes.tree",
    "vika.nodes.get",
}
MODEL_BLOCKED_TOOLS = BLOCKED_DIRECT_MODEL_TOOLS | MAINTENANCE_MODEL_BLOCKED_TOOLS | LIVE_DISCOVERY_MODEL_BLOCKED_TOOLS

CAPABILITY_ONLY_GUIDANCE = (
    "Search is capability-only. Extract the business table name yourself, call "
    "vika_resolve_datasheet(query=...), then search with a capability such as records.query."
)


@dataclass(frozen=True)
class _ToolSearchScore:
    score: int
    admissible: bool
    match_basis: Optional[str] = None


ROUTE_TASKS: Dict[str, Dict[str, Any]] = {
    "record_query": {
        "tool_name": "vika.records.query",
        "domain": "query",
        "capability": "records.query",
        "role": "read",
        "table_scoped": True,
        "write_preview": False,
    },
    "record_export": {
        "tool_name": "vika_export_records",
        "domain": "export",
        "capability": "records.export",
        "role": "export",
        "table_scoped": True,
        "write_preview": False,
    },
    "record_create": {
        "tool_name": "vika.records.create",
        "domain": "write",
        "capability": "records.create",
        "role": "preview",
        "table_scoped": True,
        "write_preview": True,
    },
    "record_update": {
        "tool_name": "vika.records.update",
        "domain": "write",
        "capability": "records.update",
        "role": "preview",
        "table_scoped": True,
        "write_preview": True,
    },
    "record_delete": {
        "tool_name": "vika.records.delete",
        "domain": "write",
        "capability": "records.delete",
        "role": "preview",
        "table_scoped": True,
        "write_preview": True,
    },
    "schema_read": {
        "tool_name": "vika.schema.get",
        "domain": "schema",
        "capability": "schema.get",
        "role": "read",
        "table_scoped": True,
        "write_preview": False,
    },
    "attachment_upload": {
        "tool_name": "vika.attachments.upload",
        "domain": "write",
        "capability": "attachments.upload",
        "role": "preview",
        "table_scoped": True,
        "write_preview": True,
    },
    "write_commit": {
        "tool_name": "vika.write.commit",
        "domain": "write",
        "capability": "write.commit",
        "role": "commit_after_user_confirmation",
        "table_scoped": False,
        "write_preview": False,
    },
}
TABLE_SCOPED_ROUTE_KINDS = {task_kind for task_kind, route in ROUTE_TASKS.items() if route["table_scoped"]}


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
    task_kind_prop = {"type": "string", "enum": sorted(ROUTE_TASKS)}
    return [
        ToolDefinition(
            name="vika_guide",
            description=(
                "Return the Vika MCP operating guide. Start here when unsure. It tells the LLM to extract the "
                "business table name itself, resolve the datasheet, then use capability-only search and "
                "structured workflow planning."
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
                "Resolve a Vika datasheet from a datasheet_id, URL, table name, path, space hint, or the exact "
                "business object that the LLM extracted from the user request. Do not guess when multiple "
                "candidates remain."
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
                "Capability-only search over hidden Vika tools. Use domain/capability or a stable capability "
                "keyword such as records.query or 导出记录; do not pass full user business tasks. "
                "Call vika_describe_tool next for schema and examples."
            ),
            input_schema=_schema(
                {
                    "query": text_prop,
                    "domain": text_prop,
                    "capability": text_prop,
                    "top_k": int_prop,
                }
            ),
            domain="guide",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 8000},
            aliases=["search tools", "工具搜索", "检索工具"],
        ),
        ToolDefinition(
            name="vika_route_task",
            description=(
                "Structured workflow planner for an LLM-understood Vika task. Provide task_kind plus the "
                "datasheet_query or datasheet_id that the LLM already extracted. It rejects free-text task input, "
                "does not parse business language, does not execute tools, and never commits writes."
            ),
            input_schema=_schema(
                {
                    "task_kind": task_kind_prop,
                    "datasheet_query": text_prop,
                    "datasheet_id": text_prop,
                    "has_user_confirmation": bool_prop,
                },
                ["task_kind"],
            ),
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
                "Set a session domain hint for capability search only. It does not dynamically register business "
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
            description=(
                "Search a service-created export artifact by keyword or field value. Supports CSV by default and "
                "JSONL when requested. Hard max 100 hits."
            ),
            input_schema=_schema({"artifact_id": text_prop, "query": text_prop, "max_hits": int_prop}, ["artifact_id", "query"]),
            domain="export",
            exposure="visible",
            result_policy={"mode": "inline", "max_chars": 40000},
            aliases=["artifact search", "搜索导出", "文件搜索"],
        ),
        ToolDefinition(
            name="vika_artifact_read",
            description=(
                "Read a bounded line window from a service-created export artifact. Supports CSV by default and "
                "JSONL when requested. Hard max 500 lines and 40000 chars."
            ),
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
            "llm_responsibility": [
                "LLM must understand the user request and extract the 业务表名/business table name or business object itself.",
                "Pass that exact business object to vika_resolve_datasheet(query=...).",
                "MCP does not parse, clean, or guess user business natural language.",
            ],
            "default_flow": [
                "不知道 datasheet_id 时先调用 vika_resolve_datasheet(query='<LLM extracted business table name>').",
                "如果返回 catalog_not_ready/catalog_stale/refreshing/refresh_abandoned/failed, 停止当前任务并请维护方刷新 catalog; 不要在模型路径触发 refresh.",
                "定位表后先获取 schema.",
                "Use vika_search_tools as capability-only search, for example domain='query', capability='records.query'.",
                "Use vika_route_task only as a structured workflow planner with task_kind, datasheet_query, or datasheet_id.",
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
            "effect": "search_hint_only",
            "permissions_changed": False,
            "active_domain_hints": sorted(self.active_domains),
        }

    async def search_tools(
        self,
        query: str = "",
        domain: Optional[str] = None,
        capability: Optional[str] = None,
        top_k: int = SEARCH_TOP_K_DEFAULT,
    ) -> Dict[str, Any]:
        top_k = min(max(int(top_k or SEARCH_TOP_K_DEFAULT), 1), SEARCH_TOP_K_MAX)
        query_text = (query or "").strip().lower()
        capability_text = (capability or "").strip().lower()
        domain_text = (domain or "").strip() or None

        if not query_text and not capability_text and not domain_text:
            return {
                "query": query,
                "domain": domain,
                "capability": capability,
                "top_k": top_k,
                "candidates": [],
                "guidance": CAPABILITY_ONLY_GUIDANCE,
            }

        candidates: List[Dict[str, Any]] = []
        for spec in self.hidden_registry.list_hidden_tools(include_unavailable=True):
            if spec.name in MODEL_BLOCKED_TOOLS:
                continue
            if self.workbench_url and spec.name in WORKBENCH_BLOCKED_TOOLS:
                continue
            if domain_text and spec.domain != domain_text:
                continue
            scored = self._score_tool(spec, query_text=query_text, capability_text=capability_text, domain_filter=domain_text)
            if not scored.admissible:
                continue
            candidate = {
                "name": spec.name,
                "domain": spec.domain,
                "capability": spec.capability_id,
                "brief": spec.description,
                "risk": spec.risk,
                "active": spec.available,
                "hidden": True,
                "next_step": f"Call vika_describe_tool with tool_name='{spec.name}'.",
                "score": scored.score,
                "capability_priority": spec.capability_priority,
                "unavailable_reason": spec.unavailable_reason,
            }
            if scored.match_basis:
                candidate["match_basis"] = scored.match_basis
            candidates.append(candidate)
        candidates.sort(key=lambda item: (-item["score"], -item["capability_priority"], item["name"]))
        for candidate in candidates:
            candidate.pop("score", None)
            candidate.pop("capability_priority", None)
        result = {
            "query": query,
            "domain": domain,
            "capability": capability,
            "top_k": top_k,
            "candidates": candidates[:top_k],
        }
        if not result["candidates"]:
            result["guidance"] = CAPABILITY_ONLY_GUIDANCE
        return result

    async def route_task(
        self,
        task_kind: Optional[str] = None,
        datasheet_query: Optional[str] = None,
        datasheet_id: Optional[str] = None,
        has_user_confirmation: bool = False,
        task: Optional[str] = None,
    ) -> Dict[str, Any]:
        if task is not None:
            return {
                "error": {
                    "code": "unsupported_natural_language_route_input",
                    "message": "vika_route_task no longer accepts free-text task input. The LLM must provide task_kind and extracted datasheet_query or datasheet_id.",
                    "details": {"task": task},
                }
            }
        if not task_kind:
            return {
                "error": {
                    "code": "task_kind_required",
                    "message": "Provide a structured task_kind such as record_query, record_export, record_update, or schema_read.",
                    "details": {"allowed_task_kinds": sorted(ROUTE_TASKS)},
                }
            }
        route = ROUTE_TASKS.get(task_kind)
        if route is None:
            return {
                "error": {
                    "code": "unknown_task_kind",
                    "message": f"Unknown task_kind: {task_kind}",
                    "details": {"allowed_task_kinds": sorted(ROUTE_TASKS)},
                }
            }
        if task_kind in TABLE_SCOPED_ROUTE_KINDS and not datasheet_id and not datasheet_query:
            return {
                "error": {
                    "code": "datasheet_target_required",
                    "message": "This workflow needs a datasheet_id or an LLM-extracted datasheet_query before routing.",
                    "details": {"task_kind": task_kind, "datasheet_id": datasheet_id, "datasheet_query": datasheet_query},
                }
            }

        recommended_tools = [self._recommended_tool(route)]
        if route["write_preview"]:
            recommended_tools.append(
                {
                    "tool_name": "vika.write.commit",
                    "domain": "write",
                    "capability": "write.commit",
                    "role": "commit_after_user_confirmation",
                    "reason": "Commit the preview operation after one-sentence user confirmation using confirmed_payload_hash.",
                    "next_step": "vika_describe_tool(tool_name='vika.write.commit')",
                }
            )

        sequence = self._route_sequence(route, datasheet_query=datasheet_query, datasheet_id=datasheet_id)
        result: Dict[str, Any] = {
            "task_kind": task_kind,
            "recommended_sequence": sequence,
            "recommended_tools": recommended_tools,
            "auto_commits_write": False,
            "has_user_confirmation": bool(has_user_confirmation),
        }
        if datasheet_query is not None:
            result["datasheet_query"] = datasheet_query
        if datasheet_id is not None:
            result["datasheet_id"] = datasheet_id
        return result

    async def describe_tool(self, tool_name: str) -> Dict[str, Any]:
        if tool_name in BLOCKED_DIRECT_MODEL_TOOLS:
            return {
                "error": {
                    "code": "tool_not_model_entry",
                    "message": "records.read_all is internal export implementation only; use vika_export_records when available.",
                }
            }
        if tool_name in MAINTENANCE_MODEL_BLOCKED_TOOLS:
            return {
                "error": {
                    "code": "tool_not_model_entry",
                    "message": "Catalog refresh/clear are maintenance operations and are not callable from the normal model task path.",
                }
            }
        if tool_name in LIVE_DISCOVERY_MODEL_BLOCKED_TOOLS:
            return {
                "error": {
                    "code": "tool_not_model_entry",
                    "message": "Live space/node discovery is internal or maintenance-only; use vika_resolve_datasheet and cache-backed catalog state.",
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
            "capability": spec.capability_id,
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
        if tool_name in MAINTENANCE_MODEL_BLOCKED_TOOLS:
            return {
                "error": {
                    "code": "tool_not_model_entry",
                    "message": "Catalog refresh/clear are maintenance operations and are not callable from the normal model task path.",
                }
            }
        if tool_name in LIVE_DISCOVERY_MODEL_BLOCKED_TOOLS:
            return {
                "error": {
                    "code": "tool_not_model_entry",
                    "message": "Live space/node discovery is internal or maintenance-only; use vika_resolve_datasheet and cache-backed catalog state.",
                }
            }
        try:
            spec, handler = self.hidden_registry.get(tool_name)
        except KeyError:
            return {"error": {"code": "tool_not_found", "message": f"Tool not found: {tool_name}"}}
        scope_error = await self.scope.check_tool_call(tool_name, arguments or {}, write=spec.write)
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
                "next_actions": ["vika_search_tools(domain='schema', capability='schema.get')", "vika_describe_tool", "vika_call_tool"],
            }
        return {
            "selected": None,
            "candidates": [],
            "need_user_choice": True,
            "match_basis": "no_explicit_datasheet_id",
            "query": query or table_name,
            "workbench_scope": self.workbench_url,
            "next_actions": [
                "Ask the user for a datasheet URL/id, or ask an operator to refresh the cache-only catalog until ready_for_discovery=true."
            ],
        }

    def _recommended_tool(self, route: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = route["tool_name"]
        try:
            spec, _handler = self.hidden_registry.get(tool_name)
            reason = spec.description
            risk = spec.risk
        except KeyError:
            reason = f"Hidden tool {tool_name} is expected for capability {route['capability']}."
            risk = "low"
        return {
            "tool_name": tool_name,
            "domain": route["domain"],
            "capability": route["capability"],
            "role": route["role"],
            "risk": risk,
            "reason": reason,
            "next_step": f"vika_describe_tool(tool_name='{tool_name}')",
        }

    def _route_sequence(self, route: Dict[str, Any], datasheet_query: Optional[str], datasheet_id: Optional[str]) -> List[str]:
        sequence: List[str] = ["vika_guide"]
        if route["table_scoped"]:
            if datasheet_id:
                sequence.append(f"vika_resolve_datasheet(datasheet_id='{datasheet_id}')")
            else:
                sequence.append(f"vika_resolve_datasheet(query='{datasheet_query}')")
        sequence.append(f"vika_search_tools(domain='{route['domain']}', capability='{route['capability']}')")
        sequence.append(f"vika_describe_tool(tool_name='{route['tool_name']}')")
        if route["write_preview"]:
            sequence.extend(
                [
                    f"vika_call_tool(tool_name='{route['tool_name']}', arguments={{...}}) preview",
                    "user confirmation",
                    "vika_call_tool(tool_name='vika.write.commit', arguments={operation_id, confirmed_payload_hash, confirmed_by_user=true})",
                ]
            )
        elif route["tool_name"] == "vika.write.commit":
            sequence.append(
                "vika_call_tool(tool_name='vika.write.commit', arguments={operation_id, confirmed_payload_hash, confirmed_by_user=true})"
            )
        else:
            sequence.append(f"vika_call_tool(tool_name='{route['tool_name']}', arguments={{...}})")
        return sequence

    def _score_tool(self, spec: ToolDefinition, query_text: str, capability_text: str, domain_filter: Optional[str]) -> _ToolSearchScore:
        score = 0
        admissible = False
        match_basis = None

        capability_id = (spec.capability_id or spec.name).lower()
        capability_aliases = [alias.lower() for alias in spec.capability_aliases if alias]
        compact_query = self._compact_text(query_text)

        if capability_text:
            compact_capability = self._compact_text(capability_text)
            if capability_text == capability_id or compact_capability == self._compact_text(capability_id):
                return _ToolSearchScore(score=240, admissible=True, match_basis="capability_id")
            for alias in capability_aliases:
                if capability_text == alias or compact_capability == self._compact_text(alias):
                    return _ToolSearchScore(score=220, admissible=True, match_basis="capability_alias")
            return _ToolSearchScore(score=0, admissible=False)

        if query_text:
            tool_name = spec.name.lower()
            compact_tool_name = self._compact_text(tool_name)
            if query_text == tool_name or compact_query == compact_tool_name:
                score += 200
                admissible = True
                match_basis = "tool_name"
            if query_text == capability_id or compact_query == self._compact_text(capability_id):
                score += 180
                admissible = True
                match_basis = "capability_id"
            for alias in capability_aliases:
                if self._capability_phrase_matches(alias, query_text, compact_query):
                    score += 150
                    admissible = True
                    match_basis = "capability_alias"
            for key in (spec.input_schema or {}).get("properties", {}).keys():
                normalized_key = key.lower()
                if query_text == normalized_key or compact_query == self._compact_text(normalized_key):
                    score += 40
                    admissible = True
                    match_basis = "schema_key"
        elif domain_filter:
            score += 1
            admissible = True
            match_basis = "domain"

        if spec.domain in self.active_domains:
            score += 3
        return _ToolSearchScore(score=score, admissible=admissible, match_basis=match_basis)

    def _capability_phrase_matches(self, phrase: str, query_text: str, compact_query: str) -> bool:
        normalized = (phrase or "").strip().lower()
        if not normalized:
            return False
        compact_phrase = self._compact_text(normalized)
        return query_text == normalized or compact_query == compact_phrase

    @staticmethod
    def _compact_text(text: str) -> str:
        return re.sub(r"\s+", "", (text or "").lower())

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
