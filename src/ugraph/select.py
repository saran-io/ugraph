"""
select.py — choosing *which* sources a command should act on.

Every command that walks the KB needs the same three questions answered: how recent,
since when, and which channel. They live here rather than in each command so the flags
cannot drift apart — `--newest` meaning one thing in `extract` and another in `ledger`
would be worse than not having it.

## The ordering trap

Pages are selected by their `published` frontmatter, and some pages do not have it.
Sorting `["2026-08-02", "2026-07-31", None]` descending with a naive key puts the
*undated* page first, so `--newest 3` would confidently return pages whose date nobody
knows as "the three most recent". In this KB that is three hand-written Karpathy pages,
which would have displaced real recent talks every single time.

So undated pages sort **last**, and `--since` drops them: a page that cannot prove it
falls inside the window is not in the window.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

#: `7d`, `2w`, `3m`, `1y` — relative windows, because "since a week ago" is what people
#: actually mean and computing the date by hand is friction.
_RELATIVE = re.compile(r"^(\d+)\s*([dwmy])$", re.IGNORECASE)

_UNITS = {"d": 1, "w": 7, "m": 30, "y": 365}

#: Sorts after every real ISO date, so undated pages land at the end of a newest-first
#: list instead of the front. The comparison is on the string, so this only has to be
#: lexically larger than any date we will ever see.
_UNDATED = "￿"


def parse_since(value: str, today: date | None = None) -> date:
    """`2026-07-25`, or a relative window like `7d` / `2w` / `3m` / `1y`.

    Raises ValueError with the accepted forms, since this is user input from a flag.
    """
    text = str(value).strip()

    match = _RELATIVE.match(text)
    if match:
        count, unit = int(match.group(1)), match.group(2).lower()
        return (today or date.today()) - timedelta(days=count * _UNITS[unit])

    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            f"cannot read {value!r} as a date. Use YYYY-MM-DD, or a window "
            "like 7d, 2w, 3m, 1y."
        ) from None


def _field(item: Any, name: str) -> Any:
    """Read `name` off either a `model.Page` (frontmatter in `.meta`) or a
    `ledger.Item` (plain dataclass attribute).

    Both are "a source" as far as selection cares, and duck-typing here means the
    flags behave identically in `extract` and `ledger` without either module having
    to know about the other.
    """
    meta = getattr(item, "meta", None)
    if isinstance(meta, dict) and meta.get(name) is not None:
        return meta[name]
    return getattr(item, name, None)


def published(page: Any) -> str:
    """The page's publication date as a sortable string, or the undated sentinel."""
    raw = _field(page, "published")
    text = str(raw).strip() if raw is not None else ""
    return text or _UNDATED


def is_dated(page: Any) -> bool:
    return published(page) != _UNDATED


def identity(page: Any) -> str:
    """A stable name for tie-breaking: the slug where there is one."""
    return str(_field(page, "slug") or getattr(page, "id", "") or "")


def channel_of(page: Any) -> str:
    """First path segment of the slug: `ai-engineer/some-talk` -> `ai-engineer`.

    Deliberately *not* the `channel` frontmatter field, which holds the display name
    ("AI Engineer"). The slug segment is what the directories are named and what the
    user can see, so it is what `--channel` should match.
    """
    slug = identity(page)
    return slug.split("/")[0] if "/" in slug else ""


def newest_first(pages: Iterable[Any]) -> list[Any]:
    """Most recently published first; undated last.

    Ties break on slug so two runs over the same KB choose the same work. A batch job
    that picks a different five sources each time it runs is not resumable.
    """
    return sorted(
        pages,
        key=lambda p: (published(p) == _UNDATED, _invert(published(p)), identity(p)),
    )


def _invert(text: str) -> str:
    """Sort key that reverses a string's order without reversing the tie-breaker.

    `sorted(reverse=True)` would flip the slug tie-break too, making the ordering read
    backwards for same-day items. Inverting only the date keeps both correct.
    """
    return "".join(chr(0x10FFFF - ord(ch)) if ord(ch) < 0x10FFFF else ch for ch in text)


def by_recency(pages: Iterable[Any], newest: int | None = None,
               since: date | None = None, channel: str | None = None) -> list[Any]:
    """Filter and order a set of pages the way every command should.

    Applied in this order, which is also how the flags read aloud:
    channel narrows the corpus, `since` bounds the window, `newest` takes the top N.
    A caller's own `--limit` then applies last, so `--newest 20 --limit 5` is
    "of the 20 most recent, do 5".
    """
    selected = list(pages)

    if channel:
        selected = [p for p in selected if channel_of(p) == channel]

    if since is not None:
        # Undated pages are dropped rather than kept: `--since` asks for a proof of
        # recency that they cannot give.
        selected = [p for p in selected
                    if is_dated(p) and published(p) >= since.isoformat()]

    selected = newest_first(selected)

    if newest is not None:
        selected = selected[:newest]

    return selected


def describe(newest: int | None = None, since: date | None = None,
             channel: str | None = None) -> str:
    """A short human phrase for what was selected, for command output."""
    parts = []
    if newest is not None:
        parts.append(f"{newest} most recent")
    if since is not None:
        parts.append(f"published since {since.isoformat()}")
    if channel:
        parts.append(f"in {channel}")
    return ", ".join(parts)
