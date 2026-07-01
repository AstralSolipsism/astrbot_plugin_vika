from __future__ import annotations

import json
from typing import Any, Dict, Optional


DEFAULT_QUERY_PAGE_SIZE = 50
MAX_QUERY_PAGE_SIZE = 100
INLINE_MAX_CHARS = 20_000
MAX_EXPORT_RECOMMENDED_RECORDS = 100_000


def normalize_query_page_size(page_size: Optional[int]) -> int:
    if page_size is None:
        return DEFAULT_QUERY_PAGE_SIZE
    return min(max(int(page_size), 1), MAX_QUERY_PAGE_SIZE)


def enforce_inline_record_limit(result: Dict[str, Any], max_chars: int = INLINE_MAX_CHARS) -> Dict[str, Any]:
    normalized = dict(result)
    if "next_page_token" not in normalized and "next_offset" in normalized:
        normalized["next_page_token"] = normalized.get("next_offset")
    normalized.pop("next_offset", None)

    serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= max_chars:
        normalized["truncated"] = False
        normalized["inline_chars"] = len(serialized)
        return normalized

    records = normalized.pop("records", []) or []
    returned_record_count = len(records) if isinstance(records, list) else 1
    try:
        recommended_max_records = int(normalized.get("total")) if normalized.get("total") is not None else returned_record_count
    except (TypeError, ValueError):
        recommended_max_records = returned_record_count
    recommended_max_records = min(max(recommended_max_records, 1), MAX_EXPORT_RECOMMENDED_RECORDS)
    recommended_args = {
        key: normalized.get(key)
        for key in ("datasheet_id", "view_id", "fields", "formula")
        if normalized.get(key) is not None
    }
    recommended_args["max_records"] = recommended_max_records
    return {
        **normalized,
        "truncated": True,
        "inline_chars": len(serialized),
        "inline_max_chars": max_chars,
        "record_count": returned_record_count,
        "recommended_tool": "vika_export_records",
        "recommended_args": recommended_args,
        "message": "Inline result is too large; use vika_export_records and artifact search/read instead.",
    }
