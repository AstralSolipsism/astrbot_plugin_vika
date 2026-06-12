import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, Union

from ..cache import CatalogCache
from ..config import load_config
from ..mcp.registry import ToolRegistry
from ..mcp.types import ToolSpec
from ..mcp.validation import ToolInputInvalid, validate_arguments

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
    "records.create",
    "records.update",
    "records.delete",
    "fields.create",
    "fields.delete",
    "datasheets.create",
    "attachments.upload",
    "nodes.embedlinks.create",
    "nodes.embedlinks.delete",
}


class VikaClient:
    def __init__(
        self,
        api_token: Optional[str],
        host: Optional[str] = None,
        default_space_id: Optional[str] = None,
        cache: Optional[CatalogCache] = None,
    ) -> None:
        self.api_token = api_token
        self.host = (host or DEFAULT_API_BASE or "https://vika.cn").rstrip("/")
        self.default_space_id = default_space_id
        self.cache = cache

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

    async def _load_catalog_nodes_from_api(self, vika: Any, space_id: str) -> List[Dict[str, Any]]:
        space = vika.space(space_id)
        merged: Dict[str, Dict[str, Any]] = {}

        async def add_nodes(nodes: List[Any]) -> None:
            for node in nodes:
                raw = node.raw_data if hasattr(node, "raw_data") else node
                node_id = raw.get("id") if isinstance(raw, dict) else None
                if node_id:
                    merged[node_id] = raw

        try:
            await add_nodes(await space.nodes.alist())
        except Exception:
            pass

        for node_type in ("Folder", "Datasheet", "Form", "Dashboard"):
            try:
                await add_nodes(await space.nodes.asearch(node_type=node_type))
            except Exception:
                continue

        return list(merged.values())

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

    async def nodes_list(self, space_id: str, use_cache: bool = True, force_refresh: bool = False) -> Dict[str, Any]:
        if self.cache and use_cache and not force_refresh:
            try:
                cached = self.cache.list_items(self.namespace, "node", space_id=space_id, max_age_seconds=self._cache_max_age())
                if cached:
                    return {"nodes": cached, "source": "cache"}
            except Exception:
                pass
        vika = None
        try:
            vika = self._ensure_client()
            raw_nodes = await self._load_catalog_nodes_from_api(vika, space_id)
            items = self._make_node_items(space_id, raw_nodes)
            if self.cache:
                try:
                    self.cache.replace_items(self.namespace, space_id, "node", [item for item in items if item["type"] == "node"])
                    self.cache.replace_items(self.namespace, space_id, "datasheet", [item for item in items if item["type"] == "datasheet"])
                except Exception:
                    pass
            return {"nodes": items, "source": "api"}
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
                await self.nodes_list(space_id, use_cache=False, force_refresh=True)
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

    async def catalog_refresh(self, space_id: Optional[str] = None, include_fields: bool = False, include_views: bool = False, force: bool = False) -> Dict[str, Any]:
        spaces_result = await self.spaces_list(use_cache=not force, force_refresh=force)
        if "error" in spaces_result:
            return spaces_result
        spaces = spaces_result.get("spaces", [])
        target_space_ids = [space_id] if space_id else [space.get("id") for space in spaces if space.get("id")]
        counts = {"spaces": len(spaces), "nodes": 0, "datasheets": 0, "fields": 0, "views": 0}
        for sid in target_space_ids:
            nodes_result = await self.nodes_list(sid, use_cache=False, force_refresh=True)
            if "error" in nodes_result:
                return nodes_result
            nodes = nodes_result.get("nodes", [])
            counts["nodes"] += len([item for item in nodes if item.get("type") == "node"])
            datasheets = [item for item in nodes if item.get("type") == "datasheet" and item.get("dst_id")]
            counts["datasheets"] += len(datasheets)
            if include_fields or include_views:
                for ds_item in datasheets:
                    schema = await self.schema_get(ds_item["dst_id"], space_id=sid, use_cache=False, force_refresh=True)
                    if "error" not in schema:
                        counts["fields"] += len(schema.get("fields", [])) if include_fields else 0
                        counts["views"] += len(schema.get("views", [])) if include_views else 0
        return {"refreshed": True, "space_ids": target_space_ids, "counts": counts, "cache": self.catalog_status()}

    def catalog_status(self) -> Dict[str, Any]:
        if not self.cache:
            return {"enabled": False}
        return self.cache.status(self.namespace)

    def catalog_search(self, query: str, space_id: Optional[str] = None, node_type: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        if not self.cache:
            return {"matches": [], "source": "disabled"}
        try:
            return {"matches": self.cache.search(self.namespace, query, space_id=space_id, node_type=node_type, limit=limit), "source": "cache"}
        except Exception as exc:
            return self._wrap_error(exc)

    def catalog_get(self, item_type: str, item_id: str) -> Dict[str, Any]:
        if not self.cache:
            return {"item": None, "source": "disabled"}
        try:
            return {"item": self.cache.get_item(self.namespace, item_type, item_id), "source": "cache"}
        except Exception as exc:
            return self._wrap_error(exc)

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


def _preview(operation: str, target: Dict[str, Any], payload: Any) -> Dict[str, Any]:
    return {
        "executed": False,
        "preview_only": True,
        "requires_confirmation": True,
        "confirmation_fields": {"dry_run": False, "confirm": True},
        "operation": operation,
        "target": target,
        "payload_preview": payload,
        "message": "Preview only. No Vika write operation was executed.",
    }


async def _execute(operation: str, call: Any) -> Dict[str, Any]:
    result = _raise_if_error(await call)
    return {
        "executed": True,
        "preview_only": False,
        "requires_confirmation": False,
        "operation": operation,
        "result": result,
    }


def _should_execute(args: Dict[str, Any]) -> bool:
    return args.get("dry_run") is False and args.get("confirm") is True


async def vika_status(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.status())


async def vika_healthcheck(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return await _CLIENT.healthcheck()


async def vika_spaces_list(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.spaces_list(args.get("use_cache", True), args.get("force_refresh", False)))


async def vika_nodes_list(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.nodes_list(args["space_id"], args.get("use_cache", True), args.get("force_refresh", False)))


async def vika_nodes_search(args: Dict[str, Any]) -> Any:
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


async def vika_nodes_tree(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.nodes_tree(args["space_id"], args.get("use_cache", True), args.get("force_refresh", False)))


async def vika_nodes_get(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.nodes_get(args["space_id"], args["node_id"], args.get("use_cache", True)))


async def vika_nodes_embedlinks_list(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.embedlinks_list(args["space_id"], args["node_id"]))


async def vika_nodes_embedlinks_create(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    payload = {"theme": args.get("theme"), "payload": args.get("payload")}
    if not _should_execute(args):
        return _preview("nodes.embedlinks.create", {"space_id": args["space_id"], "node_id": args["node_id"]}, payload)
    return await _execute("nodes.embedlinks.create", _CLIENT.embedlinks_create(args["space_id"], args["node_id"], args.get("theme"), args.get("payload")))


async def vika_nodes_embedlinks_delete(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    if not _should_execute(args):
        return _preview("nodes.embedlinks.delete", {"space_id": args["space_id"], "node_id": args["node_id"], "link_id": args["link_id"]}, {})
    return await _execute("nodes.embedlinks.delete", _CLIENT.embedlinks_delete(args["space_id"], args["node_id"], args["link_id"]))


async def vika_catalog_refresh(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.catalog_refresh(args.get("space_id"), args.get("include_fields", False), args.get("include_views", False), args.get("force", False)))


async def vika_catalog_status(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _CLIENT.catalog_status()


async def vika_catalog_search(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _CLIENT.catalog_search(args.get("query", ""), args.get("space_id"), args.get("node_type"), args.get("limit", 20))


async def vika_catalog_get(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _CLIENT.catalog_get(args["item_type"], args["item_id"])


async def vika_catalog_clear(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _CLIENT.catalog_clear(args.get("space_id"))


async def vika_schema_get(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.schema_get(args["datasheet_id"], args.get("space_id"), args.get("use_cache", True), args.get("force_refresh", False)))


async def vika_records_query(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.records_query(args["datasheet_id"], args.get("view_id"), args.get("formula"), args.get("fields"), args.get("page_size"), args.get("page_num"), args.get("page_token"), args.get("sort"), args.get("field_key")))


async def vika_records_read_all(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.records_read_all(args["datasheet_id"], args.get("view_id"), args.get("formula"), args.get("fields"), args.get("page_size", 100), args.get("max_records"), args.get("max_pages"), args.get("sort"), args.get("field_key")))


async def vika_records_create(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    payload = {"records": args["records"], "field_key": args.get("field_key")}
    if not _should_execute(args):
        return _preview("records.create", {"datasheet_id": args["datasheet_id"]}, payload)
    return await _execute("records.create", _CLIENT.records_create(args["datasheet_id"], args["records"], args.get("field_key")))


async def vika_records_update(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    payload = {"records": args["records"], "field_key": args.get("field_key")}
    if not _should_execute(args):
        return _preview("records.update", {"datasheet_id": args["datasheet_id"]}, payload)
    return await _execute("records.update", _CLIENT.records_update(args["datasheet_id"], args["records"], args.get("field_key")))


async def vika_records_delete(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    if not _should_execute(args):
        return _preview("records.delete", {"datasheet_id": args["datasheet_id"], "record_ids": args["record_ids"]}, {})
    return await _execute("records.delete", _CLIENT.records_delete(args["datasheet_id"], args["record_ids"]))


async def vika_records_get(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.records_get(args["datasheet_id"], args["record_ids"], args.get("fields"), args.get("field_key")))


async def vika_fields_get(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.fields_get(args["datasheet_id"], args["field_id_or_name"]))


async def vika_fields_create(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    payload = {"name": args["name"], "field_type": args["field_type"], "property": args.get("property")}
    if not _should_execute(args):
        return _preview("fields.create", {"datasheet_id": args["datasheet_id"], "space_id": args["space_id"]}, payload)
    return await _execute("fields.create", _CLIENT.fields_create(args["datasheet_id"], args["space_id"], args["name"], args["field_type"], args.get("property")))


async def vika_fields_delete(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    if not _should_execute(args):
        return _preview("fields.delete", {"datasheet_id": args["datasheet_id"], "space_id": args["space_id"], "field_id_or_name": args["field_id_or_name"]}, {})
    return await _execute("fields.delete", _CLIENT.fields_delete(args["datasheet_id"], args["space_id"], args["field_id_or_name"]))


async def vika_views_get(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.views_get(args["datasheet_id"], args["view_id_or_name"]))


async def vika_attachments_upload(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    if not _should_execute(args):
        return _preview("attachments.upload", {"datasheet_id": args["datasheet_id"]}, {"file_path": args["file_path"]})
    return await _execute("attachments.upload", _CLIENT.attachments_upload(args["datasheet_id"], args["file_path"]))


async def vika_attachments_download(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.attachments_download(args.get("url"), args.get("attachment"), args.get("save_path")))


async def vika_datasheets_create(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    payload = {key: args.get(key) for key in ("name", "description", "folder_id", "pre_filled_records") if key in args}
    if not _should_execute(args):
        return _preview("datasheets.create", {"space_id": args["space_id"]}, payload)
    return await _execute("datasheets.create", _CLIENT.datasheets_create(args["space_id"], args["name"], args.get("description"), args.get("folder_id"), args.get("pre_filled_records")))


def _schema(properties: Dict[str, Any], required: Optional[List[str]] = None, additional: bool = False) -> Dict[str, Any]:
    return {"type": "object", "required": required or [], "properties": properties, "additionalProperties": additional}


def _with_safety(properties: Dict[str, Any]) -> Dict[str, Any]:
    props = dict(properties)
    props["dry_run"] = {
        "type": "boolean",
        "description": "默认 true，仅返回 preview_only 预览且不执行；必须为 false 才可能真实执行",
    }
    props["confirm"] = {
        "type": "boolean",
        "description": "调用方声明已完成上层确认；只有 dry_run=false 且 confirm=true 才真实执行",
    }
    return props


def _register(
    registry: ToolRegistry,
    name: str,
    description: str,
    handler: Callable[[Dict[str, Any]], Any],
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    available: Optional[bool] = None,
    output_schema: Optional[Dict[str, Any]] = None,
) -> int:
    assert _CLIENT is not None
    spec = ToolSpec(
        name=name,
        description=description,
        input_schema=_schema(properties, required),
        output_schema=output_schema or {"type": "object", "additionalProperties": True},
        examples=[{"arguments": {key: f"{key}_value" for key in (required or [])}}],
        available=_CLIENT.configured if available is None else available,
        unavailable_reason=None if (available is True or _CLIENT.configured) else "astral_vika not configured",
        tags=tags or ["vika"],
    )
    registry.register(spec, handler)
    return 1


def try_register_vika_tools(registry: ToolRegistry) -> int:
    global _CLIENT
    cfg = load_config()
    ttl_hours = getattr(cfg.cache, "ttl_hours", None) or getattr(cfg.vika, "cache_duration_hours", 24)
    cache = CatalogCache(db_path=cfg.cache.db_path, ttl_hours=ttl_hours, enabled=cfg.cache.enabled)
    _CLIENT = VikaClient(api_token=cfg.vika.api_token, host=cfg.vika.host, default_space_id=cfg.vika.default_space_id, cache=cache)

    registered = 0
    str_prop = {"type": "string"}
    bool_prop = {"type": "boolean"}
    int_prop = {"type": "integer", "minimum": 1}
    fields_prop = {"type": "array", "items": {"type": "string"}}
    sort_prop = {"type": "array", "items": {"type": "object"}}
    field_key_prop = {"type": "string", "enum": ["name", "id"]}

    registered += _register(registry, "vika.status", "返回 MCP 的 Vika 配置状态，不做真实网络请求。", vika_status, {}, available=True)
    registered += _register(registry, "vika.healthcheck", "真实请求 Vika API，检查配置和网络/API 可达性。", vika_healthcheck, {}, available=True)
    registered += _register(registry, "vika.spaces.list", "列出可访问空间，支持缓存。", vika_spaces_list, {"use_cache": bool_prop, "force_refresh": bool_prop})
    registered += _register(registry, "vika.nodes.list", "列出指定空间站节点，支持缓存。", vika_nodes_list, {"space_id": str_prop, "use_cache": bool_prop, "force_refresh": bool_prop}, ["space_id"], ["vika", "nodes"])
    registered += _register(registry, "vika.nodes.search", "按名称、类型或权限搜索节点，优先使用缓存。", vika_nodes_search, {"space_id": str_prop, "query": str_prop, "node_type": str_prop, "permissions": {"type": ["integer", "string", "array"]}, "use_cache": bool_prop, "force_refresh": bool_prop, "limit": int_prop}, ["space_id"], ["vika", "nodes"])
    registered += _register(registry, "vika.nodes.tree", "返回指定空间的文件夹/节点树。", vika_nodes_tree, {"space_id": str_prop, "use_cache": bool_prop, "force_refresh": bool_prop}, ["space_id"], ["vika", "nodes"])
    registered += _register(registry, "vika.nodes.get", "获取指定节点详情。", vika_nodes_get, {"space_id": str_prop, "node_id": str_prop, "use_cache": bool_prop}, ["space_id", "node_id"], ["vika", "nodes"])
    registered += _register(registry, "vika.nodes.embedlinks.list", "列出节点嵌入链接。", vika_nodes_embedlinks_list, {"space_id": str_prop, "node_id": str_prop}, ["space_id", "node_id"], ["vika", "nodes"])
    registered += _register(registry, "vika.nodes.embedlinks.create", "创建节点嵌入链接，默认 dry-run。", vika_nodes_embedlinks_create, _with_safety({"space_id": str_prop, "node_id": str_prop, "theme": str_prop, "payload": {"type": "object"}}), ["space_id", "node_id"], ["vika", "nodes"])
    registered += _register(registry, "vika.nodes.embedlinks.delete", "删除节点嵌入链接，默认 dry-run。", vika_nodes_embedlinks_delete, _with_safety({"space_id": str_prop, "node_id": str_prop, "link_id": str_prop}), ["space_id", "node_id", "link_id"], ["vika", "nodes"])

    registered += _register(registry, "vika.catalog.refresh", "刷新 SQLite catalog 缓存，可选拉取字段和视图。", vika_catalog_refresh, {"space_id": str_prop, "include_fields": bool_prop, "include_views": bool_prop, "force": bool_prop}, tags=["vika", "catalog"])
    registered += _register(registry, "vika.catalog.status", "返回 catalog 缓存状态。", vika_catalog_status, {}, tags=["vika", "catalog"])
    registered += _register(registry, "vika.catalog.search", "确定性检索缓存中的表格/节点候选。", vika_catalog_search, {"query": str_prop, "space_id": str_prop, "node_type": str_prop, "limit": int_prop}, ["query"], ["vika", "catalog"])
    registered += _register(registry, "vika.catalog.get", "按缓存 item_type 和 item_id 获取 catalog 项。", vika_catalog_get, {"item_type": {"type": "string", "enum": ["space", "node", "datasheet", "field", "view"]}, "item_id": str_prop}, ["item_type", "item_id"], ["vika", "catalog"])
    registered += _register(registry, "vika.catalog.clear", "清理当前 token namespace 的 catalog 缓存。", vika_catalog_clear, {"space_id": str_prop}, tags=["vika", "catalog"])
    registered += _register(registry, "vika.schema.get", "获取数据表字段和视图 schema，优先读缓存。", vika_schema_get, {"datasheet_id": str_prop, "space_id": str_prop, "use_cache": bool_prop, "force_refresh": bool_prop}, ["datasheet_id"], ["vika", "schema"])

    registered += _register(registry, "vika.records.query", "分页查询记录，返回 records/has_more/next_offset/total。", vika_records_query, {"datasheet_id": str_prop, "view_id": str_prop, "formula": str_prop, "fields": fields_prop, "page_size": int_prop, "page_num": int_prop, "page_token": str_prop, "sort": sort_prop, "field_key": field_key_prop}, ["datasheet_id"], ["vika", "records"])
    registered += _register(registry, "vika.records.read_all", "批量读取多页记录；必须提供 max_records 或 max_pages。", vika_records_read_all, {"datasheet_id": str_prop, "view_id": str_prop, "formula": str_prop, "fields": fields_prop, "page_size": int_prop, "max_records": int_prop, "max_pages": int_prop, "sort": sort_prop, "field_key": field_key_prop}, ["datasheet_id"], ["vika", "records"])
    registered += _register(registry, "vika.records.create", "创建记录，默认 dry-run。", vika_records_create, _with_safety({"datasheet_id": str_prop, "records": {"type": ["array", "object"], "items": {"type": "object"}}, "field_key": field_key_prop}), ["datasheet_id", "records"], ["vika", "records"])
    registered += _register(registry, "vika.records.update", "更新记录，默认 dry-run。", vika_records_update, _with_safety({"datasheet_id": str_prop, "records": {"type": ["array", "object"], "items": {"type": "object"}}, "field_key": field_key_prop}), ["datasheet_id", "records"], ["vika", "records"])
    registered += _register(registry, "vika.records.delete", "删除记录，默认 dry-run。", vika_records_delete, _with_safety({"datasheet_id": str_prop, "record_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}}), ["datasheet_id", "record_ids"], ["vika", "records"])
    registered += _register(registry, "vika.records.get", "按记录 ID 批量获取记录。", vika_records_get, {"datasheet_id": str_prop, "record_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}, "fields": fields_prop, "field_key": field_key_prop}, ["datasheet_id", "record_ids"], ["vika", "records"])

    registered += _register(registry, "vika.fields.get", "按 ID 或名称获取字段。", vika_fields_get, {"datasheet_id": str_prop, "field_id_or_name": str_prop}, ["datasheet_id", "field_id_or_name"], ["vika", "fields"])
    registered += _register(registry, "vika.fields.create", "创建字段，默认 dry-run。", vika_fields_create, _with_safety({"datasheet_id": str_prop, "space_id": str_prop, "name": str_prop, "field_type": str_prop, "property": {"type": "object"}}), ["datasheet_id", "space_id", "name", "field_type"], ["vika", "fields"])
    registered += _register(registry, "vika.fields.delete", "删除字段，默认 dry-run。", vika_fields_delete, _with_safety({"datasheet_id": str_prop, "space_id": str_prop, "field_id_or_name": str_prop}), ["datasheet_id", "space_id", "field_id_or_name"], ["vika", "fields"])
    registered += _register(registry, "vika.views.get", "按 ID 或名称获取视图。", vika_views_get, {"datasheet_id": str_prop, "view_id_or_name": str_prop}, ["datasheet_id", "view_id_or_name"], ["vika", "views"])
    registered += _register(registry, "vika.attachments.upload", "上传附件，默认 dry-run。", vika_attachments_upload, _with_safety({"datasheet_id": str_prop, "file_path": str_prop}), ["datasheet_id", "file_path"], ["vika", "attachments"])
    registered += _register(registry, "vika.attachments.download", "下载附件到本地。", vika_attachments_download, {"url": str_prop, "attachment": {"type": "object"}, "save_path": str_prop}, tags=["vika", "attachments"])
    registered += _register(registry, "vika.datasheets.create", "创建数据表，默认 dry-run。", vika_datasheets_create, _with_safety({"space_id": str_prop, "name": str_prop, "description": str_prop, "folder_id": str_prop, "pre_filled_records": {"type": "array", "items": {"type": "object"}}}), ["space_id", "name"], ["vika", "datasheets"])
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
