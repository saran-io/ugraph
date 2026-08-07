"""ShareDraft — the only payload share adapters accept."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class ShareError(RuntimeError):
    """User-visible share failure. Never includes secret material."""


@dataclass(frozen=True)
class ShareDraft:
    """Exactly what the user asked to publish — no KB invention."""

    text: str
    media: tuple[Path, ...] = ()
    destination: str = "x"

    def normalized(self) -> ShareDraft:
        text = self.text.strip()
        if not text and not self.media:
            raise ShareError("nothing to share — text is empty")
        return ShareDraft(text=text, media=self.media, destination=self.destination)


@dataclass(frozen=True)
class ShareResult:
    destination: str
    post_id: str
    url: str
    text: str
    dry_run: bool = False
    extra: dict = field(default_factory=dict)
