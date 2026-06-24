from __future__ import annotations

from pathlib import Path

import pytest


def test_query_limits_clamp_page_size_and_remove_oversized_records() -> None:
    from vika_mcp.runtime.limits import enforce_inline_record_limit, normalize_query_page_size

    assert normalize_query_page_size(None) == 50
    assert normalize_query_page_size(1000) == 100
    assert normalize_query_page_size(0) == 1

    records = [{"id": str(i), "fields": {"value": "x" * 200}} for i in range(20)]
    result = enforce_inline_record_limit(
        {"records": records, "has_more": False, "next_page_token": None, "total": 20},
        max_chars=500,
    )

    assert "records" not in result
    assert result["truncated"] is True
    assert result["recommended_tool"] == "vika_export_records"
    assert result["record_count"] == 20


def test_inline_overflow_recommends_executable_csv_export_args() -> None:
    from vika_mcp.runtime.limits import enforce_inline_record_limit

    result = enforce_inline_record_limit(
        {
            "datasheet_id": "dst123",
            "view_id": "viw123",
            "fields": ["name"],
            "formula": "{name} != ''",
            "records": [{"id": "rec1", "fields": {"name": "Alice"}}],
            "total": 250000,
        },
        max_chars=120,
    )

    assert result["truncated"] is True
    assert result["recommended_tool"] == "vika_export_records"
    assert result["recommended_args"] == {
        "datasheet_id": "dst123",
        "view_id": "viw123",
        "fields": ["name"],
        "formula": "{name} != ''",
        "max_records": 100000,
    }
    assert "format" not in result["recommended_args"]


def test_inline_overflow_recommended_args_without_optional_filters_validate_against_export_schema() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.limits import enforce_inline_record_limit
    from vika_mcp.runtime.validation import validate_arguments

    result = enforce_inline_record_limit(
        {
            "datasheet_id": "dst123",
            "records": [{"id": "rec1", "fields": {"name": "Alice", "notes": "x" * 200}}],
            "total": 42,
        },
        max_chars=80,
    )
    registry = build_hidden_registry()
    spec, _handler = registry.get("vika_export_records")

    assert result["recommended_args"] == {"datasheet_id": "dst123", "max_records": 42}
    assert validate_arguments(result["recommended_args"], spec.input_schema) == []
    assert "format" not in result["recommended_args"]


def test_artifact_store_writes_jsonl_manifest_and_enforces_read_limits(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path)
    created = store.create_records_export(
        datasheet_id="dst123",
        records=[{"id": str(i), "fields": {"name": f"row-{i}"}} for i in range(10)],
        field_names=["name"],
        source_args={"datasheet_id": "dst123"},
        format="jsonl",
    )

    assert created["format"] == "jsonl"
    assert created["record_count"] == 10
    assert Path(created["path"]).is_file()

    head = store.head(created["artifact_id"], lines=200)
    assert head["returned_lines"] == 10
    assert head["max_lines"] == 100

    hits = store.search(created["artifact_id"], query="row-9", max_hits=200)
    assert hits["max_hits"] == 100
    assert hits["hits"][0]["line_number"] == 10
    assert len(hits["hits"][0]["snippet"]) <= 300

    window = store.read(created["artifact_id"], start_line=2, lines=1000, max_chars=200)
    assert window["max_lines"] == 500
    assert window["start_line"] == 2
    assert window["returned_lines"] <= 500
    assert window["truncated_by_chars"] is True


def test_artifact_store_rejects_paths_outside_exports(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path)
    outside = tmp_path.parent / "outside.jsonl"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact"):
        store.read(outside.stem)


def test_export_records_schema_requires_explicit_record_bound() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    spec, _handler = registry.get("vika_export_records")

    assert "max_records" in spec.input_schema["required"]
    assert spec.input_schema["properties"]["max_records"]["maximum"] == 100000
    assert spec.input_schema["properties"]["format"]["enum"] == ["csv", "jsonl"]


