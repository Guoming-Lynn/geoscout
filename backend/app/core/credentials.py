from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.redact import redact_text


@dataclass
class SessionCredentials:
    session_id: str
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_timeout_s: float = 60.0
    llm_input_price_per_mtok: float | None = None
    llm_output_price_per_mtok: float | None = None
    ncbi_api_key: str = ""
    ncbi_email: str = ""
    ncbi_tool: str = "GEOScout"
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def public_view(self) -> dict:
        host = redact_text(self.llm_base_url)
        return {
            "session_id": self.session_id,
            "llm_provider": self.llm_provider,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_key_present": bool(self.llm_api_key),
            "llm_timeout_s": self.llm_timeout_s,
            "llm_input_price_per_mtok": self.llm_input_price_per_mtok,
            "llm_output_price_per_mtok": self.llm_output_price_per_mtok,
            "ncbi_key_present": bool(self.ncbi_api_key),
            "ncbi_email": self.ncbi_email,
            "ncbi_tool": self.ncbi_tool,
            "request_target": host,
            "updated_at": self.updated_at.isoformat(),
        }

    def has_llm_key(self) -> bool:
        return bool(self.llm_api_key)


class CredentialStore:
    """Process-memory credentials. Never written to SQLite or logs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, SessionCredentials] = {}

    def get_or_create(self, session_id: str | None) -> SessionCredentials:
        self._prune()
        sid = session_id or secrets.token_urlsafe(18)
        with self._lock:
            if sid not in self._items:
                self._items[sid] = SessionCredentials(session_id=sid)
            return self._items[sid]

    def _prune(self) -> None:
        """Drop stale empty sessions. Keep recently updated sessions that still hold keys."""
        now = datetime.now(timezone.utc)
        max_items = 200
        with self._lock:
            stale = [
                sid
                for sid, creds in self._items.items()
                if not creds.llm_api_key
                and not creds.ncbi_api_key
                and (now - creds.updated_at).total_seconds() > 3600
            ]
            for sid in stale:
                self._items.pop(sid, None)
            if len(self._items) <= max_items:
                return
            ranked = sorted(self._items.values(), key=lambda item: item.updated_at)
            for creds in ranked:
                if len(self._items) <= max_items:
                    break
                if creds.llm_api_key or creds.ncbi_api_key:
                    continue
                if (now - creds.updated_at).total_seconds() < 600:
                    continue
                self._items.pop(creds.session_id, None)

    def update(self, session_id: str, **fields: object) -> SessionCredentials:
        creds = self.get_or_create(session_id)
        with self._lock:
            for key, value in fields.items():
                if value is None:
                    continue
                if not hasattr(creds, key):
                    continue
                setattr(creds, key, value)
            creds.updated_at = datetime.now(timezone.utc)
            return creds

    def get(self, session_id: str | None) -> SessionCredentials | None:
        if not session_id:
            return None
        with self._lock:
            return self._items.get(session_id)


store = CredentialStore()
