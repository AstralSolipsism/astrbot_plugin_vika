import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional, Union

from ..cache import CatalogCache, catalog_readiness_error
from ..config import load_config
from ..runtime.limits import enforce_inline_record_limit, normalize_query_page_size
from ..runtime.registry import ToolRegistry
from ..runtime.services import RuntimeServices
from ..runtime.types import ToolDefinition
from ..runtime.validation import ToolInputInvalid, validate_arguments

try:
    from astral_vika import DEFAULT_API_BASE, Vika

    try:
        from astral_vika.utils import validate_field_key as _sdk_validate_field_key  # type: ignore
    except Exception:
        _sdk_validate_field_key = None  # type: ignore
    _VIKA_IMPORTED = True
except Exception:
    DEFAULT_API_BASE = "https://vika.cn"  # type: ignore
    Vika = None  # type: ignore
    _sdk_validate_field_key = None  # type: ignore
    _VIKA_IMPORTED = False


WRITE_TOOLS = {
    "vika.records.create",
    "vika.records.update",
    "vika.records.delete",
    "vika.fields.create",
    "vika.fields.delete",
    "vika.datasheets.create",
    "vika.attachments.upload",
    "vika.nodes.embedlinks.create",
    "vika.nodes.embedlinks.delete",
    "vika.write.commit",
}


TOOL_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "vika.schema.get": {
        "capability": "schema.get",
        "aliases": ["schema", "schema get", "schema fields", "table schema", "表结构", "字段和视图", "读取表结构"],
        "priority": 760,
    },
    "vika.fields.get": {
        "capability": "fields.get",
        "aliases": ["fields.get", "fields get", "field get", "字段", "获取字段", "字段详情"],
        "priority": 740,
    },
    "vika.views.get": {
        "capability": "views.get",
        "aliases": ["views.get", "views get", "view get", "视图", "获取视图", "视图详情"],
        "priority": 740,
    },
    "vika.records.query": {
        "capability": "records.query",
        "aliases": ["records query", "query records", "records.query", "查询记录", "检索记录", "筛选记录", "分页查询记录"],
        "priority": 820,
    },
    "vika.records.get": {
        "capability": "records.get",
        "aliases": ["records get", "get records", "records.get", "按记录ID获取", "获取指定记录"],
        "priority": 780,
    },
    "vika_export_records": {
        "capability": "records.export",
        "aliases": ["records export", "export records", "records.export", "导出记录", "导出全量记录", "csv export"],
        "priority": 860,
    },
    "vika.records.create": {
        "capability": "records.create",
        "aliases": ["records create", "create records", "create record", "insert record", "add record", "records.create", "新增记录", "添加记录", "写入记录", "创建记录"],
        "priority": 920,
    },
    "vika.records.update": {
        "capability": "records.update",
        "aliases": ["records update", "update records", "update record", "records.update", "更新记录", "修改记录"],
        "priority": 910,
    },
    "vika.records.delete": {
        "capability": "records.delete",
        "aliases": ["records delete", "delete records", "delete record", "records.delete", "删除记录", "移除记录"],
        "priority": 910,
    },
    "vika.write.commit": {
        "capability": "write.commit",
        "aliases": ["write commit", "commit write", "payload hash", "confirmed_payload_hash", "提交写入", "确认写入", "执行写入", "提交变更"],
        "priority": 980,
    },
    "vika.fields.create": {
        "capability": "fields.create",
        "aliases": ["fields create", "create field", "fields.create", "创建字段", "新增字段", "添加字段"],
        "priority": 840,
    },
    "vika.fields.delete": {
        "capability": "fields.delete",
        "aliases": ["fields delete", "delete field", "fields.delete", "删除字段", "移除字段"],
        "priority": 830,
    },
    "vika.datasheets.create": {
        "capability": "datasheets.create",
        "aliases": ["datasheets create", "create datasheet", "datasheets.create", "创建数据表", "新建数据表", "创建表格"],
        "priority": 900,
    },
    "vika.attachments.upload": {
        "capability": "attachments.upload",
        "aliases": ["attachments upload", "upload attachment", "attachments.upload", "上传附件", "上传文件"],
        "priority": 760,
    },
    "vika.attachments.download": {
        "capability": "attachments.download",
        "aliases": ["attachments download", "download attachment", "attachments.download", "下载附件", "下载文件"],
        "priority": 760,
    },
    "vika.nodes.embedlinks.create": {
        "capability": "embedlinks.create",
        "aliases": ["embedlinks create", "create embedlink", "embedlinks.create", "创建嵌入链接"],
        "priority": 620,
    },
    "vika.nodes.embedlinks.delete": {
        "capability": "embedlinks.delete",
        "aliases": ["embedlinks delete", "delete embedlink", "embedlinks.delete", "删除嵌入链接"],
        "priority": 610,
    },
    "vika.nodes.embedlinks.list": {
        "capability": "embedlinks.list",
        "aliases": ["embedlinks list", "list embedlinks", "embedlinks.list", "列出嵌入链接", "查看嵌入链接"],
        "priority": 600,
    },
    "vika.catalog.status": {
        "capability": "catalog.status",
        "aliases": ["catalog status", "catalog.status", "缓存状态"],
        "priority": 500,
    },
    "vika.catalog.search": {
        "capability": "catalog.search",
        "aliases": ["catalog search", "catalog.search"],
        "priority": 500,
    },
    "vika.catalog.get": {
        "capability": "catalog.get",
        "aliases": ["catalog get", "catalog.get"],
        "priority": 500,
    },
}


