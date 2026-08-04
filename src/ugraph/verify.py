"""
verify.py — does the knowledge base actually say what the transcript said?

The linter checks that the KB is *well-formed*: frontmatter conforms, links resolve,
every source has a transcript on disk. None of that touches the one claim the whole
format rests on — that a quote is verbatim and a timestamp is real. Extraction agents
reported verifying it. Nothing ever checked. This module is that check.

Two passes, deliberately asymmetric in strictness:

  `verify_candidates`  Machine output, machine-checkable. A candidate's
                       `verbatim_quote` was cut from the transcript by a program, so it
                       must be a literal substring of it and its `timestamp` must be a
                       marker that really exists, with the quote inside that marker's
                       paragraph. Anything less is a bug in extraction.

  `verify_pages`       Human-edited prose. Quotes get re-wrapped, elided with an
                       ellipsis, and surrounded by paraphrase that is not quoting
                       anything. Here the checker is deliberately timid: it only tests
                       text it can *confidently* identify as quotation, and it would
                       rather stay silent than accuse a page wrongly. See the docstring
                       on `verify_pages` for the full list of what it declines to check.

The asymmetry is the point. A checker that cries wolf gets muted, and this one has to
survive being trusted. On a healthy KB the expected output is near-empty; a flood of
failures means the checker is wrong, not the knowledge base.

Nothing here ever repairs anything. Machine captions carry their own disfluencies and
mistranscriptions, and those are preserved inside quotes on purpose — normalizing them
away would destroy the evidence this module exists to protect. The only text surgery
performed is representational (whitespace runs, curly quotes, dash shapes), applied
identically to both sides of every comparison, so it can never turn a mismatch into a
match in one direction only.
"""

from __future__ import annotations

import bisect
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ugraph import store

__all__ = ["QuoteIssue", "verify", "verify_candidates", "verify_pages"]

# -- tuning knobs ------------------------------------------------------------
#
# Every one of these trades recall for precision, in that direction on purpose.

#: A page quotation shorter than this is assumed to be a scare quote or a term of art
#: ("jagged intelligence"), not a quotation of the source. Checking those produces
#: nothing but noise.
MIN_PAGE_QUOTE_CHARS = 40
MIN_PAGE_QUOTE_WORDS = 6

#: Fragments of an elided quote ("... and augments it") shorter than this are ignored;
#: a three-word fragment matches almost any transcript by chance.
MIN_SEGMENT_WORDS = 4

#: How far a page quote may sit from its cited timestamp before it is called a
#: mismatch. Page citations are hand-written and often point at the start of a passage
#: rather than the caption paragraph the sentence landed in, so this is generous.
PAGE_TIMESTAMP_TOLERANCE_S = 90

#: How far past the last caption marker a citation may point before the timestamp is
#: called nonexistent. Covers the tail of the final paragraph.
TRANSCRIPT_TAIL_SLACK_S = 120

QUOTE_DISPLAY_CHARS = 100


@dataclass
class QuoteIssue:
    """One failed check. `kind` is a closed vocabulary:

    ``not-verbatim``       the quoted text is not in the transcript
    ``timestamp-missing``  the cited timestamp does not exist in the transcript
    ``timestamp-mismatch`` the quote is real but lives somewhere else in the transcript
    ``no-transcript``      a transcript was expected for this source and is not usable
    """

    kind: str
    file: str
    source: str
    timestamp: str
    quote: str
    detail: str


# ---------------------------------------------------------------------------
# Text normalization
#
# Applied to both sides of every comparison. Representation only: whitespace shape,
# quote glyphs, dash glyphs. Never spelling, never grammar, never disfluencies.
# ---------------------------------------------------------------------------

_TRANSLATE = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2033: '"',
    0x2013: "-", 0x2014: "-", 0x2212: "-", 0x2010: "-",
    0x00A0: " ", 0x200B: "",
    0x2026: "...",  # elision gets one spelling, so `_segments` has one thing to split on
}

_WS_RE = re.compile(r"\s+")


