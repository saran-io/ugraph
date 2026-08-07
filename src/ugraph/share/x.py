"""X (Twitter) share adapter — OAuth 1.0a user context, create-post only.

Uses POST https://api.x.com/2/tweets. App-only bearer tokens cannot create posts;
this adapter requires the four user-context secrets from the X developer portal.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ugraph.share import receipts
from ugraph.share.draft import ShareDraft, ShareError, ShareResult
from ugraph.share.secrets import get_x_credentials

CREATE_URL = "https://api.x.com/2/tweets"
MAX_CHARS = 280


def _pct(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


def _oauth_header(method: str, url: str, creds: dict[str, str]) -> str:
    """Build an OAuth 1.0a Authorization header for a JSON body request.

    JSON bodies are not signed parameter bags — only the oauth_* fields and any
    query string participate. That matches X's manage-Posts guidance.
    """
    parsed = urllib.parse.urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))

    oauth: dict[str, str] = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    params = {**query, **oauth}
    param_str = "&".join(
        f"{_pct(k)}={_pct(params[k])}" for k in sorted(params)
    )
    base = "&".join([method.upper(), _pct(base_url), _pct(param_str)])
    signing_key = f"{_pct(creds['api_secret'])}&{_pct(creds['access_token_secret'])}"
    digest = hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(digest).decode()

    ordered = ", ".join(
        f'{_pct(k)}="{_pct(oauth[k])}"'
        for k in (
            "oauth_consumer_key",
            "oauth_nonce",
            "oauth_signature",
            "oauth_signature_method",
            "oauth_timestamp",
            "oauth_token",
            "oauth_version",
        )
    )
    return f"OAuth {ordered}"


def validate_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise ShareError("nothing to share — text is empty")
    # X counts most BMP characters as 1; URLs are weighted separately. For v1 we
    # enforce a hard 280 on the raw string — better to refuse than silently truncate.
    if len(text) > MAX_CHARS:
        raise ShareError(
            f"text is {len(text)} characters; X limit is {MAX_CHARS}. "
            "Shorten it, then retry."
        )
    return text


def _create(text: str, creds: dict[str, str]) -> dict[str, Any]:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        CREATE_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": _oauth_header("POST", CREATE_URL, creds),
            "Content-Type": "application/json",
            "User-Agent": "ugraph-kit/0.1 (+https://ugraph.build)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        # Never echo Authorization headers; urllib's error body is enough.
        if exc.code in (401, 403):
            raise ShareError(
                f"X rejected the credentials (HTTP {exc.code}).\n"
                "  Check that the app has Read and Write permissions and that\n"
                "  `ugraph x auth set` used user access tokens, not an app-only bearer.\n"
                f"  detail: {detail}"
            ) from exc
        if exc.code == 429:
            raise ShareError(
                "X rate limit reached. Wait and retry later."
            ) from exc
        raise ShareError(f"X API error HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ShareError(f"could not reach X API: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ShareError("X returned non-JSON") from exc
    post = (data.get("data") or {})
    post_id = str(post.get("id") or "")
    if not post_id:
        raise ShareError(f"X response missing post id: {body[:200]}")
    if status not in (200, 201):
        raise ShareError(f"unexpected X status {status}")
    return post


def post(draft: ShareDraft, *, dry_run: bool = False) -> ShareResult:
    """Publish a text draft to X, or simulate with dry_run."""
    draft = draft.normalized()
    if draft.media:
        raise ShareError("media attachments are not supported in ugraph x v1")
    text = validate_text(draft.text)

    if dry_run:
        result = ShareResult(
            destination="x",
            post_id="dry-run",
            url="https://x.com/i/web/status/dry-run",
            text=text,
            dry_run=True,
        )
        receipts.record("x", result.post_id, result.url, text, dry_run=True)
        return result

    creds = get_x_credentials()
    post_data = _create(text, creds)
    post_id = str(post_data["id"])
    url = f"https://x.com/i/web/status/{post_id}"
    result = ShareResult(destination="x", post_id=post_id, url=url, text=text)
    receipts.record("x", post_id, url, text, dry_run=False)
    return result
