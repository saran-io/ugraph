"""
cli.py — the `okf` command.

Deliberately thin. Every subcommand resolves a Config, calls one library function, and
formats the result. Logic that lives here cannot be tested or reused, so it does not live
here.

Exit codes matter: `lint`, `verify`, and `index --check` are meant to be usable as CI
gates, so they exit non-zero on failure and stay quiet on success.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from okf import __version__
from okf import config as config_mod

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _config(args) -> config_mod.Config:
    try:
        return config_mod.load(kb=getattr(args, "kb", None))
    except config_mod.ConfigError as exc:
        sys.exit(f"okf: {exc}")


def _bundled(name: str) -> Path:
    """Locate a directory shipped inside the wheel (skills/, templates/)."""
    packaged = Path(__file__).parent / "_bundled" / name
    if packaged.is_dir():
        return packaged
    # Running from a source checkout rather than an installed wheel.
    repo = Path(__file__).resolve().parents[2] / name
    if repo.is_dir():
        return repo
    sys.exit(f"okf: cannot locate bundled {name}/ — is the install complete?")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    root = Path(args.path).expanduser().resolve()
    templates = _bundled("templates")

    existing = [p for p in (root / "SCHEMA.md", root / "taxonomy.json") if p.exists()]
    if existing and not args.force:
        print(f"okf: {root} already looks like a knowledge base.")
        for p in existing:
            print(f"  exists: {p.name}")
        print("  use --force to overwrite the scaffold (content is never touched)")
        return 1

    for rel in config_mod.CONTENT_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    for name in ("SCHEMA.md", "taxonomy.json"):
        shutil.copy2(templates / name, root / name)

    cfg_path = root.parent / config_mod.CONFIG_FILENAME
    if not cfg_path.exists():
        cfg_path.write_text(f'kb = "{root.name}"\n', encoding="utf-8")

    from okf import indexes
    cfg = config_mod.load(kb=root)
    indexes.write_all(cfg)

    print(f"Initialized knowledge base at {root}")
    print(f"  wrote SCHEMA.md, taxonomy.json, {len(config_mod.CONTENT_DIRS)} directories")
    print(f"  wrote {cfg_path}")
    print()
    print("Next:")
    print("  okf ingest youtube <channel-url> --limit 25")
    print("  okf skills install        # agent instructions for the extraction pass")
    return 0


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def cmd_ingest(args) -> int:
    cfg = _config(args)
    if args.source != "youtube":
        sys.exit(f"okf: unknown source '{args.source}' (only 'youtube' so far)")

    from okf.sources import youtube

    def progress(i, total, vid, title):
        print(f"[{i}/{total}] {vid}  {title[:58]}")

    try:
        result = youtube.ingest(
            cfg, args.url,
            limit=args.limit, slug=args.slug, dry_run=args.dry_run,
            sleep=args.sleep, force=args.force, progress=progress,
        )
    except FileNotFoundError as exc:
        sys.exit(f"okf: {exc}")
    except RuntimeError as exc:
        sys.exit(f"okf: {exc}")

    if args.dry_run:
        for v in result.get("videos", []):
            print(f"  {v['id']}  {v.get('title', '')[:70]}")
        print(f"\n{len(result.get('videos', []))} video(s) would be ingested.")
        return 0

    for warning in result.get("warnings", []):
        print(f"  [warn] {warning}")
    print(f"\nIngested {result['written']}, skipped {result['skipped']}. "
          f"{result['total_ingested']}/{result['listed']} of the listing now in the KB.")
    print("Next: okf index && okf lint")
    return 0


# ---------------------------------------------------------------------------
# index / lint / verify / status
# ---------------------------------------------------------------------------

def cmd_index(args) -> int:
    from okf import indexes
    cfg = _config(args)
    if args.check:
        stale = indexes.check(cfg)
        if stale:
            print("Stale indexes (run `okf index`):")
            for p in stale:
                print(f"  {p.relative_to(cfg.kb)}")
            return 1
        print("All indexes up to date.")
        return 0
    written = indexes.write_all(cfg)
    if written:
        print(f"Rebuilt {len(written)} index file(s):")
        for p in written:
            print(f"  {p.relative_to(cfg.kb)}")
    else:
        print("All indexes already current.")
    return 0


def cmd_lint(args) -> int:
    from okf import lint as lint_mod
    cfg = _config(args)
    findings, pages = lint_mod.lint(cfg)

    if args.json:
        print(json.dumps({
            "status": "fail" if findings.errors else "pass",
            "pages": len(pages),
            "errors": findings.errors,
            "warnings": findings.warnings,
        }, indent=2))
    else:
        for item in findings.errors:
            print(f"ERROR  [{item['check']}] {item['file']}: {item['message']}")
        if not args.quiet:
            for item in findings.warnings:
                print(f"WARN   [{item['check']}] {item['file']}: {item['message']}")
        verdict = "FAIL" if findings.errors else "PASS"
        print(f"\n{verdict} — {len(pages)} pages, "
              f"{len(findings.errors)} error(s), {len(findings.warnings)} warning(s)")

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(lint_mod.render_report(findings, pages), encoding="utf-8")
        print(f"Report written to {out}")

    return 1 if findings.errors or (args.warnings and findings.warnings) else 0


def cmd_verify(args) -> int:
    from okf import verify as verify_mod
    cfg = _config(args)

    if args.pages_only:
        issues = verify_mod.verify_pages(cfg)
    elif args.candidates_only:
        issues = verify_mod.verify_candidates(cfg)
    else:
        issues = verify_mod.verify(cfg)

    if args.json:
        print(json.dumps([i.__dict__ for i in issues], indent=2))
        return 1 if issues else 0

    for issue in issues:
        print(f"{issue.kind.upper():<20} {issue.file}")
        print(f"  @{issue.timestamp}  {issue.detail}")
        if issue.quote:
            print(f"  quote: {issue.quote}")
    if issues:
        print(f"\nFAIL — {len(issues)} quote/timestamp issue(s)")
        return 1
    print("PASS — every quote is verbatim and every timestamp resolves.")
    return 0


def cmd_status(args) -> int:
    from okf import status as status_mod
    cfg = _config(args)
    stats = status_mod.collect(cfg)
    if args.json:
        print(json.dumps(stats, indent=2, default=str))
        return 0
    print(status_mod.render(stats, clusters=args.clusters,
                            pending=args.pending, thin=args.thin))
    return 0


def cmd_graph(args) -> int:
    from okf import graph as graph_mod
    cfg = _config(args)
    types = {"concept", "entity", "moc"} if args.concepts_only else None
    g = graph_mod.build(cfg, include_provenance=not args.no_provenance, types=types)
    try:
        if args.format == "d3":
            rendered = graph_mod.to_d3(g)
        else:
            rendered = graph_mod.render(g, args.format, config=cfg)
    except ValueError as exc:
        sys.exit(f"okf: {exc}")

    if args.format == "canvas" and graph_mod.find_vault_root(cfg) is None:
        print("  [warn] no .obsidian found above the KB — canvas file paths may not "
              "resolve. Open the .canvas from inside your vault.", file=sys.stderr)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        print(f"{len(g['nodes'])} nodes, {len(g['edges'])} edges → {out}")
    else:
        print(rendered)
    return 0


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------

def cmd_skills(args) -> int:
    if args.action != "install":
        sys.exit("okf: only `okf skills install` is supported")
    src = _bundled("skills")
    dest = Path(args.dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for item in src.iterdir():
        target = dest / item.name
        if target.exists() and not args.force:
            print(f"  skip (exists): {target}")
            continue
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
        copied.append(target)
    for p in copied:
        print(f"  installed: {p}")
    print(f"\n{len(copied)} skill(s) installed to {dest}")
    print("In Claude Code, run:  /channel-to-kb")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="okf",
        description="Build an agent-navigable knowledge base from a YouTube channel.",
    )
    p.add_argument("--version", action="version", version=f"okf-kit {__version__}")
    p.add_argument("--kb", metavar="PATH",
                   help="knowledge base root (default: okf.toml, $OKF_KB, or cwd)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="scaffold a new knowledge base")
    sp.add_argument("path")
    sp.add_argument("--force", action="store_true", help="overwrite an existing scaffold")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("ingest", help="fetch source material")
    sp.add_argument("source", choices=["youtube"])
    sp.add_argument("url")
    sp.add_argument("--limit", type=int, default=10, help="max NEW items this run")
    sp.add_argument("--slug", help="override the channel slug")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--sleep", type=float, default=1.5,
                    help="seconds between fetches; raise it if you hit rate limits")
    sp.add_argument("--force", action="store_true", help="re-fetch items already recorded")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("index", help="regenerate every index.md")
    sp.add_argument("--check", action="store_true", help="exit 1 if stale; write nothing")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("lint", help="conformance gate")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--quiet", action="store_true", help="errors only")
    sp.add_argument("--warnings", action="store_true", help="treat warnings as failure")
    sp.add_argument("--report", metavar="PATH", help="also write a markdown report")
    sp.set_defaults(func=cmd_lint)

    sp = sub.add_parser("verify", help="every quote verbatim, every timestamp real")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--candidates-only", action="store_true")
    sp.add_argument("--pages-only", action="store_true")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("status", help="extraction progress and graph health")
    sp.add_argument("--clusters", action="store_true")
    sp.add_argument("--pending", action="store_true")
    sp.add_argument("--thin", action="store_true", help="single-source concepts")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("graph", help="export the KB as a graph (derived view)")
    sp.add_argument("--format", default="json",
                    choices=["json", "graphml", "dot", "canvas", "obsidian-groups", "d3"],
                    help="canvas = Obsidian Canvas; d3 = standalone interactive HTML")
    sp.add_argument("--out", metavar="PATH", help="write to a file instead of stdout")
    sp.add_argument("--no-provenance", action="store_true",
                    help="drop concept→source edges; clearer for diagramming")
    sp.add_argument("--concepts-only", action="store_true",
                    help="concepts, entities and MOCs only — sources usually "
                         "outnumber them and swamp a visual")
    sp.set_defaults(func=cmd_graph)

    sp = sub.add_parser("skills", help="install the agent instructions")
    sp.add_argument("action", choices=["install"])
    sp.add_argument("--dest", default=".claude/skills")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_skills)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        # A downstream reader closed the pipe — `okf graph | head`, `| jq .nodes[0]`.
        # That is normal usage, not an error, but Python will also try to flush stdout
        # on exit and raise a second time. Pointing the fd at devnull first is the
        # documented way to exit quietly.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 141  # 128 + SIGPIPE, what a shell expects


if __name__ == "__main__":
    raise SystemExit(main())
