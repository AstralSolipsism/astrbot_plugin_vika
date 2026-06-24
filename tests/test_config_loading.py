from __future__ import annotations

from pathlib import Path

import pytest


def test_load_config_allows_absent_default_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vika_mcp.config import load_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIKAMCP_CONFIG", raising=False)

    cfg = load_config()

    assert cfg.server.host == "localhost"
    assert cfg.vika.host == "https://vika.cn"


def test_load_config_rejects_missing_explicit_config(tmp_path: Path) -> None:
    from vika_mcp.config import load_config

    missing = tmp_path / "missing.yaml"

    with pytest.raises(ValueError, match="Config file not found"):
        load_config(str(missing))


def test_load_config_rejects_missing_env_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vika_mcp.config import load_config

    monkeypatch.setenv("VIKAMCP_CONFIG", str(tmp_path / "missing.yaml"))

    with pytest.raises(ValueError, match="Config file not found"):
        load_config()


def test_load_config_rejects_invalid_yaml(tmp_path: Path) -> None:
    from vika_mcp.config import load_config

    config_path = tmp_path / "vika_mcp.yaml"
    config_path.write_text("vika: [", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to parse config file"):
        load_config(str(config_path))


def test_load_config_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    from vika_mcp.config import load_config

    config_path = tmp_path / "vika_mcp.yaml"
    config_path.write_text("- item\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        load_config(str(config_path))


def test_env_parses_attachment_download_allowed_hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vika_mcp.config import load_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIKAMCP_CONFIG", raising=False)
    monkeypatch.setenv("VIKAMCP_VIKA__ATTACHMENT_DOWNLOAD_ALLOWED_HOSTS", "files.vika.cn, cdn.example.com")

    cfg = load_config()

    assert cfg.vika.attachment_download_allowed_hosts == ["files.vika.cn", "cdn.example.com"]
