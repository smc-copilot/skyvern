"""Read pyproject.toml [project].version without extra dependencies."""

from __future__ import annotations

import tomllib
from pathlib import Path

from errors import EnterpriseError


def read_project_version(repo_root: Path) -> str:
    """Return [project].version from pyproject.toml."""
    path = repo_root / "pyproject.toml"
    if not path.is_file():
        raise EnterpriseError("BUILD_VERSION_MISSING", f"{path} is not a file")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        version = data["project"]["version"]
    except KeyError as exc:
        raise EnterpriseError("BUILD_VERSION_MISSING", "pyproject.toml has no [project].version") from exc
    if not isinstance(version, str) or not version.strip():
        raise EnterpriseError("BUILD_VERSION_MISSING", f"invalid version {version!r}")
    return version
