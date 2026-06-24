from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest


@pytest.mark.anyio
async def test_write_plan_preview_returns_confirmation_context_for_llm() -> None:
    from vika_mcp.runtime.write_plans import WritePlanStore

    store = WritePlanStore()
    operation = store.preview(
        operation_type="records.create",
        datasheet_id="dst123",
        target_label="客户跟进表",
        payload={"records": [{"fields": {"客户名": "Alice", "来源": "官网"}}]},
        field_names=["客户名", "来源"],
        record_count=1,
        execute=lambda operation: {"created": len(operation["payload"]["records"])},
    )

    assert operation["preview_only"] is True
    assert operation["requires_confirmation"] is True
    assert "confirmation_summary" not in operation
    assert "field_names" not in operation
    assert "sample_records" not in operation

    context = operation["confirmation_context"]
    assert context["operation_id"] == operation["operation_id"]
    assert context["operation_type"] == "records.create"
    assert context["target_label"] == "客户跟进表"
    assert context["record_count"] == 1
    assert context["risk_level"] == "medium"
    assert context["payload_hash"] == operation["payload_hash"]
    assert context["expires_at"] == operation["expires_at"]
    assert context["operation_label"] == "新增"

    assert operation["confirmation_brief"] == "将对《客户跟进表》新增 1 条记录，风险等级 medium。"
    instruction = operation["ask_user_instruction"]
    assert "一句自然语言" in instruction
    assert "不要展示原始 payload" in instruction
    assert "样本记录" in instruction
    assert "完整字段列表" in instruction
    assert "调试结构" in instruction
    assert "confirmed_payload_hash" in instruction


@pytest.mark.anyio
async def test_write_plan_commit_uses_payload_hash_and_audit_summary() -> None:
    from vika_mcp.runtime.write_plans import WritePlanStore

    store = WritePlanStore()
    operation = store.preview(
        operation_type="records.create",
        datasheet_id="dst123",
        target_label="客户跟进表",
        payload={"records": [{"fields": {"客户名": "Alice", "来源": "官网"}}]},
        field_names=["客户名", "来源"],
        record_count=1,
        execute=lambda operation: {"created": len(operation["payload"]["records"])},
    )

    rejected = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash="wrong-hash",
        confirmed_by_user=True,
        user_confirmation_summary="用户确认向客户跟进表新增 1 条记录。",
    )
    assert rejected["error"]["code"] == "confirmed_payload_hash_mismatch"

    committed = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=operation["payload_hash"],
        confirmed_by_user=True,
        user_confirmation_summary="用户确认向客户跟进表新增 1 条记录。",
    )
    assert committed["committed"] is True
    assert committed["result"] == {"created": 1}
    assert committed["user_confirmation_summary"] == "用户确认向客户跟进表新增 1 条记录。"

    repeated = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=operation["payload_hash"],
        confirmed_by_user=True,
        user_confirmation_summary="第二次确认文本不会改变已提交结果。",
    )
    assert repeated["already_committed"] is True
    assert repeated["result"] == committed["result"]
    assert repeated["user_confirmation_summary"] == committed["user_confirmation_summary"]


@pytest.mark.anyio
async def test_write_plan_commit_error_result_is_not_marked_committed_and_can_retry() -> None:
    from vika_mcp.runtime.write_plans import WritePlanStore

    store = WritePlanStore()
    attempts = {"count": 0}

    def fail_write(operation):
        attempts["count"] += 1
        return {"error": {"code": "vika_error", "message": "failed"}}

    operation = store.preview(
        operation_type="records.create",
        datasheet_id="dst123",
        target_label="客户跟进表",
        payload={"records": [{"fields": {"客户名": "Alice"}}]},
        field_names=["客户名"],
        record_count=1,
        execute=fail_write,
    )

    failed = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=operation["payload_hash"],
        confirmed_by_user=True,
    )
    assert failed == {
        "operation_id": operation["operation_id"],
        "committed": False,
        "error": {"code": "vika_error", "message": "failed"},
    }
    assert attempts["count"] == 1

    retried = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=operation["payload_hash"],
        confirmed_by_user=True,
    )
    assert retried["committed"] is False
    assert retried["error"]["code"] == "vika_error"
    assert "already_committed" not in retried
    assert attempts["count"] == 2


