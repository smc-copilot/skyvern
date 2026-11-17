"""Import helpers for PR-00 scripts that live outside the skyvern package."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ENTERPRISE_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "enterprise"


def load_enterprise_module(name: str) -> ModuleType:
    """Load scripts/enterprise/<name>.py as a module using that directory on sys.path."""
    scripts_dir = str(ENTERPRISE_SCRIPTS)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    path = ENTERPRISE_SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"enterprise_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
