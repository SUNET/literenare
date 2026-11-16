"""Service container: everything a pipeline step may need, built once from config."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .backends import make_jev_client


@dataclass
class Services:
    config: dict[str, Any]
    jev: Any               # await .ask(state, questions) -> answers (systemone shape)
    grants: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Services":
        return cls(config=cfg, jev=make_jev_client(**cfg["backends"]["jev"]),
                   grants=load_grants(cfg["server"].get("grants_file")))

    async def aclose(self) -> None:
        if hasattr(self.jev, "aclose"):
            await self.jev.aclose()


def load_grants(path: str | None) -> dict[str, dict]:
    if not path or not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return {g["id"]: g for g in json.load(fh)}