@pytest.mark.anyio
async def test_write_plan_commit_rejects_missing_hash_expired_or_unconfirmed_operations() -> None:
    from vika_mcp.runtime.write_plans import WritePlanStore

    store = WritePlanStore()
    operation = store.preview(
        operation_type="records.delete",
        datasheet_id="dst123",
        target_label="客户跟进表",
        payload={"record_ids": ["rec1"]},
        field_names=[],
        record_count=1,
        execute=lambda operation: {"deleted": len(operation["payload"]["record_ids"])},
    )

    unconfirmed = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=operation["payload_hash"],
        confirmed_by_user=False,
    )
    assert unconfirmed["error"]["code"] == "user_confirmation_required"

    missing_hash = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=None,
        confirmed_by_user=True,
    )
    assert missing_hash["error"]["code"] == "confirmed_payload_hash_required"

    expired_store = WritePlanStore(default_ttl=timedelta(seconds=-1))
    expired_operation = expired_store.preview(
        operation_type="records.delete",
        datasheet_id="dst123",
        target_label="客户跟进表",
        payload={"record_ids": ["rec1"]},
        field_names=[],
        record_count=1,
        execute=lambda operation: {"deleted": len(operation["payload"]["record_ids"])},
    )
    expired = await expired_store.commit(
        expired_operation["operation_id"],
        confirmed_payload_hash=expired_operation["payload_hash"],
        confirmed_by_user=True,
    )
    assert expired["error"]["code"] == "operation_expired"


@pytest.mark.anyio
async def test_vika_write_tool_uses_preview_commit_boundary() -> None:
    from vika_mcp.runtime.services import RuntimeServices
    from vika_mcp.tools import vika_tools

    class FakeClient:
        configured = True

        async def records_create(self, datasheet_id, records, field_key=None):
            return {"datasheet_id": datasheet_id, "created": len(records), "field_key": field_key}

    services = RuntimeServices(vika_client=FakeClient())
    preview = await vika_tools.vika_records_create(
        {
            "datasheet_id": "dst123",
            "records": [{"fields": {"客户名": "Alice", "来源": "官网"}}],
        },
        services,
    )
    assert preview["preview_only"] is True
    assert preview["operation_type"] == "records.create"
    assert "operation_id" in preview
    assert "confirmation_summary" not in preview

    committed = await vika_tools.vika_write_commit(
        {
            "operation_id": preview["operation_id"],
            "confirmed_payload_hash": preview["payload_hash"],
            "confirmed_by_user": True,
            "user_confirmation_summary": "用户确认向目标表新增 1 条记录。",
        },
        services,
    )
    assert committed["committed"] is True
    assert committed["result"]["created"] == 1


@pytest.mark.anyio
async def test_write_plan_commit_uses_preview_payload_snapshot() -> None:
    from vika_mcp.runtime.write_plans import WritePlanStore

    store = WritePlanStore()
    observed = {}
    payload = {"records": [{"fields": {"客户名": "Alice"}}]}
    operation = store.preview(
        operation_type="records.create",
        datasheet_id="dst123",
        target_label="客户跟进表",
        payload=payload,
        field_names=["客户名"],
        record_count=1,
        execute=lambda operation: observed.setdefault("payload", operation["payload"]),
    )
    payload["records"][0]["fields"]["客户名"] = "Bob"

    committed = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=operation["payload_hash"],
        confirmed_by_user=True,
    )

    assert committed["committed"] is True
    assert observed["payload"]["records"][0]["fields"]["客户名"] == "Alice"


@pytest.mark.anyio
async def test_write_plan_commit_rejects_payload_hash_mismatch() -> None:
    from vika_mcp.runtime.write_plans import WritePlanStore

    store = WritePlanStore()
    operation = store.preview(
        operation_type="records.create",
        datasheet_id="dst123",
        target_label="客户跟进表",
        payload={"records": [{"fields": {"客户名": "Alice"}}]},
        field_names=["客户名"],
        record_count=1,
        execute=lambda operation: {"created": len(operation["payload"]["records"])},
    )
    store._operations[operation["operation_id"]]["payload"]["records"][0]["fields"]["客户名"] = "Bob"

    rejected = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=operation["payload_hash"],
        confirmed_by_user=True,
    )

    assert rejected["error"]["code"] == "payload_hash_mismatch"


@pytest.mark.anyio
async def test_write_plan_preview_public_objects_do_not_mutate_stored_payload() -> None:
    from vika_mcp.runtime.write_plans import WritePlanStore

    store = WritePlanStore()
    observed = {}
    operation = store.preview(
        operation_type="records.create",
        datasheet_id="dst123",
        target_label="客户跟进表",
        payload={"records": [{"fields": {"客户名": "Alice"}}]},
        field_names=["客户名"],
        record_count=1,
        execute=lambda operation: observed.setdefault("payload", operation["payload"]),
    )
    operation["confirmation_context"]["payload_hash"] = "tampered"

    committed = await store.commit(
        operation["operation_id"],
        confirmed_payload_hash=operation["payload_hash"],
        confirmed_by_user=True,
    )

    assert committed["committed"] is True
    assert observed["payload"]["records"][0]["fields"]["客户名"] == "Alice"