def test_attachment_download_schema_requires_url() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    spec, _handler = registry.get("vika.attachments.download")

    assert spec.input_schema["required"] == ["url"]
    assert "attachment" not in spec.input_schema["properties"]
    assert "save_path" not in spec.input_schema["properties"]


def test_artifact_store_creates_binary_download_manifest_without_inline_content(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path)
    created = store.create_download_artifact(
        filename="report.pdf",
        source_url="https://vika.cn/attachments/report.pdf",
        content_type="application/pdf",
        content=b"abc",
    )

    assert created["artifact_id"].startswith("dl_")
    assert created["format"] == "binary"
    assert created["filename"] == "report.pdf"
    assert created["byte_count"] == 3
    assert created["content_inline"] is False
    assert created["next_actions"] == ["vika_artifact_status"]
    assert Path(created["path"]).is_file()

    manifest = store.status(created["artifact_id"])
    assert manifest["source_url_hash"]
    assert "source_url" not in manifest

    with pytest.raises(ValueError, match="not line-readable"):
        store.read(created["artifact_id"])


def test_artifact_store_writes_csv_by_default_for_tabular_analysis(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path)
    created = store.create_records_export(
        datasheet_id="dst123",
        records=[{"id": "rec1", "fields": {"name": "Alice", "score": 3}}],
        field_names=["name", "score"],
        source_args={"datasheet_id": "dst123", "max_records": 1},
    )

    assert created["format"] == "csv"
    assert created["path"].endswith(".csv")
    assert created["record_count"] == 1

    text = Path(created["path"]).read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == "record_id,name,score"
    assert "rec1,Alice,3" in text

    head = store.head(created["artifact_id"], lines=2)
    assert head["lines"][0] == "record_id,name,score"
    assert head["returned_lines"] == 2


def test_artifact_export_response_does_not_inline_record_preview(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore

    large_text = "x" * 5000
    store = ArtifactStore(tmp_path)
    created = store.create_records_export(
        datasheet_id="dst123",
        records=[{"id": "rec1", "fields": {"name": "Alice", "notes": large_text}}],
        field_names=["name", "notes"],
        source_args={"datasheet_id": "dst123", "max_records": 1},
    )

    assert "preview" not in created
    assert created["content_inline"] is False
    assert created["next_actions"] == ["vika_artifact_head", "vika_artifact_search", "vika_artifact_read"]
    assert large_text not in str(created)


def test_artifact_store_can_still_write_jsonl_when_requested(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path)
    created = store.create_records_export(
        datasheet_id="dst123",
        records=[{"id": "rec1", "fields": {"name": "Alice"}}],
        field_names=["name"],
        source_args={"datasheet_id": "dst123", "max_records": 1, "format": "jsonl"},
        format="jsonl",
    )

    assert created["format"] == "jsonl"
    assert created["path"].endswith(".jsonl")
    assert store.status(created["artifact_id"])["format"] == "jsonl"


@pytest.mark.anyio
async def test_export_records_uses_runtime_artifact_store(tmp_path, monkeypatch) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.services import RuntimeServices

    class FakeClient:
        configured = True

        async def records_read_all(self, *args, **kwargs):
            return {"records": [{"id": "rec1", "fields": {"name": "Alice"}}]}

    services = RuntimeServices(artifact_store=ArtifactStore(tmp_path))
    registry = build_hidden_registry(services=services, vika_client=FakeClient())
    runtime = MetaToolRuntime(registry, artifact_store=services.artifact_store)
    exported = await runtime.call_tool("vika_export_records", {"datasheet_id": "dst123", "max_records": 1})
    read = await runtime.artifact_read(exported["artifact_id"], start_line=1, lines=2)

    assert exported["format"] == "csv"
    assert exported["path"].endswith(".csv")
    assert read["returned_lines"] == 2
    assert read["lines"][0] == "record_id,name"
    assert read["lines"][1] == "rec1,Alice"
    assert str(tmp_path) in exported["path"]
