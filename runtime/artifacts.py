from __future__ import annotations

import hashlib
import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ARTIFACT_HEAD_DEFAULT_LINES = 20
ARTIFACT_HEAD_MAX_LINES = 100
ARTIFACT_SEARCH_DEFAULT_HITS = 20
ARTIFACT_SEARCH_MAX_HITS = 100
ARTIFACT_SNIPPET_MAX_CHARS = 300
ARTIFACT_READ_DEFAULT_LINES = 100
ARTIFACT_READ_MAX_LINES = 500
ARTIFACT_READ_MAX_CHARS = 40_000
ARTIFACT_SUPPORTED_FORMATS = {"csv", "jsonl"}


class ArtifactStore:
    def __init__(self, root: Optional[Path | str] = None) -> None:
        self.root = Path(root or Path("artifacts") / "exports").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_records_export(
        self,
        datasheet_id: str,
        records: Iterable[Dict[str, Any]],
        field_names: Optional[List[str]] = None,
        source_args: Optional[Dict[str, Any]] = None,
        space_id: Optional[str] = None,
        view_id: Optional[str] = None,
        query: Optional[Dict[str, Any]] = None,
        format: str = "csv",
    ) -> Dict[str, Any]:
        if format not in ARTIFACT_SUPPORTED_FORMATS:
            raise ValueError(f"unsupported artifact format: {format}")

        artifact_id = f"exp_{uuid.uuid4().hex}"
        path = self._data_path(artifact_id, format)
        manifest_path = self._manifest_path(artifact_id)
        rows = list(records)
        columns = field_names or sorted({key for record in rows for key in (record.get("fields") or {}).keys()})

        if format == "csv":
            with path.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["record_id", *columns], extrasaction="ignore")
                writer.writeheader()
                for record in rows:
                    fields = record.get("fields") or {}
                    writer.writerow({"record_id": record.get("id"), **{column: fields.get(column) for column in columns}})
        else:
            with path.open("w", encoding="utf-8", newline="\n") as fh:
                for record in rows:
                    fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

        args_hash = hashlib.sha256(
            json.dumps(source_args or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifest = {
            "artifact_id": artifact_id,
            "datasheet_id": datasheet_id,
            "space_id": space_id,
            "view_id": view_id,
            "query": query or {},
            "field_names": columns,
            "record_count": len(rows),
            "format": format,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_tool_args_hash": args_hash,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            **manifest,
            "path": str(path),
            "manifest_path": str(manifest_path),
            "content_inline": False,
            "next_actions": ["vika_artifact_head", "vika_artifact_search", "vika_artifact_read"],
        }

    def head(self, artifact_id: str, lines: int = ARTIFACT_HEAD_DEFAULT_LINES) -> Dict[str, Any]:
        line_limit = min(max(int(lines or ARTIFACT_HEAD_DEFAULT_LINES), 1), ARTIFACT_HEAD_MAX_LINES)
        return self.read(artifact_id, start_line=1, lines=line_limit, max_chars=ARTIFACT_READ_MAX_CHARS, reported_max_lines=ARTIFACT_HEAD_MAX_LINES)

    def search(self, artifact_id: str, query: str, max_hits: int = ARTIFACT_SEARCH_DEFAULT_HITS) -> Dict[str, Any]:
        hit_limit = min(max(int(max_hits or ARTIFACT_SEARCH_DEFAULT_HITS), 1), ARTIFACT_SEARCH_MAX_HITS)
        path = self._existing_data_path(artifact_id)
        hits: List[Dict[str, Any]] = []
        query_text = query or ""
        with path.open("r", encoding="utf-8-sig") as fh:
            for index, line in enumerate(fh, start=1):
                if query_text in line:
                    snippet = line.strip()
                    if len(snippet) > ARTIFACT_SNIPPET_MAX_CHARS:
                        snippet = snippet[:ARTIFACT_SNIPPET_MAX_CHARS]
                    hits.append({"line_number": index, "snippet": snippet})
                    if len(hits) >= hit_limit:
                        break
        return {
            "artifact_id": artifact_id,
            "query": query,
            "hits": hits,
            "max_hits": ARTIFACT_SEARCH_MAX_HITS,
            "snippet_max_chars": ARTIFACT_SNIPPET_MAX_CHARS,
        }

    def read(
        self,
        artifact_id: str,
        start_line: int = 1,
        lines: int = ARTIFACT_READ_DEFAULT_LINES,
        max_chars: int = ARTIFACT_READ_MAX_CHARS,
        reported_max_lines: int = ARTIFACT_READ_MAX_LINES,
    ) -> Dict[str, Any]:
        path = self._existing_data_path(artifact_id)
        start = max(int(start_line or 1), 1)
        line_limit = min(max(int(lines or ARTIFACT_READ_DEFAULT_LINES), 1), ARTIFACT_READ_MAX_LINES)
        char_limit = min(max(int(max_chars or ARTIFACT_READ_MAX_CHARS), 1), ARTIFACT_READ_MAX_CHARS)
        rows: List[str] = []
        total_chars = 0
        truncated_by_chars = False

        with path.open("r", encoding="utf-8-sig") as fh:
            for index, line in enumerate(fh, start=1):
                if index < start:
                    continue
                if len(rows) >= line_limit:
                    break
                next_chars = total_chars + len(line)
                if next_chars > char_limit:
                    truncated_by_chars = True
                    break
                rows.append(line.rstrip("\n"))
                total_chars = next_chars

        return {
            "artifact_id": artifact_id,
            "start_line": start,
            "requested_lines": lines,
            "returned_lines": len(rows),
            "max_lines": reported_max_lines,
            "max_chars": char_limit,
            "truncated_by_chars": truncated_by_chars,
            "lines": rows,
        }

    def status(self, artifact_id: str) -> Dict[str, Any]:
        manifest_path = self._existing_manifest_path(artifact_id)
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _data_path(self, artifact_id: str, format: str) -> Path:
        self._validate_artifact_id(artifact_id)
        if format not in ARTIFACT_SUPPORTED_FORMATS:
            raise ValueError(f"unsupported artifact format: {format}")
        path = (self.root / f"{artifact_id}.{format}").resolve()
        self._ensure_inside_root(path)
        return path

    def _manifest_path(self, artifact_id: str) -> Path:
        self._validate_artifact_id(artifact_id)
        path = (self.root / f"{artifact_id}.manifest.json").resolve()
        self._ensure_inside_root(path)
        return path

    def _existing_data_path(self, artifact_id: str) -> Path:
        manifest = self.status(artifact_id)
        fmt = manifest.get("format") or "csv"
        path = self._data_path(artifact_id, fmt)
        if not path.is_file():
            raise ValueError(f"artifact not found: {artifact_id}")
        return path

    def _existing_manifest_path(self, artifact_id: str) -> Path:
        path = self._manifest_path(artifact_id)
        if not path.is_file():
            raise ValueError(f"artifact manifest not found: {artifact_id}")
        return path

    def _ensure_inside_root(self, path: Path) -> None:
        if path != self.root and self.root not in path.parents:
            raise ValueError("artifact path escapes exports root")

    def _validate_artifact_id(self, artifact_id: str) -> None:
        if not artifact_id or not all(ch.isalnum() or ch in {"_", "-"} for ch in artifact_id):
            raise ValueError(f"invalid artifact id: {artifact_id}")
