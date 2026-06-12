from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _python_env(extra_pythonpath: list[Path] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(path) for path in (extra_pythonpath or [])]
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def test_requirements_use_versioned_astral_vika_dependency_not_editable_path() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    normalized = {
        line.strip().lower()
        for line in requirements
        if line.strip() and not line.strip().startswith("#")
    }

    assert any(line.startswith("astral-vika") or line.startswith("astral_vika") for line in normalized)
    assert not any(line.startswith("-e ") and "astral_vika" in line for line in normalized)


def test_project_metadata_declares_mcp_package_and_astral_dependency() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "vika-mcp"
    assert metadata["project"]["scripts"]["vika-mcp"] == "vika_mcp.__main__:main"

    dependencies = {dependency.lower() for dependency in metadata["project"]["dependencies"]}
    assert any(dependency.startswith("astral-vika") or dependency.startswith("astral_vika") for dependency in dependencies)

    packages = set(metadata["tool"]["setuptools"]["packages"])
    assert {"vika_mcp", "vika_mcp.mcp", "vika_mcp.tools"}.issubset(packages)
    assert not any(package == "astral_vika" or package.startswith("astral_vika.") for package in packages)

    package_dir = metadata["tool"]["setuptools"]["package-dir"]
    assert package_dir["vika_mcp"] == "."
    assert "astral_vika" not in package_dir


def test_vika_mcp_source_checkout_bootstraps_local_astral_vika() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import vika_mcp; "
                "from vika_mcp.tools import vika_tools as vt; "
                "import astral_vika; "
                "print(f'imported={vt._VIKA_IMPORTED};version={astral_vika.__version__}')"
            ),
        ],
        cwd=ROOT.parent,
        env=_python_env([ROOT.parent]),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "imported=True;version=1.1.3" in result.stdout


def test_standard_x_api_key_header_is_accepted() -> None:
    sys.path.insert(0, str(ROOT.parent))
    sys.path.insert(0, str(ROOT / "astral_vika" / "src"))

    from fastapi.testclient import TestClient
    from vika_mcp.server import create_app

    env = os.environ.copy()
    os.environ["VIKAMCP_API_KEY"] = "secret"
    try:
        client = TestClient(create_app())
    finally:
        os.environ.clear()
        os.environ.update(env)

    assert client.get("/mcp/v1/tools").status_code == 401
    assert client.get("/mcp/v1/tools", headers={"X-API-Key": "secret"}).status_code == 200
