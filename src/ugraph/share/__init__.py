"""Outbound sharing — never part of the knowledge ingest path.

See docs/adr/0002-share-boundary.md for the product contract.
"""

from ugraph.share.draft import ShareDraft, ShareError, ShareResult
from ugraph.share.x import post as post_x

__all__ = ["ShareDraft", "ShareError", "ShareResult", "post_x"]