class VikaClient:
    def __init__(
        self,
        api_token: Optional[str],
        host: Optional[str] = None,
        default_space_id: Optional[str] = None,
        workbench_space_id: Optional[str] = None,
        cache: Optional[CatalogCache] = None,
    ) -> None:
        self.api_token = api_token
        self.host = (host or DEFAULT_API_BASE or "https://vika.cn").rstrip("/")
        self.default_space_id = default_space_id
        self.workbench_space_id = workbench_space_id
        self.cache = cache
        self._last_node_refresh_requests: List[Dict[str, Any]] = []
        self._last_node_refresh_required_errors: List[Dict[str, Any]] = []

    @property
    def configured(self) -> bool:
        return bool(self.api_token) and _VIKA_IMPORTED

    @property
    def namespace(self) -> str:
        digest = hashlib.sha256(f"{self.host}|{self.api_token or ''}".encode("utf-8")).hexdigest()
        return digest[:24]

    def _ensure_client(self) -> Any:
        if not _VIKA_IMPORTED:
            raise RuntimeError("astral_vika SDK is not available")
        if not self.api_token:
            raise RuntimeError("Vika API token is not configured")
        return Vika(self.api_token, api_base=self.host)  # type: ignore

    def _wrap_error(self, exc: Exception) -> Dict[str, Any]:
        details: Dict[str, Any] = {"type": exc.__class__.__name__}
        code = getattr(exc, "code", None)
        response = getattr(exc, "response", None)
        if code is not None:
            details["vika_code"] = code
        if response is not None:
            details["response"] = response
        return {"error": {"code": "vika_error", "message": str(exc), "details": details}}

    def _normalize_field_key(self, field_key: Optional[str]) -> str:
        if _sdk_validate_field_key is not None:
            try:
                return _sdk_validate_field_key(field_key)  # type: ignore
            except Exception:
                pass
        return field_key if field_key in ("name", "id") else "name"

    def _cache_max_age(self) -> Optional[int]:
        return self.cache.ttl_seconds if self.cache and self.cache.enabled else None

    def _make_space_item(self, space: Dict[str, Any]) -> Dict[str, Any]:
        space_id = space.get("id") or space.get("spaceId") or ""
        return {
            "type": "space",
            "id": space_id,
            "space_id": space_id,
            "name": space.get("name"),
            "path": space.get("name") or space_id,
            "data": space,
        }

    def _flatten_nodes(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        flattened: List[Dict[str, Any]] = []

        def visit(node: Dict[str, Any]) -> None:
            current = dict(node)
            children = current.pop("children", None) or []
            flattened.append(current)
            for child in children:
                visit(child)

        for node in nodes:
            visit(node)
        return flattened

    def _make_node_items(self, space_id: str, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        flat_nodes = self._flatten_nodes(nodes)
        by_id = {node.get("id"): node for node in flat_nodes if node.get("id")}

        def path_for(node: Dict[str, Any], seen: Optional[set] = None) -> str:
            seen = seen or set()
            node_id = node.get("id")
            if node_id in seen:
                return node.get("name") or node_id or ""
            seen.add(node_id)
            parent_id = node.get("parentId")
            parent = by_id.get(parent_id)
            if not parent:
                return node.get("name") or node_id or ""
            parent_path = path_for(parent, seen)
            return f"{parent_path}/{node.get('name') or node_id}" if parent_path else (node.get("name") or node_id or "")

        items: List[Dict[str, Any]] = []
        for node in flat_nodes:
            node_id = node.get("id")
            if not node_id:
                continue
            node_path = path_for(node)
            item = {
                "type": "node",
                "id": node_id,
                "space_id": space_id,
                "name": node.get("name"),
                "path": node_path,
                "parent_id": node.get("parentId"),
                "dst_id": node_id if node.get("type") == "Datasheet" or str(node_id).startswith("dst") else None,
                "data": node,
            }
            items.append(item)
            if item["dst_id"]:
                ds_item = dict(item)
                ds_item["type"] = "datasheet"
                items.append(ds_item)
        return items

    def _catalog_index_node(self, node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        node_id = node.get("id")
        node_type = node.get("type")
        allowed = node_type in {"Folder", "Datasheet"} or str(node_id or "").startswith(("fod", "dst"))
        if not allowed:
            return None
        indexed = dict(node)
        children = indexed.get("children")
        if isinstance(children, list):
            indexed["children"] = [
                child
                for child in (self._catalog_index_node(child) for child in children if isinstance(child, dict))
                if child is not None
            ]
        return indexed

    async def _load_catalog_nodes_from_api(self, vika: Any, space_id: str) -> List[Dict[str, Any]]:
        space = vika.space(space_id)
        merged: Dict[str, Dict[str, Any]] = {}
        refresh_requests: List[Dict[str, Any]] = []
        required_errors: List[Dict[str, Any]] = []

        async def add_nodes(nodes: List[Any]) -> None:
            for node in nodes:
                raw = node.raw_data if hasattr(node, "raw_data") else node
                node_id = raw.get("id") if isinstance(raw, dict) else None
                indexed = self._catalog_index_node(raw) if isinstance(raw, dict) else None
                if node_id and indexed:
                    merged[node_id] = indexed

        async def timed_add(request: str, call: Callable[[], Any], required: bool = False) -> None:
            started_at = time.time()
            try:
                nodes = await call()
                await add_nodes(nodes)
                refresh_requests.append(
                    {
                        "request": request,
                        "duration_seconds": max(0.0, time.time() - started_at),
                        "count": len(nodes or []),
                        "error": None,
                    }
                )
            except Exception as exc:
                record = {
                    "request": request,
                    "duration_seconds": max(0.0, time.time() - started_at),
                    "count": 0,
                    "error": str(exc),
                }
                refresh_requests.append(record)
                if required:
                    required_errors.append(record)

        await timed_add("nodes.alist", space.nodes.alist)

        for node_type in ("Folder", "Datasheet"):
            await timed_add(
                f"nodes.asearch:{node_type}",
                lambda node_type=node_type: space.nodes.asearch(node_type=node_type),
                required=True,
            )

        self._last_node_refresh_requests = refresh_requests
        self._last_node_refresh_required_errors = required_errors
        return list(merged.values())

    def _catalog_refresh_scope_required(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": "catalog_refresh_scope_required",
                "message": (
                    "Catalog refresh requires an explicit bounded space_id, "
                    "vika.workbench_space_id, or vika.default_space_id; token-wide space scanning is disabled."
                ),
                "details": {
                    "workbench_space_id": self.workbench_space_id or None,
                    "default_space_id": self.default_space_id or None,
                },
            }
        }

    def _resolve_catalog_refresh_space_id(self, space_id: Optional[str]) -> Optional[str]:
        return space_id or self.workbench_space_id or self.default_space_id

    def _catalog_refresh_failed(self, message: str, details: Dict[str, Any]) -> Dict[str, Any]:
        return {"error": {"code": "catalog_refresh_failed", "message": message, "details": details}}

    def _catalog_cache_failure(
        self,
        message: str,
        space_id: Optional[str],
        stage: str,
        exc: Exception,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        details: Dict[str, Any] = {
            "space_id": space_id,
            "stage": stage,
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }
        if extra:
            details.update(extra)
        return self._catalog_refresh_failed(message, details)

    def _error_text(self, error: Any) -> str:
        if isinstance(error, str):
            return error
        try:
            return json.dumps(error, ensure_ascii=False)
        except Exception:
            return str(error)

    def _record_failed_catalog_refresh(
        self,
        space_id: str,
        counts: Dict[str, Any],
        error: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.cache:
            return error
        try:
            self.cache.finish_refresh(self.namespace, space_id, counts, error=self._error_text(error))
        except Exception as state_exc:
            error.setdefault("details", {})["failed_state_error"] = {
                "type": state_exc.__class__.__name__,
                "message": str(state_exc),
            }
        return error

    def _cache_disabled_error(self, space_id: Optional[str] = None) -> Dict[str, Any]:
        return {"error": catalog_readiness_error({"catalog_status": "disabled", "enabled": False}, space_id)}

    def _catalog_refresh_cache_unavailable(self, space_id: str) -> Optional[Dict[str, Any]]:
        if self.cache and self.cache.enabled:
            return None
        result = self._cache_disabled_error(space_id)
        result["cache"] = self.catalog_status(space_id=space_id)
        return result

    def _make_schema_items(
        self,
        datasheet_id: str,
        fields: List[Dict[str, Any]],
        views: List[Dict[str, Any]],
        space_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for field in fields:
            field_id = field.get("id") or field.get("name")
            if not field_id:
                continue
            items.append(
                {
                    "type": "field",
                    "id": f"{datasheet_id}:{field_id}",
                    "space_id": space_id or "",
                    "name": field.get("name") or field_id,
                    "path": f"{datasheet_id}/{field.get('name') or field_id}",
                    "dst_id": datasheet_id,
                    "data": field,
                }
            )
        for view in views:
            view_id = view.get("id") or view.get("name")
            if not view_id:
                continue
            items.append(
                {
                    "type": "view",
                    "id": f"{datasheet_id}:{view_id}",
                    "space_id": space_id or "",
                    "name": view.get("name") or view_id,
                    "path": f"{datasheet_id}/{view.get('name') or view_id}",
                    "dst_id": datasheet_id,
                    "data": view,
                }
            )
        return items

    async def status(self) -> Dict[str, Any]:
        return {"configured": self.configured, "host": self.host, "default_space_id": self.default_space_id or None}

    async def healthcheck(self) -> Dict[str, Any]:
        if not self.configured:
            return {
                "configured": self.configured,
                "reachable": False,
                "host": self.host,
                "default_space_id": self.default_space_id or None,
                "error_type": "NotConfigured",
                "error_message": "Vika API token or astral_vika SDK is not configured",
            }
        vika = None
        try:
            vika = self._ensure_client()
            spaces = await vika.spaces.alist()
            return {
                "configured": True,
                "reachable": True,
                "host": self.host,
                "default_space_id": self.default_space_id or None,
                "spaces_count": len(spaces),
                "error_type": None,
                "error_message": None,
            }
        except Exception as exc:
            return {
                "configured": True,
                "reachable": False,
                "host": self.host,
                "default_space_id": self.default_space_id or None,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            }
        finally:
            if vika is not None:
                await vika.aclose()

    async def spaces_list(self, use_cache: bool = True, force_refresh: bool = False) -> Dict[str, Any]:
        if self.cache and use_cache and not force_refresh:
            try:
                cached = self.cache.list_items(self.namespace, "space", max_age_seconds=self._cache_max_age())
                if cached:
                    return {"spaces": [item["data"] for item in cached], "source": "cache"}
            except Exception:
                pass
        vika = None
        try:
            vika = self._ensure_client()
            spaces = await vika.spaces.alist()
            if self.cache:
                try:
                    self.cache.upsert_items(self.namespace, [self._make_space_item(space) for space in spaces])
                except Exception:
                    pass
            return {"spaces": spaces, "source": "api"}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def nodes_list(
        self,
        space_id: str,
        use_cache: bool = True,
        force_refresh: bool = False,
        cache_only: bool = False,
    ) -> Dict[str, Any]:
        if force_refresh and (not self.cache or not self.cache.enabled):
            return self._cache_disabled_error(space_id)
        if self.cache and use_cache and not force_refresh:
            try:
                ready_discovery = self.cache.read_ready_discovery(self.namespace, space_id=space_id)
                if not ready_discovery.get("ready"):
                    if cache_only:
                        return {"error": ready_discovery["error"]}
                else:
                    cached = ready_discovery.get("items", [])
                    if cached or cache_only:
                        return {"nodes": cached, "source": "cache", "catalog": ready_discovery["catalog"]}
                if cache_only:
                    return self._cache_disabled_error(space_id)
            except Exception as exc:
                if cache_only:
                    return {
                        "error": catalog_readiness_error(
                            {"catalog_status": "failed", "last_refresh_error": str(exc)},
                            space_id,
                        )
                    }
        if cache_only:
            return self._cache_disabled_error(space_id)
        vika = None
        try:
            vika = self._ensure_client()
            raw_nodes = await self._load_catalog_nodes_from_api(vika, space_id)
            if self._last_node_refresh_required_errors:
                return self._catalog_refresh_failed(
                    "Catalog node refresh failed because required Folder/Datasheet requests did not complete.",
                    {
                        "space_id": space_id,
                        "failed_requests": list(self._last_node_refresh_required_errors),
                        "refresh_requests": list(self._last_node_refresh_requests),
                    },
                )
            items = self._make_node_items(space_id, raw_nodes)
            if self.cache:
                try:
                    self.cache.replace_discovery_items(self.namespace, space_id, items)
                except Exception as exc:
                    if force_refresh:
                        return self._catalog_cache_failure(
                            "Catalog refresh failed while persisting discovery cache.",
                            space_id,
                            "cache_persist",
                            exc,
                            {"refresh_requests": list(self._last_node_refresh_requests)},
                        )
                    return {
                        "nodes": items,
                        "source": "api",
                        "refresh_requests": list(self._last_node_refresh_requests),
                        "cache_persist_error": {
                            "type": exc.__class__.__name__,
                            "message": str(exc),
                        },
                    }
            return {"nodes": items, "source": "api", "refresh_requests": list(self._last_node_refresh_requests)}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def nodes_search(
        self,
        space_id: str,
        query: Optional[str] = None,
        node_type: Optional[str] = None,
        permissions: Optional[Union[int, str, List[Union[int, str]]]] = None,
        use_cache: bool = True,
        force_refresh: bool = False,
        limit: int = 20,
    ) -> Dict[str, Any]:
        if self.cache and use_cache:
            if force_refresh:
                return {
                    "error": {
                        "code": "catalog_refresh_required",
                        "message": "Node search does not perform refresh; use the catalog refresh maintenance path.",
                        "details": {"space_id": space_id},
                    }
                }
            try:
                results = self.cache.search(self.namespace, query or "", space_id=space_id, node_type=node_type, limit=limit)
                if results:
                    return {"nodes": results, "source": "cache"}
            except Exception:
                pass
        vika = None
        try:
            vika = self._ensure_client()
            nodes = await vika.space(space_id).nodes.asearch(query=query, node_type=node_type, permissions=permissions)
            raw_nodes = [node.raw_data for node in nodes]
            return {"nodes": self._make_node_items(space_id, raw_nodes), "source": "api"}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def nodes_get(self, space_id: str, node_id: str, use_cache: bool = True) -> Dict[str, Any]:
        if self.cache and use_cache:
            cached = self.cache.get_item(self.namespace, "node", node_id)
            if cached and cached.get("space_id") == space_id:
                return {"node": cached, "source": "cache"}
        vika = None
        try:
            vika = self._ensure_client()
            node = await vika.space(space_id).nodes.aget(node_id)
            item = self._make_node_items(space_id, [node.raw_data])[0]
            if self.cache:
                try:
                    self.cache.upsert_items(self.namespace, [item])
                except Exception:
                    pass
            return {"node": item, "source": "api"}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def nodes_tree(self, space_id: str, use_cache: bool = True, force_refresh: bool = False) -> Dict[str, Any]:
        result = await self.nodes_list(space_id, use_cache=use_cache, force_refresh=force_refresh)
        if "error" in result:
            return result
        nodes = [item for item in result.get("nodes", []) if item.get("type") == "node"]
        by_id = {item["id"]: dict(item, children=[]) for item in nodes}
        roots: List[Dict[str, Any]] = []
        for item in by_id.values():
            parent_id = item.get("parent_id")
            parent = by_id.get(parent_id)
            if parent:
                parent["children"].append(item)
            else:
                roots.append(item)
        return {"tree": roots, "source": result.get("source")}

    async def embedlinks_list(self, space_id: str, node_id: str) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            return {"embed_links": await vika.space(space_id).nodes.aget_embed_links(node_id)}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def embedlinks_create(self, space_id: str, node_id: str, theme: Optional[str], payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            return {"embed_link": await vika.space(space_id).nodes.acreate_embed_link(node_id, theme=theme, payload=payload)}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def embedlinks_delete(self, space_id: str, node_id: str, link_id: str) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            deleted = await vika.space(space_id).nodes.adelete_embed_link(node_id, link_id)
            return {"deleted": deleted, "link_id": link_id}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def records_query(
        self,
        datasheet_id: str,
        view_id: Optional[str] = None,
        formula: Optional[str] = None,
        fields: Optional[List[str]] = None,
        page_size: Optional[int] = None,
        page_num: Optional[int] = None,
        page_token: Optional[str] = None,
        sort: Optional[List[Dict[str, Any]]] = None,
        field_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            ds = vika.datasheet(datasheet_id, field_key=self._normalize_field_key(field_key))
            resp = await ds.records._aget_records(
                view_id=view_id,
                fields=fields,
                filterByFormula=formula,
                page_size=page_size,
                page_num=page_num,
                page_token=page_token,
                sort=sort,
                field_key=self._normalize_field_key(field_key),
                cell_format="json",
            )
            data = resp.get("data", {}) or {}
            page_token_out = data.get("pageToken") or None
            out: Dict[str, Any] = {
                "records": data.get("records", []) or [],
                "has_more": bool(page_token_out) or bool(data.get("hasMore")),
                "next_offset": page_token_out,
                "total": data.get("total"),
            }
            return out
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def records_read_all(
        self,
        datasheet_id: str,
        view_id: Optional[str] = None,
        formula: Optional[str] = None,
        fields: Optional[List[str]] = None,
        page_size: int = 100,
        max_records: Optional[int] = None,
        max_pages: Optional[int] = None,
        sort: Optional[List[Dict[str, Any]]] = None,
        field_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        if max_records is None and max_pages is None:
            return {"error": {"code": "tool_input_invalid", "message": "max_records or max_pages is required", "details": {}}}
        page_size = min(max(1, int(page_size or 100)), 1000)
        records: List[Dict[str, Any]] = []
        pages_read = 0
        next_offset = None
        total = None
        while True:
            if max_pages is not None and pages_read >= max_pages:
                break
            remaining = None if max_records is None else max_records - len(records)
            if remaining is not None and remaining <= 0:
                break
            current_page_size = min(page_size, remaining) if remaining is not None else page_size
            page = await self.records_query(
                datasheet_id,
                view_id=view_id,
                formula=formula,
                fields=fields,
                page_size=current_page_size,
                page_num=pages_read + 1 if next_offset is None else None,
                page_token=next_offset,
                sort=sort,
                field_key=field_key,
            )
            if "error" in page:
                return page
            total = page.get("total", total)
            batch = page.get("records", []) or []
            records.extend(batch)
            pages_read += 1
            next_offset = page.get("next_offset")
            if not page.get("has_more") or not batch:
                break
        if max_records is not None:
            records = records[:max_records]
        return {"records": records, "count": len(records), "pages_read": pages_read, "has_more": bool(next_offset), "next_offset": next_offset, "total": total}

    async def records_create(self, datasheet_id: str, records: Union[List[Dict[str, Any]], Dict[str, Any]], field_key: Optional[str] = None) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            ds = vika.datasheet(datasheet_id, field_key=self._normalize_field_key(field_key))
            created = await ds.records.acreate(records)
            return {"records": [record.raw_data for record in created]}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def records_update(self, datasheet_id: str, records: Union[List[Dict[str, Any]], Dict[str, Any]], field_key: Optional[str] = None) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            ds = vika.datasheet(datasheet_id, field_key=self._normalize_field_key(field_key))
            updated = await ds.records.aupdate(records)
            return {"records": [record.raw_data for record in updated]}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def records_delete(self, datasheet_id: str, record_ids: List[str]) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            deleted = await vika.datasheet(datasheet_id).records.adelete(record_ids)
            return {"deleted": deleted, "record_ids": record_ids}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def records_get(self, datasheet_id: str, record_ids: List[str], fields: Optional[List[str]] = None, field_key: Optional[str] = None) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            ds = vika.datasheet(datasheet_id, field_key=self._normalize_field_key(field_key))
            resp = await ds.records._aget_records(record_ids=record_ids, fields=fields, field_key=self._normalize_field_key(field_key), cell_format="json")
            return {"records": (resp.get("data") or {}).get("records", []) or []}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def fields_get(self, datasheet_id: str, field_id_or_name: str) -> Dict[str, Any]:
        schema = await self.schema_get(datasheet_id, use_cache=True, force_refresh=False)
        if "error" in schema:
            return schema
        for field in schema.get("fields", []):
            if field.get("id") == field_id_or_name or field.get("name") == field_id_or_name:
                return {"field": field}
        return {"error": {"code": "vika_error", "message": f"Field not found: {field_id_or_name}", "details": {"type": "NotFound"}}}

    async def fields_create(self, datasheet_id: str, space_id: str, name: str, field_type: str, property: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            property_model = None
            if isinstance(property, dict):
                from typing import Any as _Any, Optional as _Optional
                from pydantic import create_model

                model_fields = {key: (_Optional[_Any], value) for key, value in property.items()}
                property_model = create_model("FieldPropertyModel", **model_fields)(**property)
            resp = await vika.datasheet(datasheet_id, space_id=space_id).fields.acreate(field_type=field_type, name=name, property=property_model)
            return {"id": resp.id, "name": resp.name, "type": field_type, "property": property}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def fields_delete(self, datasheet_id: str, space_id: str, field_id_or_name: str) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            deleted = await vika.datasheet(datasheet_id, space_id=space_id).fields.adelete(field_id_or_name)
            return {"deleted": deleted}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def views_get(self, datasheet_id: str, view_id_or_name: str) -> Dict[str, Any]:
        schema = await self.schema_get(datasheet_id, use_cache=True, force_refresh=False)
        if "error" in schema:
            return schema
        for view in schema.get("views", []):
            if view.get("id") == view_id_or_name or view.get("name") == view_id_or_name:
                return {"view": view}
        return {"error": {"code": "vika_error", "message": f"View not found: {view_id_or_name}", "details": {"type": "NotFound"}}}

    async def attachments_upload(self, datasheet_id: str, file_path: str) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            attachment = await vika.datasheet(datasheet_id).attachments.aupload(file_path)
            return attachment.raw_data
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def attachments_download(self, url: Optional[str] = None, attachment: Optional[Dict[str, Any]] = None, save_path: Optional[str] = None) -> Dict[str, Any]:
        vika = None
        try:
            if not url and not attachment:
                raise ValueError("either 'url' or 'attachment' must be provided")
            vika = self._ensure_client()
            path = await vika.datasheet("dst_dummy_for_attachment").attachments.adownload(attachment if attachment is not None else (url or ""), save_path)
            return {"path": path}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def datasheets_create(
        self,
        space_id: str,
        name: str,
        description: Optional[str] = None,
        folder_id: Optional[str] = None,
        pre_filled_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        vika = None
        try:
            vika = self._ensure_client()
            datasheet = await vika.space(space_id).datasheets.acreate(name=name, description=description, folder_id=folder_id, pre_filled_records=pre_filled_records)
            return {"id": datasheet.dst_id, "name": name}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def schema_get(self, datasheet_id: str, space_id: Optional[str] = None, use_cache: bool = True, force_refresh: bool = False) -> Dict[str, Any]:
        if self.cache and use_cache and not force_refresh:
            try:
                schema = self.cache.get_schema(self.namespace, datasheet_id, max_age_seconds=self._cache_max_age())
                if schema["fields"] or schema["views"]:
                    primary = next((field for field in schema["fields"] if field.get("isPrimary")), None)
                    return {"datasheet_id": datasheet_id, "space_id": space_id, "fields": schema["fields"], "views": schema["views"], "primary_field": primary, "source": "cache"}
            except Exception:
                pass
        vika = None
        try:
            vika = self._ensure_client()
            ds = vika.datasheet(datasheet_id, space_id=space_id)
            fields = [field.raw_data for field in await ds.fields.aall()]
            views = [view.raw_data for view in await ds.views.aall()]
            if self.cache:
                try:
                    self.cache.replace_schema_items(self.namespace, datasheet_id, self._make_schema_items(datasheet_id, fields, views, space_id=space_id))
                except Exception:
                    pass
            primary = next((field for field in fields if field.get("isPrimary")), None)
            return {"datasheet_id": datasheet_id, "space_id": space_id, "fields": fields, "views": views, "primary_field": primary, "source": "api"}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def _refresh_schema_cache(
        self,
        datasheet_id: str,
        space_id: Optional[str],
        include_fields: bool,
        include_views: bool,
    ) -> Dict[str, Any]:
        requested_types: List[str] = []
        fields: List[Dict[str, Any]] = []
        views: List[Dict[str, Any]] = []
        if include_fields:
            requested_types.append("field")
        if include_views:
            requested_types.append("view")
        if not requested_types:
            return {"datasheet_id": datasheet_id, "space_id": space_id, "fields": fields, "views": views, "source": "api"}

        vika = None
        try:
            vika = self._ensure_client()
            ds = vika.datasheet(datasheet_id, space_id=space_id)
            if include_fields:
                fields = [field.raw_data for field in await ds.fields.aall()]
            if include_views:
                views = [view.raw_data for view in await ds.views.aall()]
            if self.cache:
                try:
                    self.cache.replace_schema_items(
                        self.namespace,
                        datasheet_id,
                        self._make_schema_items(datasheet_id, fields, views, space_id=space_id),
                        item_types=requested_types,
                    )
                except Exception as exc:
                    return self._catalog_cache_failure(
                        "Catalog refresh failed while persisting schema cache.",
                        space_id,
                        "cache_persist",
                        exc,
                        {"datasheet_id": datasheet_id, "item_types": requested_types},
                    )
            return {"datasheet_id": datasheet_id, "space_id": space_id, "fields": fields, "views": views, "source": "api"}
        except Exception as exc:
            return self._wrap_error(exc)
        finally:
            if vika is not None:
                await vika.aclose()

    async def catalog_refresh(self, space_id: Optional[str] = None, include_fields: bool = False, include_views: bool = False, force: bool = False) -> Dict[str, Any]:
        target_space_id = self._resolve_catalog_refresh_space_id(space_id)
        if not target_space_id:
            return self._catalog_refresh_scope_required()

        cache_unavailable = self._catalog_refresh_cache_unavailable(target_space_id)
        if cache_unavailable is not None:
            return cache_unavailable

        if self.cache:
            try:
                self.cache.begin_refresh(self.namespace, target_space_id)
            except Exception as exc:
                return {
                    **self._catalog_cache_failure(
                        "Catalog refresh failed while beginning refresh state.",
                        target_space_id,
                        "refresh_state_begin",
                        exc,
                    ),
                    "cache": self.catalog_status(space_id=target_space_id),
                }
        counts = {"spaces": 0, "nodes": 0, "datasheets": 0, "fields": 0, "views": 0, "requests": []}
        target_space_ids = [target_space_id]
        counts["spaces"] = 1
        for sid in target_space_ids:
            nodes_result = await self.nodes_list(sid, use_cache=False, force_refresh=True)
            if "error" in nodes_result:
                nodes_result["error"] = self._record_failed_catalog_refresh(sid, counts, nodes_result["error"])
                result = dict(nodes_result)
                result["counts"] = counts
                result["cache"] = self.catalog_status(space_id=sid)
                return result
            nodes = nodes_result.get("nodes", [])
            counts["requests"].extend(nodes_result.get("refresh_requests", []))
            counts["nodes"] += len([item for item in nodes if item.get("type") == "node"])
            datasheets = [item for item in nodes if item.get("type") == "datasheet" and item.get("dst_id")]
            counts["datasheets"] += len(datasheets)
            schema_errors: List[Dict[str, Any]] = []
            if include_fields or include_views:
                for ds_item in datasheets:
                    schema = await self._refresh_schema_cache(ds_item["dst_id"], sid, include_fields, include_views)
                    if "error" in schema:
                        schema_errors.append({"datasheet_id": ds_item["dst_id"], "space_id": sid, "error": schema["error"]})
                        continue
                    counts["fields"] += len(schema.get("fields", [])) if include_fields else 0
                    counts["views"] += len(schema.get("views", [])) if include_views else 0
            if schema_errors:
                error = self._catalog_refresh_failed(
                    "Catalog refresh failed during requested schema refresh: "
                    + "; ".join(str(item["error"].get("message") or item["error"]) for item in schema_errors),
                    {"space_id": sid, "failed_schema": schema_errors, "counts": counts},
                )["error"]
                error = self._record_failed_catalog_refresh(sid, counts, error)
                return {"error": error, "counts": counts, "cache": self.catalog_status(space_id=sid)}
        if self.cache:
            try:
                self.cache.finish_refresh(self.namespace, target_space_id, counts)
            except Exception as exc:
                error = self._catalog_cache_failure(
                    "Catalog refresh failed while marking refresh state ready.",
                    target_space_id,
                    "refresh_state_finish",
                    exc,
                    {"counts": counts},
                )["error"]
                try:
                    self.cache.finish_refresh(self.namespace, target_space_id, counts, error=self._error_text(error))
                except Exception as state_exc:
                    error["details"]["failed_state_error"] = {
                        "type": state_exc.__class__.__name__,
                        "message": str(state_exc),
                    }
                return {"error": error, "counts": counts, "cache": self.catalog_status(space_id=target_space_id)}
        return {"refreshed": True, "space_ids": target_space_ids, "counts": counts, "cache": self.catalog_status(space_id=target_space_id)}

    def catalog_status(self, space_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.cache:
            return {"enabled": False}
        target_space_id = space_id if space_id is not None else self.workbench_space_id
        return self.cache.status(self.namespace, space_id=target_space_id)

    def catalog_search(self, query: str, space_id: Optional[str] = None, node_type: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        if not self.cache:
            return self._cache_disabled_error(space_id)
        try:
            ready_search = self.cache.search_ready(self.namespace, query, space_id=space_id, node_type=node_type, limit=limit)
            if not ready_search.get("ready"):
                return {"error": ready_search["error"], "source": "cache"}
            return {
                "matches": ready_search["matches"],
                "source": "cache",
                "catalog": ready_search["catalog"],
            }
        except Exception as exc:
            return {
                "error": catalog_readiness_error(
                    {"catalog_status": "failed", "last_refresh_error": str(exc)},
                    space_id,
                ),
                "source": "cache",
            }

    def catalog_get(self, item_type: str, item_id: str) -> Dict[str, Any]:
        if not self.cache:
            return self._cache_disabled_error()
        try:
            ready_item = self.cache.get_ready_item(self.namespace, item_type, item_id)
            if not ready_item.get("ready"):
                return {"error": ready_item["error"], "source": "cache"}
            return {"item": ready_item["item"], "source": "cache", "catalog": ready_item["catalog"]}
        except Exception as exc:
            return {
                "error": catalog_readiness_error(
                    {"catalog_status": "failed", "last_refresh_error": str(exc)},
                    None,
                ),
                "source": "cache",
            }

    def catalog_clear(self, space_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.cache:
            return {"cleared": 0, "source": "disabled"}
        try:
            return {"cleared": self.cache.clear(self.namespace, space_id=space_id), "source": "cache"}
        except Exception as exc:
            return self._wrap_error(exc)


_CLIENT: Optional[VikaClient] = None


def _raise_if_error(result: Any) -> Any:
    if isinstance(result, dict) and "error" in result:
        raise Exception(json.dumps(result["error"], ensure_ascii=False))
    if isinstance(result, list) and result and isinstance(result[0], dict) and "error" in result[0]:
        raise Exception(json.dumps(result[0]["error"], ensure_ascii=False))
    return result


def _record_count_from_payload(payload: Dict[str, Any]) -> int:
    records = payload.get("records")
    if isinstance(records, list):
        return len(records)
    if isinstance(records, dict):
        return 1
    record_ids = payload.get("record_ids")
    if isinstance(record_ids, list):
        return len(record_ids)
    return 1


def _field_names_from_records(records: Any) -> List[str]:
    if isinstance(records, dict):
        records = [records]
    names = set()
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict):
                fields = record.get("fields")
                if isinstance(fields, dict):
                    names.update(str(key) for key in fields.keys())
    return sorted(names)


async def vika_status(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.status())


async def vika_healthcheck(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return await _CLIENT.healthcheck()


async def vika_spaces_list(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.spaces_list(args.get("use_cache", True), args.get("force_refresh", False)))


async def vika_nodes_list(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(
        await _CLIENT.nodes_list(
            args["space_id"],
            args.get("use_cache", True),
            args.get("force_refresh", False),
            args.get("cache_only", False),
        )
    )


async def vika_nodes_search(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(
        await _CLIENT.nodes_search(
            args["space_id"],
            query=args.get("query"),
            node_type=args.get("node_type"),
            permissions=args.get("permissions"),
            use_cache=args.get("use_cache", True),
            force_refresh=args.get("force_refresh", False),
            limit=args.get("limit", 20),
        )
    )


async def vika_nodes_tree(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.nodes_tree(args["space_id"], args.get("use_cache", True), args.get("force_refresh", False)))


async def vika_nodes_get(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.nodes_get(args["space_id"], args["node_id"], args.get("use_cache", True)))


async def vika_nodes_embedlinks_list(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.embedlinks_list(args["space_id"], args["node_id"]))


async def vika_nodes_embedlinks_create(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {"space_id": args["space_id"], "node_id": args["node_id"], "theme": args.get("theme"), "payload": args.get("payload")}
    return services.write_plans.preview(
        "nodes.embedlinks.create",
        args["node_id"],
        args["node_id"],
        payload,
        [],
        1,
        lambda operation: _CLIENT.embedlinks_create(
            operation["payload"]["space_id"],
            operation["payload"]["node_id"],
            operation["payload"].get("theme"),
            operation["payload"].get("payload"),
        ),
    )


async def vika_nodes_embedlinks_delete(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {"space_id": args["space_id"], "node_id": args["node_id"], "link_id": args["link_id"]}
    return services.write_plans.preview(
        "nodes.embedlinks.delete",
        args["node_id"],
        args["node_id"],
        payload,
        [],
        1,
        lambda operation: _CLIENT.embedlinks_delete(
            operation["payload"]["space_id"],
            operation["payload"]["node_id"],
            operation["payload"]["link_id"],
        ),
    )


async def vika_catalog_refresh(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return await _CLIENT.catalog_refresh(args.get("space_id"), args.get("include_fields", False), args.get("include_views", False), args.get("force", False))


async def vika_catalog_status(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _CLIENT.catalog_status()


async def vika_catalog_search(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _CLIENT.catalog_search(args.get("query", ""), args.get("space_id"), args.get("node_type"), args.get("limit", 20))


async def vika_catalog_get(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _CLIENT.catalog_get(args["item_type"], args["item_id"])


async def vika_catalog_clear(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _CLIENT.catalog_clear(args.get("space_id"))


async def vika_schema_get(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.schema_get(args["datasheet_id"], args.get("space_id"), args.get("use_cache", True), args.get("force_refresh", False)))


async def vika_records_query(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    page_size = normalize_query_page_size(args.get("page_size"))
    result = _raise_if_error(await _CLIENT.records_query(args["datasheet_id"], args.get("view_id"), args.get("formula"), args.get("fields"), page_size, args.get("page_num"), args.get("page_token"), args.get("sort"), args.get("field_key")))
    result.update(
        {
            "datasheet_id": args["datasheet_id"],
            "view_id": args.get("view_id"),
            "fields": args.get("fields"),
            "formula": args.get("formula"),
            "page_size": page_size,
        }
    )
    return enforce_inline_record_limit(result)


async def vika_records_read_all(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.records_read_all(args["datasheet_id"], args.get("view_id"), args.get("formula"), args.get("fields"), args.get("page_size", 100), args.get("max_records"), args.get("max_pages"), args.get("sort"), args.get("field_key")))


async def vika_export_records(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    result = _raise_if_error(
        await _CLIENT.records_read_all(
            args["datasheet_id"],
            args.get("view_id"),
            args.get("formula"),
            args.get("fields"),
            args.get("page_size", 100),
            args.get("max_records"),
            args.get("max_pages"),
            args.get("sort"),
            args.get("field_key"),
        )
    )
    records = result.get("records", []) or []
    field_names = args.get("fields") or sorted({key for record in records for key in (record.get("fields") or {}).keys()})
    return services.artifact_store.create_records_export(
        datasheet_id=args["datasheet_id"],
        records=records,
        field_names=field_names,
        source_args=args,
        view_id=args.get("view_id"),
        query={"formula": args.get("formula"), "sort": args.get("sort")},
        format=args.get("format") or "csv",
    )


async def vika_records_create(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {"datasheet_id": args["datasheet_id"], "records": args["records"], "field_key": args.get("field_key")}
    return services.write_plans.preview(
        "records.create",
        args["datasheet_id"],
        args.get("target_label") or args["datasheet_id"],
        payload,
        _field_names_from_records(payload["records"]),
        _record_count_from_payload(payload),
        lambda operation: _CLIENT.records_create(
            operation["payload"]["datasheet_id"],
            operation["payload"]["records"],
            operation["payload"].get("field_key"),
        ),
    )


async def vika_records_update(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {"datasheet_id": args["datasheet_id"], "records": args["records"], "field_key": args.get("field_key")}
    return services.write_plans.preview(
        "records.update",
        args["datasheet_id"],
        args.get("target_label") or args["datasheet_id"],
        payload,
        _field_names_from_records(payload["records"]),
        _record_count_from_payload(payload),
        lambda operation: _CLIENT.records_update(
            operation["payload"]["datasheet_id"],
            operation["payload"]["records"],
            operation["payload"].get("field_key"),
        ),
    )


async def vika_records_delete(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {"datasheet_id": args["datasheet_id"], "record_ids": args["record_ids"]}
    return services.write_plans.preview(
        "records.delete",
        args["datasheet_id"],
        args.get("target_label") or args["datasheet_id"],
        payload,
        [],
        _record_count_from_payload(payload),
        lambda operation: _CLIENT.records_delete(
            operation["payload"]["datasheet_id"],
            operation["payload"]["record_ids"],
        ),
    )


async def vika_write_commit(args: Dict[str, Any], services: RuntimeServices) -> Any:
    return await services.write_plans.commit(
        args["operation_id"],
        args.get("confirmed_payload_hash"),
        args.get("confirmed_by_user") is True,
        args.get("user_confirmation_summary"),
    )


async def vika_records_get(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.records_get(args["datasheet_id"], args["record_ids"], args.get("fields"), args.get("field_key")))


async def vika_fields_get(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.fields_get(args["datasheet_id"], args["field_id_or_name"]))


async def vika_fields_create(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {
        "datasheet_id": args["datasheet_id"],
        "space_id": args["space_id"],
        "name": args["name"],
        "field_type": args["field_type"],
        "property": args.get("property"),
    }
    return services.write_plans.preview(
        "fields.create",
        args["datasheet_id"],
        args.get("target_label") or args["datasheet_id"],
        payload,
        [payload["name"]],
        1,
        lambda operation: _CLIENT.fields_create(
            operation["payload"]["datasheet_id"],
            operation["payload"]["space_id"],
            operation["payload"]["name"],
            operation["payload"]["field_type"],
            operation["payload"].get("property"),
        ),
    )


async def vika_fields_delete(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {
        "datasheet_id": args["datasheet_id"],
        "space_id": args["space_id"],
        "field_id_or_name": args["field_id_or_name"],
    }
    return services.write_plans.preview(
        "fields.delete",
        args["datasheet_id"],
        args.get("target_label") or args["datasheet_id"],
        payload,
        [payload["field_id_or_name"]],
        1,
        lambda operation: _CLIENT.fields_delete(
            operation["payload"]["datasheet_id"],
            operation["payload"]["space_id"],
            operation["payload"]["field_id_or_name"],
        ),
    )


async def vika_views_get(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.views_get(args["datasheet_id"], args["view_id_or_name"]))


async def vika_attachments_upload(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {"datasheet_id": args["datasheet_id"], "file_path": args["file_path"]}
    return services.write_plans.preview(
        "attachments.upload",
        args["datasheet_id"],
        args.get("target_label") or args["datasheet_id"],
        payload,
        [],
        1,
        lambda operation: _CLIENT.attachments_upload(
            operation["payload"]["datasheet_id"],
            operation["payload"]["file_path"],
        ),
    )


async def vika_attachments_download(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.attachments_download(args["url"], None, args.get("save_path")))


async def vika_datasheets_create(args: Dict[str, Any], services: RuntimeServices) -> Any:
    assert _CLIENT is not None
    payload = {"space_id": args["space_id"], **{key: args.get(key) for key in ("name", "description", "folder_id", "pre_filled_records") if key in args}}
    return services.write_plans.preview(
        "datasheets.create",
        args["space_id"],
        args.get("name") or args["space_id"],
        payload,
        [],
        1,
        lambda operation: _CLIENT.datasheets_create(
            operation["payload"]["space_id"],
            operation["payload"]["name"],
            operation["payload"].get("description"),
            operation["payload"].get("folder_id"),
            operation["payload"].get("pre_filled_records"),
        ),
    )


def _schema(properties: Dict[str, Any], required: Optional[List[str]] = None, additional: bool = False) -> Dict[str, Any]:
    return {"type": "object", "required": required or [], "properties": properties, "additionalProperties": additional}


def _with_safety(properties: Dict[str, Any]) -> Dict[str, Any]:
    props = dict(properties)
    props["target_label"] = {
        "type": "string",
        "description": "人类可读目标表/节点名称，用于 confirmation_context；缺省时使用目标 ID。",
    }
    return props


def _domain_for_tool(name: str) -> str:
    if name in WRITE_TOOLS:
        return "write"
    if name in {"vika.status", "vika.healthcheck"}:
        return "connection"
    if ".catalog." in name or ".nodes." in name:
        return "discovery"
    if ".schema." in name or ".fields.get" in name or ".views.get" in name:
        return "schema"
    if ".records.query" in name or ".records.get" in name:
        return "query"
    if ".records.read_all" in name or name == "vika_export_records":
        return "export"
    return "admin"


def _risk_for_tool(name: str) -> str:
    if ".delete" in name or name.endswith(".clear"):
        return "high"
    if name in WRITE_TOOLS:
        return "medium"
    return "low"


def _aliases_for_tool(name: str, tags: Optional[List[str]]) -> List[str]:
    aliases = list(tags or [])
    capability = TOOL_CAPABILITIES.get(name) or {}
    aliases.extend(capability.get("aliases") or [])
    return sorted(set(aliases))


def _capability_for_tool(name: str) -> Dict[str, Any]:
    return TOOL_CAPABILITIES.get(
        name,
        {"capability": name, "aliases": [], "priority": 100},
    )


def _result_policy_for_tool(name: str) -> Dict[str, Any]:
    if ".records.read_all" in name or name == "vika_export_records":
        return {"mode": "artifact", "default_format": "csv", "supported_formats": ["csv", "jsonl"]}
    if ".records.query" in name:
        return {"mode": "inline", "default_page_size": 50, "max_page_size": 100, "max_chars": 20000}
    return {"mode": "inline", "max_chars": 20000}


def _example_value(name: str, schema: Optional[Dict[str, Any]]) -> Any:
    if name == "datasheet_id":
        return "dstExample"
    if name == "space_id":
        return "spcExample"
    if name == "folder_id":
        return "fodExample"
    if name == "node_id":
        return "fodExample"
    if name == "record_ids":
        return ["recExample"]
    if name == "operation_id":
        return "op_example"
    if name == "confirmed_payload_hash":
        return "sha256:example-preview-payload-hash"
    if name == "confirmed_by_user":
        return True
    if name == "max_records":
        return 1000
    if name == "page_size":
        return 50
    if name == "field_key":
        return "name"
    if name == "name":
        return "客户跟进表"
    if name == "field_type":
        return "SingleText"
    if name == "field_id_or_name":
        return "客户名称"
    if name == "view_id_or_name":
        return "默认视图"
    if name == "file_path":
        return "D:/AboutDEV/example.pdf"
    if name == "url":
        return "https://example.com/file.pdf"
    if name == "format":
        return "csv"

    value_type = (schema or {}).get("type")
    if isinstance(value_type, list):
        value_type = value_type[0]
    if value_type == "boolean":
        return True
    if value_type == "integer":
        return 1
    if value_type == "array":
        return []
    if value_type == "object":
        return {}
    return "example"


def _examples_for_tool(name: str, properties: Dict[str, Any], required: Optional[List[str]]) -> List[Dict[str, Any]]:
    if name == "vika.records.create":
        return [
            {
                "arguments": {
                    "datasheet_id": "dstExample",
                    "records": [{"fields": {"客户名称": "Alice", "跟进状态": "待跟进"}}],
                    "field_key": "name",
                }
            }
        ]
    if name == "vika.records.update":
        return [
            {
                "arguments": {
                    "datasheet_id": "dstExample",
                    "records": [{"recordId": "recExample", "fields": {"客户名称": "Alice", "跟进状态": "已联系"}}],
                    "field_key": "name",
                }
            }
        ]
    if name == "vika.records.delete":
        return [{"arguments": {"datasheet_id": "dstExample", "record_ids": ["recExample"]}}]
    if name == "vika.write.commit":
        return [
            {
                "arguments": {
                    "operation_id": "op_example",
                    "confirmed_payload_hash": "sha256:example-preview-payload-hash",
                    "confirmed_by_user": True,
                    "user_confirmation_summary": "用户确认向《客户跟进表》新增 1 条客户记录。",
                }
            }
        ]
    if name == "vika.datasheets.create":
        return [
            {
                "arguments": {
                    "space_id": "spcExample",
                    "folder_id": "fodExample",
                    "name": "客户跟进表",
                    "description": "客户跟进记录",
                }
            }
        ]
    if name == "vika.records.query":
        return [{"arguments": {"datasheet_id": "dstExample", "page_size": 50, "field_key": "name"}}]
    if name == "vika_export_records":
        return [{"arguments": {"datasheet_id": "dstExample", "max_records": 1000, "format": "csv"}}]

    example_keys = required or list(properties.keys())[:3]
    return [{"arguments": {key: _example_value(key, properties.get(key)) for key in example_keys}}]


def _register(
    registry: ToolRegistry,
    name: str,
    description: str,
    handler: Callable[[Dict[str, Any], RuntimeServices], Any],
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    available: Optional[bool] = None,
    output_schema: Optional[Dict[str, Any]] = None,
    services: Optional[RuntimeServices] = None,
) -> int:
    assert _CLIENT is not None
    runtime_services = services or RuntimeServices()
    domain = _domain_for_tool(name)
    risk = _risk_for_tool(name)
    capability = _capability_for_tool(name)
    spec = ToolDefinition(
        name=name,
        description=description,
        input_schema=_schema(properties, required),
        output_schema=output_schema or {"type": "object", "additionalProperties": True},
        examples=_examples_for_tool(name, properties, required),
        available=_CLIENT.configured if available is None else available,
        unavailable_reason=None if (available is True or _CLIENT.configured) else "astral_vika not configured",
        tags=tags or ["vika"],
        domain=domain,
        risk=risk,
        exposure="hidden",
        result_policy=_result_policy_for_tool(name),
        aliases=_aliases_for_tool(name, tags),
        capability_id=capability.get("capability") or name,
        capability_aliases=capability.get("aliases") or [],
        capability_priority=int(capability.get("priority") or 100),
        annotations={
            "readOnlyHint": name not in WRITE_TOOLS,
            "destructiveHint": ".delete" in name or name.endswith(".clear"),
            "idempotentHint": name not in WRITE_TOOLS,
            "capability": {
                "id": capability.get("capability") or name,
                "aliases": capability.get("aliases") or [],
                "priority": int(capability.get("priority") or 100),
            },
        },
        read_only=name not in WRITE_TOOLS,
        write=name in WRITE_TOOLS,
        destructive=".delete" in name or name.endswith(".clear"),
    )
    registry.register(spec, lambda args: handler(args, runtime_services))
    return 1


def try_register_vika_tools(registry: ToolRegistry, services: Optional[RuntimeServices] = None) -> int:
    global _CLIENT
    cfg = load_config()
    ttl_hours = getattr(cfg.cache, "ttl_hours", None) or getattr(cfg.vika, "cache_duration_hours", 24)
    cache = CatalogCache(db_path=cfg.cache.db_path, ttl_hours=ttl_hours, enabled=cfg.cache.enabled)
    _CLIENT = VikaClient(
        api_token=cfg.vika.api_token,
        host=cfg.vika.host,
        default_space_id=cfg.vika.default_space_id,
        workbench_space_id=getattr(cfg.vika, "workbench_space_id", None),
        cache=cache,
    )
    runtime_services = services or RuntimeServices()

    def register(
        name: str,
        description: str,
        handler: Callable[[Dict[str, Any], RuntimeServices], Any],
        properties: Dict[str, Any],
        required: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        available: Optional[bool] = None,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> int:
        return _register(
            registry,
            name,
            description,
            handler,
            properties,
            required,
            tags,
            available,
            output_schema,
            services=runtime_services,
        )

    registered = 0
    str_prop = {"type": "string"}
    bool_prop = {"type": "boolean"}
    int_prop = {"type": "integer", "minimum": 1}
    export_max_records_prop = {"type": "integer", "minimum": 1, "maximum": 100000}
    fields_prop = {"type": "array", "items": {"type": "string"}}
    sort_prop = {"type": "array", "items": {"type": "object"}}
    field_key_prop = {"type": "string", "enum": ["name", "id"]}

    registered += register("vika.status", "返回 MCP 的 Vika 配置状态，不做真实网络请求。", vika_status, {}, available=True)
    registered += register("vika.healthcheck", "真实请求 Vika API，检查配置和网络/API 可达性。", vika_healthcheck, {}, available=True)
    registered += register("vika.spaces.list", "列出可访问空间，支持缓存。", vika_spaces_list, {"use_cache": bool_prop, "force_refresh": bool_prop})
    registered += register(
        "vika.nodes.list",
        "列出指定空间站节点，支持缓存；cache_only=true 时缓存缺失或过期会返回 catalog 状态错误，不回退 API。",
        vika_nodes_list,
        {"space_id": str_prop, "use_cache": bool_prop, "force_refresh": bool_prop, "cache_only": bool_prop},
        ["space_id"],
        ["vika", "nodes"],
    )
    registered += register("vika.nodes.search", "按名称、类型或权限搜索节点，优先使用缓存。", vika_nodes_search, {"space_id": str_prop, "query": str_prop, "node_type": str_prop, "permissions": {"type": ["integer", "string", "array"]}, "use_cache": bool_prop, "force_refresh": bool_prop, "limit": int_prop}, ["space_id"], ["vika", "nodes"])
    registered += register("vika.nodes.tree", "返回指定空间的文件夹/节点树。", vika_nodes_tree, {"space_id": str_prop, "use_cache": bool_prop, "force_refresh": bool_prop}, ["space_id"], ["vika", "nodes"])
    registered += register("vika.nodes.get", "获取指定节点详情。", vika_nodes_get, {"space_id": str_prop, "node_id": str_prop, "use_cache": bool_prop}, ["space_id", "node_id"], ["vika", "nodes"])
    registered += register("vika.nodes.embedlinks.list", "列出节点嵌入链接。", vika_nodes_embedlinks_list, {"space_id": str_prop, "node_id": str_prop}, ["space_id", "node_id"], ["vika", "nodes"])
    registered += register("vika.nodes.embedlinks.create", "创建节点嵌入链接 preview，不直接执行；执行必须走 vika.write.commit。", vika_nodes_embedlinks_create, _with_safety({"space_id": str_prop, "node_id": str_prop, "theme": str_prop, "payload": {"type": "object"}}), ["space_id", "node_id"], ["vika", "nodes"])
    registered += register("vika.nodes.embedlinks.delete", "删除节点嵌入链接 preview，不直接执行；执行必须走 vika.write.commit。", vika_nodes_embedlinks_delete, _with_safety({"space_id": str_prop, "node_id": str_prop, "link_id": str_prop}), ["space_id", "node_id", "link_id"], ["vika", "nodes"])

    registered += register("vika.catalog.refresh", "刷新 SQLite catalog 缓存，可选拉取字段和视图。", vika_catalog_refresh, {"space_id": str_prop, "include_fields": bool_prop, "include_views": bool_prop, "force": bool_prop}, tags=["vika", "catalog"])
    registered += register("vika.catalog.status", "返回 catalog 维护诊断状态，并单独给出 ready_for_discovery/discovery_status；模型发现以 discovery readiness 为准。", vika_catalog_status, {}, tags=["vika", "catalog"])
    registered += register(
        "vika.catalog.search",
        "确定性检索缓存中的表格/节点候选；只在统一 selector readiness gate 为 ready 时返回 matches，namespace 检索遇到任一 scoped refresh 非 ready 会返回 catalog error。",
        vika_catalog_search,
        {"query": str_prop, "space_id": str_prop, "node_type": str_prop, "limit": int_prop},
        ["query"],
        ["vika", "catalog"],
    )
    registered += register(
        "vika.catalog.get",
        "按缓存 item_type 和 item_id 获取 catalog 项；只在统一 selector readiness gate 为 ready 时返回 item，field/view 使用 datasheet selector 校验。",
        vika_catalog_get,
        {"item_type": {"type": "string", "enum": ["space", "node", "datasheet", "field", "view"]}, "item_id": str_prop},
        ["item_type", "item_id"],
        ["vika", "catalog"],
    )
    registered += register("vika.catalog.clear", "清理当前 token namespace 的 catalog 缓存。", vika_catalog_clear, {"space_id": str_prop}, tags=["vika", "catalog"])
    registered += register("vika.schema.get", "获取数据表字段和视图 schema，优先读缓存。", vika_schema_get, {"datasheet_id": str_prop, "space_id": str_prop, "use_cache": bool_prop, "force_refresh": bool_prop}, ["datasheet_id"], ["vika", "schema"])

    registered += register("vika.records.query", "分页查询记录，返回 records/has_more/next_offset/total。", vika_records_query, {"datasheet_id": str_prop, "view_id": str_prop, "formula": str_prop, "fields": fields_prop, "page_size": int_prop, "page_num": int_prop, "page_token": str_prop, "sort": sort_prop, "field_key": field_key_prop}, ["datasheet_id"], ["vika", "records"])
    registered += register("vika.records.read_all", "批量读取多页记录；必须提供 max_records 或 max_pages。", vika_records_read_all, {"datasheet_id": str_prop, "view_id": str_prop, "formula": str_prop, "fields": fields_prop, "page_size": int_prop, "max_records": int_prop, "max_pages": int_prop, "sort": sort_prop, "field_key": field_key_prop}, ["datasheet_id"], ["vika", "records"])
    registered += register(
        "vika_export_records",
        "导出有界记录到服务端 CSV artifact，返回 artifact_id、manifest 和后续 artifact_search/read 操作。必须提供 max_records，硬上限 100000；format 缺省为 csv，可显式选择 jsonl。",
        vika_export_records,
        {
            "datasheet_id": str_prop,
            "view_id": str_prop,
            "formula": str_prop,
            "fields": fields_prop,
            "page_size": int_prop,
            "max_records": export_max_records_prop,
            "max_pages": int_prop,
            "sort": sort_prop,
            "field_key": field_key_prop,
            "format": {"type": "string", "enum": ["csv", "jsonl"]},
        },
        ["datasheet_id", "max_records"],
        ["vika", "records", "export"],
    )
    registered += register("vika.records.create", "创建记录 preview，不直接执行；根据 confirmation_context/brief 向用户一句话确认后，用 payload hash 调用 vika.write.commit。", vika_records_create, _with_safety({"datasheet_id": str_prop, "records": {"type": ["array", "object"], "items": {"type": "object"}}, "field_key": field_key_prop}), ["datasheet_id", "records"], ["vika", "records"])
    registered += register("vika.records.update", "更新记录 preview，不直接执行；根据 confirmation_context/brief 向用户一句话确认后，用 payload hash 调用 vika.write.commit。", vika_records_update, _with_safety({"datasheet_id": str_prop, "records": {"type": ["array", "object"], "items": {"type": "object"}}, "field_key": field_key_prop}), ["datasheet_id", "records"], ["vika", "records"])
    registered += register("vika.records.delete", "删除记录 preview，不直接执行；根据 confirmation_context/brief 向用户一句话确认后，用 payload hash 调用 vika.write.commit。", vika_records_delete, _with_safety({"datasheet_id": str_prop, "record_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}}), ["datasheet_id", "record_ids"], ["vika", "records"])
    registered += register("vika.write.commit", "提交已由 preview 生成并经用户确认的一次写入计划。必须提供 operation_id、confirmed_payload_hash 和 confirmed_by_user=true；user_confirmation_summary 仅用于审计。", vika_write_commit, {"operation_id": str_prop, "confirmed_payload_hash": str_prop, "confirmed_by_user": bool_prop, "user_confirmation_summary": str_prop}, ["operation_id", "confirmed_payload_hash", "confirmed_by_user"], ["vika", "write"])
    registered += register("vika.records.get", "按记录 ID 批量获取记录。", vika_records_get, {"datasheet_id": str_prop, "record_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}, "fields": fields_prop, "field_key": field_key_prop}, ["datasheet_id", "record_ids"], ["vika", "records"])

    registered += register("vika.fields.get", "按 ID 或名称获取字段。", vika_fields_get, {"datasheet_id": str_prop, "field_id_or_name": str_prop}, ["datasheet_id", "field_id_or_name"], ["vika", "fields"])
    registered += register("vika.fields.create", "创建字段 preview，不直接执行；执行必须走 vika.write.commit。", vika_fields_create, _with_safety({"datasheet_id": str_prop, "space_id": str_prop, "name": str_prop, "field_type": str_prop, "property": {"type": "object"}}), ["datasheet_id", "space_id", "name", "field_type"], ["vika", "fields"])
    registered += register("vika.fields.delete", "删除字段 preview，不直接执行；执行必须走 vika.write.commit。", vika_fields_delete, _with_safety({"datasheet_id": str_prop, "space_id": str_prop, "field_id_or_name": str_prop}), ["datasheet_id", "space_id", "field_id_or_name"], ["vika", "fields"])
    registered += register("vika.views.get", "按 ID 或名称获取视图。", vika_views_get, {"datasheet_id": str_prop, "view_id_or_name": str_prop}, ["datasheet_id", "view_id_or_name"], ["vika", "views"])
    registered += register("vika.attachments.upload", "上传附件 preview，不直接执行；执行必须走 vika.write.commit。", vika_attachments_upload, _with_safety({"datasheet_id": str_prop, "file_path": str_prop}), ["datasheet_id", "file_path"], ["vika", "attachments"])
    registered += register(
        "vika.attachments.download",
        "按附件 URL 下载附件到本地。",
        vika_attachments_download,
        {"url": str_prop, "save_path": str_prop},
        ["url"],
        ["vika", "attachments"],
    )
    registered += register("vika.datasheets.create", "创建数据表 preview，不直接执行；执行必须走 vika.write.commit。", vika_datasheets_create, _with_safety({"space_id": str_prop, "name": str_prop, "description": str_prop, "folder_id": str_prop, "pre_filled_records": {"type": "array", "items": {"type": "object"}}}), ["space_id", "name", "folder_id"], ["vika", "datasheets"])
    return registered


__all__ = [
    "VikaClient",
    "try_register_vika_tools",
    "vika_status",
    "vika_healthcheck",
    "vika_records_query",
    "vika_records_create",
    "vika_records_update",
    "vika_records_delete",
]
