from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.anyio
async def test_attachment_download_rejects_non_allowlisted_host(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(
        api_token="token",
        host="https://vika.cn",
        attachment_download_allowed_hosts=["files.vika.cn"],
    )

    result = await client.attachments_download(
        "https://evil.example/file.txt",
        ArtifactStore(tmp_path),
    )

    assert result["error"]["code"] == "attachment_download_host_not_allowed"


@pytest.mark.anyio
async def test_attachment_download_writes_allowlisted_url_to_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(
        api_token="token",
        host="https://vika.cn",
        attachment_download_allowed_hosts=["files.vika.cn"],
    )

    async def fake_download(url: str, path: Path, max_bytes: int):
        path.write_bytes(b"downloaded bytes")
        return {
            "byte_count": len(b"downloaded bytes"),
            "content_type": "text/plain",
            "filename": "safe.txt",
        }

    monkeypatch.setattr(client, "_download_url_to_path", fake_download)

    result = await client.attachments_download(
        "https://files.vika.cn/safe.txt",
        ArtifactStore(tmp_path),
    )

    assert result["artifact_id"].startswith("dl_")
    assert result["filename"] == "safe.txt"
    assert result["byte_count"] == len(b"downloaded bytes")
    assert result["content_type"] == "text/plain"
    assert result["content_inline"] is False
    assert result["next_actions"] == ["vika_artifact_status"]
    assert Path(result["path"]).read_bytes() == b"downloaded bytes"
    assert "content" not in result
    assert "data" not in result


@pytest.mark.anyio
async def test_attachment_download_cleans_partial_file_when_size_limit_exceeded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(
        api_token="token",
        host="https://vika.cn",
        attachment_download_allowed_hosts=["files.vika.cn"],
    )

    async def fake_download(url: str, path: Path, max_bytes: int):
        path.write_bytes(b"partial")
        raise ValueError("attachment_download_too_large")

    monkeypatch.setattr(client, "_download_url_to_path", fake_download)

    result = await client.attachments_download(
        "https://files.vika.cn/large.bin",
        ArtifactStore(tmp_path),
    )

    assert result["error"]["code"] == "attachment_download_too_large"
    assert not list(tmp_path.glob("dl_*"))
