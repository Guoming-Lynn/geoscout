from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.redact import redact_mapping


def write_audit_pack(path: Path, payload: dict[str, Any]) -> None:
    clean = redact_mapping(payload)
    if isinstance(clean, dict):
        for key in list(clean):
            if "key" in key.lower() or "token" in key.lower() or "authorization" in key.lower():
                clean.pop(key, None)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
