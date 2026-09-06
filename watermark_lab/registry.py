"""Session registry matching and policy decisions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .core import session_tag


@dataclass(frozen=True)
class RegistryMatch:
    session_id: str | None
    status: str
    action: str


def load_registry(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sessions = data.get("sessions", [])
    if not isinstance(sessions, list):
        raise ValueError("registry must contain a 'sessions' list")
    return sessions


def match_tag(
    tag_hex: str,
    sessions: list[dict[str, Any]],
    secret: str,
    destination_session: str | None = None,
) -> RegistryMatch:
    tag_bytes = len(bytes.fromhex(tag_hex))
    for item in sessions:
        candidate = str(item["session_id"])
        expected = session_tag(secret, candidate, tag_bytes).hex()
        if expected != tag_hex:
            continue
        status = str(item.get("status", "unknown")).lower()
        if candidate == destination_session:
            action = "allow-self"
        elif status in {"malicious", "terminated", "blocked"}:
            action = "block"
        elif status in {"suspicious", "quarantined", "unknown"}:
            action = "quarantine"
        else:
            action = "review-cross-session"
        return RegistryMatch(candidate, status, action)
    return RegistryMatch(None, "unregistered", "quarantine")