@pytest.mark.anyio
async def test_vika_write_tool_commit_uses_preview_payload_after_args_mutation() -> None:
    from vika_mcp.runtime.services import RuntimeServices
    from vika_mcp.tools import vika_tools

    class FakeClient:
        configured = True

        async def records_create(self, datasheet_id, records, field_key=None):
            return {"datasheet_id": datasheet_id, "records": records, "field_key": field_key}

    services = RuntimeServices(vika_client=FakeClient())
    args = {
        "datasheet_id": "dstOriginal",
        "records": [{"fields": {"客户名": "Alice"}}],
        "field_key": "name",
    }
    preview = await vika_tools.vika_records_create(args, services)
    args["datasheet_id"] = "dstMutated"
    args["records"][0]["fields"]["客户名"] = "Bob"
    args["field_key"] = "id"

    committed = await vika_tools.vika_write_commit(
        {
            "operation_id": preview["operation_id"],
            "confirmed_payload_hash": preview["payload_hash"],
            "confirmed_by_user": True,
        },
        services,
    )

    assert committed["result"]["datasheet_id"] == "dstOriginal"
    assert committed["result"]["records"][0]["fields"]["客户名"] == "Alice"
    assert committed["result"]["field_key"] == "name"


@pytest.mark.anyio
async def test_attachment_upload_preview_discloses_file_facts_without_path_restriction(tmp_path: Path) -> None:
    from vika_mcp.runtime.services import RuntimeServices
    from vika_mcp.tools import vika_tools

    class FakeClient:
        configured = True

        async def attachments_upload(self, datasheet_id, file_path):
            return {"datasheet_id": datasheet_id, "file_path": file_path}

    local_file = tmp_path / "outside-artifact-root.txt"
    local_file.write_text("upload me", encoding="utf-8")
    services = RuntimeServices(vika_client=FakeClient())

    preview = await vika_tools.vika_attachments_upload(
        {"datasheet_id": "dst123", "file_path": str(local_file)},
        services,
    )

    expected_hash = hashlib.sha256(local_file.read_bytes()).hexdigest()
    context = preview["confirmation_context"]
    assert context["file_path"] == str(local_file.resolve())
    assert context["file_name"] == "outside-artifact-root.txt"
    assert context["file_size_bytes"] == len("upload me")
    assert context["file_sha256"] == expected_hash
    assert preview["preview_only"] is True
    assert "outside-artifact-root.txt" in preview["confirmation_brief"]


@pytest.mark.anyio
async def test_attachment_upload_commit_rejects_changed_file_after_preview(tmp_path: Path) -> None:
    from vika_mcp.runtime.services import RuntimeServices
    from vika_mcp.tools import vika_tools

    class FakeClient:
        configured = True

        async def attachments_upload(self, datasheet_id, file_path):
            return {"datasheet_id": datasheet_id, "file_path": file_path}

    local_file = tmp_path / "mutable.txt"
    local_file.write_text("before", encoding="utf-8")
    services = RuntimeServices(vika_client=FakeClient())

    preview = await vika_tools.vika_attachments_upload(
        {"datasheet_id": "dst123", "file_path": str(local_file)},
        services,
    )
    local_file.write_text("after", encoding="utf-8")
    committed = await vika_tools.vika_write_commit(
        {
            "operation_id": preview["operation_id"],
            "confirmed_payload_hash": preview["payload_hash"],
            "confirmed_by_user": True,
        },
        services,
    )

    assert committed["committed"] is False
    assert committed["error"]["code"] == "file_hash_mismatch"


def test_vika_write_commit_schema_uses_payload_hash_without_user_summary_match() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    spec, _handler = registry.get("vika.write.commit")
    properties = spec.input_schema["properties"]
    required = set(spec.input_schema["required"])

    assert "confirmed_payload_hash" in required
    assert "confirmed_summary" not in properties
    assert "user_confirmation_summary" in properties
    assert "user_confirmation_summary" not in required


@pytest.mark.anyio
async def test_runtime_services_isolate_write_plan_stores() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.services import RuntimeServices

    class FakeClient:
        configured = True

        async def records_create(self, datasheet_id, records, field_key=None):
            return {"datasheet_id": datasheet_id, "created": len(records)}

    services_a = RuntimeServices()
    services_b = RuntimeServices()
    registry_a = build_hidden_registry(services=services_a, vika_client=FakeClient())
    registry_b = build_hidden_registry(services=services_b, vika_client=FakeClient())

    _spec_a, create_a = registry_a.get("vika.records.create")
    _spec_b, commit_b = registry_b.get("vika.write.commit")
    preview = await create_a({"datasheet_id": "dst123", "records": [{"fields": {"name": "Alice"}}]})
    rejected = await commit_b(
        {
            "operation_id": preview["operation_id"],
            "confirmed_payload_hash": preview["payload_hash"],
            "confirmed_by_user": True,
        }
    )

    assert rejected["error"]["code"] == "operation_not_found"
