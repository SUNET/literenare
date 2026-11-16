"""Loads config.yaml with ${VAR:-default} environment expansion."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ENV = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path or os.environ.get("LITERENARE_CONFIG", "config.yaml"))
    with path.open(encoding="utf-8") as fh:
        return _expand(yaml.safe_load(fh))


@lru_cache
def get_config() -> dict[str, Any]:
    return load_config()
