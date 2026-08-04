"""
ugraph-kit — build an agent-navigable knowledge base from a YouTube channel.

Plain markdown, YAML frontmatter, relative links. No database, no embeddings. An agent
reads an index, follows links to the few pages it needs, and cites a timestamp in an
immutable transcript.

The format is the Open Knowledge Format, originated by Cole Medin
(github.com/coleam00/cole-medin-knowledge-base). This package is an independent
implementation of it as a reusable tool; divergences are marked OKF-v in SCHEMA.md.

Library entry points:

    from ugraph import config, indexes, lint, status, verify
    from ugraph.sources import youtube

    cfg = config.load(kb="~/vault/knowledge")
    youtube.ingest(cfg, "https://youtube.com/@example", limit=25)
    indexes.write_all(cfg)
    findings, pages = lint.lint(cfg)
    issues = verify.verify(cfg)
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
