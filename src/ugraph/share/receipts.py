"""Append-only share receipts. Never store tokens."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ugraph.share.secrets import share_dir


def receipts_path() -> Path:
    return share_dir() / "receipts.jsonl"


def record(destination: str, post_id: str, url: str, text: str,
           dry_run: bool = False) -> dict:
    event = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "destination": destination,
        "post_id": post_id,
        "url": url,
        "chars": len(text),
        "preview": text[:80],
        "dry_run": dry_run,
    }
    path = receipts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return event
