"""Immutable local experiment metadata. Never read application secrets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from claimguard.benchmark.corpus import fingerprint


def freeze_metadata(path: Path, value: Mapping[str, Any]) -> str:
    """Require identical source/hardware metadata on resume; never overwrite evidence."""
    if path.exists():
        previous: Any = json.loads(path.read_text(encoding="utf-8"))
        if previous != dict(value):
            raise ValueError(
                f"Experiment metadata changed: {path.name}; use a new output directory"
            )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(value), indent=2, ensure_ascii=False), encoding="utf-8")
    return fingerprint(value)
