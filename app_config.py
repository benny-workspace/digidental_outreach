"""Configuration helpers for shared defaults plus local overrides.

Committed config.yaml stays generic for distribution. config.local.yaml is
ignored by git and may hold this machine's active tenant, PIN, and secrets.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.yaml"
LOCAL_CONFIG_PATH = BASE_DIR / "config.local.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    """Load committed defaults, then apply gitignored local overrides."""
    return _deep_merge(_read_yaml(DEFAULT_CONFIG_PATH), _read_yaml(LOCAL_CONFIG_PATH))


def get_config_value(key: str, default: Any = "") -> Any:
    return load_config().get(key, default)