def _normalize(text: object) -> str:
    """Collapse representational differences. Line wrapping in a page and line
    wrapping in a transcript are not disagreements about what was said."""
    out = unicodedata.normalize("NFKC", str(text)).translate(_TRANSLATE)
    return _WS_RE.sub(" ", out).strip()


def _fold(text: str) -> str:
    """Lowercase, length-preserving. Offsets into a folded string must still index the
    unfolded one — `str.lower()` does not guarantee that for every code point."""
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


def _truncate(text: str, limit: int = QUOTE_DISPLAY_CHARS) -> str:
    text = _normalize(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _seconds(stamp: object) -> Optional[int]:
    try:
        return store.parse_hhmmss(str(stamp))
    except (ValueError, AttributeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(r"^\s*\[(\d{1,3}:\d{2}(?::\d{2})?)\]\s*")


@dataclass
class _Transcript:
    """A raw transcript flattened into one searchable string, plus the offset table
    needed to say which caption paragraph any match landed in."""

    path: Path
    flat: str
    folded: str
    starts: List[int]
    stamps: List[int]
    by_stamp: Dict[int, List[int]]

    def paragraph_at(self, offset: int) -> int:
        idx = bisect.bisect_right(self.starts, offset) - 1
        return max(0, min(idx, len(self.starts) - 1))

    def paragraphs_spanning(self, start: int, end: int) -> List[int]:
        first = self.paragraph_at(start)
        last = self.paragraph_at(max(start, end - 1))
        return list(range(first, last + 1))

    def stamp_at(self, index: int) -> int:
        if not self.stamps:
            return 0
        index = max(0, min(index, len(self.stamps) - 1))
        return self.stamps[index]

    @property
    def last_stamp(self) -> int:
        return self.stamps[-1] if self.stamps else 0


def _parse_transcript(path: Path) -> Tuple[Optional[_Transcript], str]:
    """Return (transcript, reason-if-none). Never raises."""
    body: Optional[str] = None
    try:
        _, body = store.read_md(path)
    except Exception:  # malformed YAML header, encoding trouble — fall back to text
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return None, f"cannot read transcript: {exc}"
    if body is None:
        return None, "cannot read transcript"

    paragraphs: List[List] = []
    for line in body.splitlines():
        match = _MARKER_RE.match(line)
        if match:
            seconds = _seconds(match.group(1))
            if seconds is None:
                continue
            paragraphs.append([seconds, line[match.end():]])
        elif paragraphs and line.strip():
            # A wrapped continuation of the paragraph above it.
            paragraphs[-1][1] += " " + line.strip()

    if not paragraphs:
        return None, "transcript contains no [HH:MM:SS] markers"

    parts: List[str] = []
    starts: List[int] = []
    stamps: List[int] = []
    by_stamp: Dict[int, List[int]] = {}
    cursor = 0
    for seconds, text in paragraphs:
        norm = _normalize(text)
        if not norm:
            continue
        starts.append(cursor)
        cursor += len(norm) + 1  # +1 for the space `" ".join` will insert
        by_stamp.setdefault(seconds, []).append(len(stamps))
        stamps.append(seconds)
        parts.append(norm)

    if not parts:
        return None, "transcript has markers but no text"

    flat = " ".join(parts)
    return _Transcript(
        path=path,
        flat=flat,
        folded=_fold(flat),
        starts=starts,
        stamps=stamps,
        by_stamp=by_stamp,
    ), ""


# ---------------------------------------------------------------------------
# Searching
# ---------------------------------------------------------------------------


def _occurrences(haystack: str, needle: str, limit: int = 64) -> List[int]:
    found: List[int] = []
    start = 0
    while len(found) < limit:
        index = haystack.find(needle, start)
        if index < 0:
            break
        found.append(index)
        start = index + 1
    return found


def _nearest(transcript: _Transcript, positions: Sequence[int],
             target_s: Optional[int]) -> int:
    """Of several occurrences, the one closest to where the citation says it is.
    A phrase repeated later in a talk must not be reported as a timestamp error."""
    if target_s is None or len(positions) == 1:
        return positions[0]
    return min(positions,
               key=lambda p: abs(transcript.stamp_at(transcript.paragraph_at(p)) - target_s))


def _longest_prefix(haystack: str, needle: str) -> int:
    """Characters of `needle` that do appear, as a prefix, in `haystack`. Turns a bare
    'not found' into 'drifts after the first 60 characters', which is the difference
    between a usable report and a shrug."""
    low, high = 0, len(needle)
    while low < high:
        mid = (low + high + 1) // 2
        if needle[:mid] in haystack:
            low = mid
        else:
            high = mid - 1
    return low


def _divergence_detail(haystack: str, needle: str) -> str:
    matched = _longest_prefix(haystack, needle)
    if matched == 0:
        return "no part of the quote appears in the transcript"
    tail = needle[matched:matched + 40].strip()
    return f"matches for {matched} chars, then diverges at “{tail}…”"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _kb_rel(config, path: object) -> str:
    """KB-relative where possible. Candidates live outside the KB by design, so fall
    back to the KB's parent before giving up and printing an absolute path."""
    path = Path(path)
    try:
        resolved = path.resolve()
    except OSError:
        return str(path)
    for base in (Path(config.kb), Path(config.kb).parent):
        try:
            return str(resolved.relative_to(base.resolve()))
        except (ValueError, OSError):
            continue
    return str(resolved)


def _under(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except (ValueError, OSError):
        return False


class _Cache:
    """Per-run memo. Transcripts are parsed once even when fifty pages cite them."""

    def __init__(self) -> None:
        self.transcripts: Dict[str, Tuple[Optional[_Transcript], str]] = {}
        self.sources: Dict[str, dict] = {}

    def transcript(self, path: Path) -> Tuple[Optional[_Transcript], str]:
        key = str(path)
        if key not in self.transcripts:
            if not path.is_file():
                self.transcripts[key] = (None, "transcript file does not exist")
            else:
                self.transcripts[key] = _parse_transcript(path)
        return self.transcripts[key]

    def source_meta(self, path: Path) -> dict:
        key = str(path)
        if key not in self.sources:
            try:
                meta, _ = store.read_md(path)
            except Exception:  # unreadable frontmatter is the linter's problem
                meta = {}
            self.sources[key] = meta
        return self.sources[key]


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def _candidate_transcript_path(config, path: Path, slug: str) -> Optional[Path]:
    raw_dir = Path(config.raw_dir)
    if slug:
        guess = raw_dir / (slug + ".md")
        if guess.is_file():
            return guess
    matches = sorted(raw_dir.rglob(path.stem + ".md")) if raw_dir.is_dir() else []
    if len(matches) == 1:
        return matches[0]
    if slug:
        return raw_dir / (slug + ".md")  # report the path we expected, missing or not
    return matches[0] if matches else None


def verify_candidates(config) -> List[QuoteIssue]:
    """Check every `candidates/*.json` against the transcript it was extracted from.

    Candidates are machine output, so this pass is strict. For each entry in
    `concepts[]`:

    - `verbatim_quote` must be a literal substring of `raw/<channel>/<stem>.md`
      (after whitespace/glyph normalization of both sides, nothing more);
    - `timestamp` must be a caption marker that actually exists in that file;
    - the quote must fall inside that marker's paragraph — a quote lifted from the
      neighbouring paragraph is a real defect, since the timestamp is the thing that
      lets a reader go check.

    Entries with no `verbatim_quote` are skipped: not every extracted concept claims
    to be quoting. A candidate JSON that will not parse, or whose `concepts` key is
    not a list, is skipped silently — that is malformed tooling output, not a false
    citation, and inventing a `kind` for it would pollute a vocabulary that callers
    switch on.
    """
    issues: List[QuoteIssue] = []
    directory = Path(config.candidates)
    if not directory.is_dir():
        return issues

    cache = _Cache()
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        entries = data.get("concepts")
        if not isinstance(entries, list):
            continue

        slug = str(data.get("slug") or "").strip().strip("/")
        file_rel = _kb_rel(config, path)
        quoted = [e for e in entries
                  if isinstance(e, dict) and str(e.get("verbatim_quote") or "").strip()]
        if not quoted:
            continue

        raw_path = _candidate_transcript_path(config, path, slug)
        transcript, reason = (None, "no matching transcript under raw/")
        if raw_path is not None:
            transcript, reason = cache.transcript(raw_path)
        if transcript is None:
            issues.append(QuoteIssue(
                kind="no-transcript",
                file=file_rel,
                source=slug or path.stem,
                timestamp="",
                quote="",
                detail="{0} ({1} quote(s) unverifiable): {2}".format(
                    _kb_rel(config, raw_path) if raw_path else "raw/?", len(quoted), reason),
            ))
            continue

        for entry in quoted:
            issues.extend(_check_candidate_entry(
                config, entry, transcript, file_rel, slug or path.stem))
    return issues


def _check_candidate_entry(config, entry: dict, transcript: _Transcript,
                           file_rel: str, source: str) -> List[QuoteIssue]:
    issues: List[QuoteIssue] = []
    quote = _normalize(entry.get("verbatim_quote"))
    if not quote:  # a quote of nothing matches everything; there is nothing to check
        return issues
    stamp = str(entry.get("timestamp") or "").strip()
    display = _truncate(quote)
    where = _kb_rel(config, transcript.path)
    target_s = _seconds(stamp) if stamp else None

    positions = _occurrences(transcript.flat, quote)
    if not positions:
        issues.append(QuoteIssue(
            kind="not-verbatim",
            file=file_rel,
            source=source,
            timestamp=stamp,
            quote=display,
            detail=f"not found in {where}: {_divergence_detail(transcript.flat, quote)}",
        ))

    if not stamp:
        issues.append(QuoteIssue(
            kind="timestamp-missing",
            file=file_rel,
            source=source,
            timestamp="",
            quote=display,
            detail="entry has a quote but no timestamp",
        ))
        return issues

    if target_s is None:
        issues.append(QuoteIssue(
            kind="timestamp-missing",
            file=file_rel,
            source=source,
            timestamp=stamp,
            quote=display,
            detail="timestamp is not HH:MM:SS",
        ))
        return issues

    marker_indices = transcript.by_stamp.get(target_s)
    if not marker_indices:
        issues.append(QuoteIssue(
            kind="timestamp-missing",
            file=file_rel,
            source=source,
            timestamp=stamp,
            quote=display,
            detail=f"no [{store.hhmmss(target_s)}] marker in {where}",
        ))
        return issues

    if not positions:
        return issues  # already reported as not-verbatim; location is meaningless

    best = _nearest(transcript, positions, target_s)
    spanned = transcript.paragraphs_spanning(best, best + len(quote))
    if not any(index in spanned for index in marker_indices):
        actual = transcript.stamp_at(spanned[0])
        issues.append(QuoteIssue(
            kind="timestamp-mismatch",
            file=file_rel,
            source=source,
            timestamp=stamp,
            quote=display,
            detail="quote sits in the [{0}] paragraph of {1} ({2:+d}s from the cited "
                   "timestamp)".format(store.hhmmss(actual), where, actual - target_s),
        ))
    return issues


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

#: ([Short title](../sources/<channel>/<slug>.md) @ 00:14:32) — optionally a range.
_CITATION_RE = re.compile(
    r"\(\s*\[(?P<title>[^\]\n]*)\]\((?P<path>[^)\s]+\.md)\)\s*@\s*"
    r"(?P<stamp>\d{1,3}:\d{2}(?::\d{2})?)"
    r"(?:\s*[-–—]\s*\d{1,3}:\d{2}(?::\d{2})?)?\s*\)"
)

_MD_LINK_RE = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
_MD_EMPHASIS_RE = re.compile(r"[*`]+")
_QUOTED_RE = re.compile(r'"([^"]+)"')
_BLOCK_START_RE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|\|)")
_ATTRIBUTION_RE = re.compile(r"\s-\s[^.?!\"]{0,60}$")


def _strip_markdown(text: str) -> str:
    return _MD_EMPHASIS_RE.sub("", _MD_LINK_RE.sub(r"\1", text))


def _paragraph_lines(lines: Sequence[str], index: int) -> Tuple[List[str], bool]:
    """The contiguous run of non-blank lines ending at `index`. Returns the lines and
    whether the whole run is a blockquote."""
    start = index
    while start > 0:
        previous = lines[start - 1]
        if not previous.strip():
            break
        if _BLOCK_START_RE.match(lines[start]) and not lines[start].lstrip().startswith(">"):
            break  # `lines[start]` opens a list item / heading: the paragraph starts here
        if previous.lstrip().startswith("#"):
            break
        start -= 1
    block = list(lines[start:index + 1])
    is_quote = all(line.lstrip().startswith(">") for line in block if line.strip())
    return block, is_quote


def _quotation_before(block: Sequence[str], is_quote: bool,
                      citation_text: str) -> Optional[str]:
    """The text this citation is citing, or None when we cannot tell.

    Two shapes are recognized, and only two:
      1. a `>` blockquote whose citation sits inside it;
      2. double-quoted text in the same paragraph, ending before the citation.
    Everything else is paraphrase, and paraphrase is not checkable.
    """
    cleaned = []
    for line in block:
        stripped = line.lstrip()
        if stripped.startswith(">"):
            stripped = stripped[1:].lstrip()
        cleaned.append(stripped)
    text = _WS_RE.sub(" ", _strip_markdown(" ".join(cleaned)))
    needle = _WS_RE.sub(" ", _strip_markdown(citation_text))
    if needle not in text:
        # The citation is not where we thought it was (a table cell, an odd wrap).
        # Guessing which text it attaches to is exactly how false positives are made.
        return None
    head = text.split(needle)[0]

    if head.count('"') % 2 == 1:
        # An unbalanced quote means the paragraph continues a quotation opened
        # elsewhere, and any pairing we infer would be guesswork.
        return None

    spans = _QUOTED_RE.findall(head)
    if spans:
        return _normalize(spans[-1])

    if is_quote:
        # A blockquote with no quote marks is itself the quotation. Trim a trailing
        # "— speaker" attribution, which is editorial, not spoken.
        body = _normalize(head)
        body = _ATTRIBUTION_RE.sub("", body).strip()
        return body or None
    return None


def _segments(quote: str) -> List[str]:
    """Split an elided quote at its ellipses. Each surviving fragment is checked
    independently and in order; fragments too short to be distinctive are dropped."""
    parts = [p.strip(" ,;:-") for p in quote.split("...")]
    return [p for p in parts if len(p.split()) >= MIN_SEGMENT_WORDS]


def _source_slug(config, source_path: Path, meta: dict) -> str:
    slug = str(meta.get("slug") or "").strip()
    if slug:
        return slug
    try:
        rel = source_path.resolve().relative_to(Path(config.sources).resolve())
        return str(rel.with_suffix(""))
    except (ValueError, OSError):
        return source_path.stem


def _expected_transcript(source_path: Path, meta: dict) -> Tuple[Optional[Path], bool]:
    """(path, expected). A hand-written page or an article has no transcript and that
    is not a defect; only a declared video is expected to have one."""
    raw_value = str(meta.get("raw") or "").strip()
    if raw_value:
        candidate = Path(raw_value)
        if not candidate.is_absolute():
            candidate = source_path.parent / candidate
        return candidate, True
    if str(meta.get("source_type") or "").strip().lower() == "video":
        return None, True
    return None, False


def verify_pages(config) -> List[QuoteIssue]:
    """Check quotations on KB pages against the transcripts they cite.

    For every citation of the form
    `([Short title](../sources/<channel>/<slug>.md) @ 00:14:32)` it resolves the source
    page, reads its `raw:` frontmatter field to find the transcript, extracts the
    quotation the citation is attached to, and confirms that text appears in the
    transcript near that timestamp.

    **What it checks**

    - Text inside double quotes in the citation's own paragraph, ending before the
      citation. The nearest such span is the one tested.
    - A `>` blockquote containing the citation, with a trailing "— attribution"
      clause trimmed.
    - Elided quotes: the text is split at `...` and each fragment of four or more
      words must appear, in order.
    - `not-verbatim` when the quotation is absent from the transcript;
      `timestamp-mismatch` when it is present but more than
      `PAGE_TIMESTAMP_TOLERANCE_S` seconds away from the cited moment (measured
      against the *closest* occurrence, so a phrase repeated later in a talk is not
      reported); `timestamp-missing` only when the citation points past the end of
      the transcript; `no-transcript` when a source declares `raw:` that is unreadable
      or missing, or declares `source_type: video` with no `raw:` at all.

    **What it deliberately does not attempt** — every one of these is a place where a
    naive checker would generate a false accusation, and a checker nobody trusts is
    worth less than no checker:

    - *Paraphrase.* A citation with no quotation marks attached asserts provenance,
      not wording. Untouched.
    - *Bare continuation citations* like `(@ 00:19:10)` with no source link. The
      intended source is almost certainly the one cited above, but "almost certainly"
      is how false positives get made. Skipped.
    - *Short quotations* — under 40 characters or 6 words. Those are usually terms of
      art in scare quotes ("jagged intelligence"), which are being named, not quoted.
    - *Unbalanced quote marks.* If a paragraph has an odd number of `"`, the quotation
      opened somewhere this checker cannot see, so no pairing is inferred.
    - *Sources with no transcript* — articles, threads, hand-written pages. Not
      failures, and not reported.
    - *Broken source links and missing frontmatter.* Those are the linter's job; this
      module stays silent rather than duplicating its errors under different names.
    - *Timestamp precision.* Page citations are written by hand against a video
      player, not snapped to caption-paragraph boundaries, so an exact marker is never
      required — only that the quote turns up somewhere in the neighbourhood.
    - *Accuracy of the claim around the quote.* Whether the page's surrounding
      sentence fairly represents what the speaker meant is a semantic question and
      remains a human review.

    Comparison is whitespace- and glyph-normalized on both sides and case-insensitive;
    nothing else about either text is altered.
    """
    issues: List[QuoteIssue] = []
    kb = Path(config.kb)
    if not kb.is_dir():
        return issues

    raw_dir = Path(config.raw_dir)
    candidates_dir = Path(config.candidates)
    cache = _Cache()
    reported_missing: set = set()

    for page in store.iter_md(kb):
        if _under(page, raw_dir) or _under(page, candidates_dir):
            continue
        try:
            text = page.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "@" not in text:
            continue
        lines = text.splitlines()
        line_starts = _line_offsets(lines)
        file_rel = _kb_rel(config, page)

        for match in _CITATION_RE.finditer(text):
            issues.extend(_check_citation(
                config, cache, page, file_rel, lines, line_starts, match,
                reported_missing))
    return issues


def _line_offsets(lines: Sequence[str]) -> List[int]:
    offsets: List[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1
    return offsets


def _check_citation(config, cache: _Cache, page: Path, file_rel: str,
                    lines: Sequence[str], line_starts: Sequence[int],
                    match, reported_missing: set) -> List[QuoteIssue]:
    issues: List[QuoteIssue] = []
    stamp = match.group("stamp")
    target_s = _seconds(stamp)

    source_path = (page.parent / match.group("path")).resolve()
    if not source_path.is_file():
        return issues  # dangling link: kb_lint reports it, we do not double-report

    meta = cache.source_meta(source_path)
    source = _source_slug(config, source_path, meta)
    raw_path, expected = _expected_transcript(source_path, meta)
    if not expected:
        return issues

    line_index = max(0, bisect.bisect_right(line_starts, match.start()) - 1)
    # A citation can wrap across a line break; gather the paragraph through its last
    # line so the citation text is whole inside the block we search.
    last_line = max(line_index,
                    max(0, bisect.bisect_right(line_starts, max(0, match.end() - 1)) - 1))
    location = f"{file_rel}:{line_index + 1}"

    if raw_path is None:
        key = (source, "no-raw")
        if key not in reported_missing:
            reported_missing.add(key)
            issues.append(QuoteIssue(
                kind="no-transcript", file=location, source=source, timestamp=stamp,
                quote="", detail="source declares source_type: video but has no raw: field",
            ))
        return issues

    transcript, reason = cache.transcript(raw_path)
    if transcript is None:
        key = (source, reason)
        if key not in reported_missing:
            reported_missing.add(key)
            issues.append(QuoteIssue(
                kind="no-transcript", file=location, source=source, timestamp=stamp,
                quote="", detail=f"{_kb_rel(config, raw_path)}: {reason}",
            ))
        return issues

    where = _kb_rel(config, transcript.path)

    # A citation pointing past the end of the recording is wrong whether or not it
    # carries a quotation — that check does not depend on identifying quoted text.
    if target_s is not None and target_s > transcript.last_stamp + TRANSCRIPT_TAIL_SLACK_S:
        issues.append(QuoteIssue(
            kind="timestamp-missing", file=location, source=source, timestamp=stamp,
            quote="", detail=f"{where} ends at [{store.hhmmss(transcript.last_stamp)}]",
        ))
        return issues

    block, is_quote = _paragraph_lines(lines, last_line)
    quotation = _quotation_before(block, is_quote, match.group(0))
    if not quotation:
        return issues
    if len(quotation) < MIN_PAGE_QUOTE_CHARS or len(quotation.split()) < MIN_PAGE_QUOTE_WORDS:
        return issues

    segments = _segments(quotation)
    if not segments:
        return issues

    display = _truncate(quotation)
    haystack = transcript.folded
    first = _fold(segments[0])
    positions = _occurrences(haystack, first)
    if not positions:
        issues.append(QuoteIssue(
            kind="not-verbatim", file=location, source=source, timestamp=stamp,
            quote=display,
            detail="not found in {0}: {1}".format(
                where, _divergence_detail(haystack, first)),
        ))
        return issues

    anchor = _nearest(transcript, positions, target_s)
    cursor = anchor + len(first)
    end = cursor
    for index, segment in enumerate(segments[1:], start=2):
        folded = _fold(segment)
        found = haystack.find(folded, cursor)
        if found < 0:
            issues.append(QuoteIssue(
                kind="not-verbatim", file=location, source=source, timestamp=stamp,
                quote=display,
                detail="fragment {0} of the elided quote is not in {1} after the "
                       "first: {2}".format(
                           index, where, _divergence_detail(haystack[cursor:], folded)),
            ))
            return issues
        cursor = found + len(folded)
        end = cursor

    if target_s is None:
        return issues

    spanned = transcript.paragraphs_spanning(anchor, end)
    starts_at = transcript.stamp_at(spanned[0])
    ends_at = transcript.stamp_at(spanned[-1])
    low = starts_at - PAGE_TIMESTAMP_TOLERANCE_S
    high = ends_at + PAGE_TIMESTAMP_TOLERANCE_S
    if low <= target_s <= high:
        return issues

    issues.append(QuoteIssue(
        kind="timestamp-mismatch", file=location, source=source, timestamp=stamp,
        quote=display,
        detail="quote appears at [{0}] in {1} ({2:+d}s from the cited "
               "timestamp)".format(store.hhmmss(starts_at), where, starts_at - target_s),
    ))
    return issues


# ---------------------------------------------------------------------------


def verify(config) -> List[QuoteIssue]:
    """Both passes. Candidates first — a defect there is upstream of the page it
    would become, and fixing it in order avoids chasing the same quote twice."""
    return verify_candidates(config) + verify_pages(config)
