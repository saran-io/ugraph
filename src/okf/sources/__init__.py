"""okf.sources — ingest adapters.

Each module in this package pulls from one kind of feed (a YouTube channel, an RSS
feed, a folder of PDFs) and lands it in the knowledge base as a pair of pages: an
immutable `raw/` capture of the original text, and a `sources/` page that describes
it. Adapters are deterministic and never invent content; turning a source into
concepts and entities is a later, LLM-driven pass.

Every adapter takes a `Config` and exposes an `ingest(...)` function that returns a
summary dict. Printing, argument parsing, and scheduling belong to the caller.
"""
