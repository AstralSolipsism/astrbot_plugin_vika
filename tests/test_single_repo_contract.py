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


def test_requirements_do_not_depend_on_external_astral_vika_distribution() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    normalized = {
        line.strip().lower()
        for line in requirements
        if line.strip() and not line.strip().startswith("#")
    }

    assert not any(line.startswith("astral-vika") or line.startswith("astral_vika") for line in normalized)
    assert not any("astral_vika" in line or "astral-vika" in line for line in normalized)


def test_project_metadata_vendors_astral_vika_runtime_package() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "vika-mcp"
    assert metadata["project"]["scripts"]["vika-mcp"] == "vika_mcp.__main__:main"

    dependencies = {dependency.lower() for dependency in metadata["project"]["dependencies"]}
    assert not any(dependency.startswith("astral-vika") or dependency.startswith("astral_vika") for dependency in dependencies)
    assert "mcp==1.12.4" in dependencies

    packages = set(metadata["tool"]["setuptools"]["packages"])
    assert {"vika_mcp", "vika_mcp.runtime", "vika_mcp.tools"}.issubset(packages)
    assert "vika_mcp.mcp" not in packages
    assert {
        "astral_vika",
        "astral_vika.datasheet",
        "astral_vika.node",
        "astral_vika.space",
        "astral_vika.types",
        "astral_vika.unit",
    }.issubset(packages)

    package_dir = metadata["tool"]["setuptools"]["package-dir"]
    assert package_dir["vika_mcp"] == "."
    assert package_dir["astral_vika"] == "vendor/astral_vika/src/astral_vika"


def test_vendored_astral_vika_snapshot_is_present() -> None:
    vendored_root = ROOT / "vendor" / "astral_vika"
    package_root = vendored_root / "src" / "astral_vika"

    assert (vendored_root / "pyproject.toml").is_file()
    assert (vendored_root / "README.md").is_file()
    assert (vendored_root / "LICENSE").is_file()
    assert (package_root / "__init__.py").is_file()


def test_vika_mcp_source_checkout_bootstraps_vendored_astral_vika() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import vika_mcp; "
                "from vika_mcp.tools import vika_tools as vt; "
                "import astral_vika; "
                "print(f'imported={vt._VIKA_IMPORTED};version={astral_vika.__version__};file={astral_vika.__file__}')"
            ),
        ],
        cwd=ROOT.parent,
        env=_python_env([ROOT / "vendor" / "astral_vika" / "src", ROOT.parent]),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "imported=True;version=1.1.3" in result.stdout
    assert "vendor" in result.stdout.replace("\\", "/")


def test_official_mcp_sdk_import_is_not_shadowed_by_source_checkout() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from mcp.server.fastmcp import FastMCP; "
                "import mcp; "
                "print(f'{FastMCP.__name__};{mcp.__file__}')"
            ),
        ],
        cwd=ROOT,
        env=_python_env([ROOT.parent]),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "FastMCP;" in result.stdout
    assert "vika_mcp\\mcp" not in result.stdout.lower()
    assert "vika_mcp/mcp" not in result.stdout.lower()
