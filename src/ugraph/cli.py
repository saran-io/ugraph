"""
cli.py — the `ugraph` command.

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

from ugraph import __version__
from ugraph import config as config_mod

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _config(args) -> config_mod.Config:
    try:
        return config_mod.load(kb=getattr(args, "kb", None))
    except config_mod.ConfigError as exc:
        sys.exit(f"ugraph: {exc}")


def _bundled(name: str) -> Path:
    """Locate a directory shipped inside the wheel (skills/, templates/)."""
    packaged = Path(__file__).parent / "_bundled" / name
    if packaged.is_dir():
        return packaged
    # Running from a source checkout rather than an installed wheel.
    repo = Path(__file__).resolve().parents[2] / name
    if repo.is_dir():
        return repo
    sys.exit(f"ugraph: cannot locate bundled {name}/ — is the install complete?")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    answers = None
    if not args.path:
        from ugraph import wizard
        if not wizard.interactive():
            sys.exit("ugraph: init needs a path when not run interactively\n"
                     "  e.g.  ugraph init ./knowledge")
        answers = wizard.run()
        args.path = str(answers["kb"])

    root = Path(args.path).expanduser().resolve()
    templates = _bundled("templates")

    existing = [p for p in (root / "SCHEMA.md", root / "taxonomy.json") if p.exists()]
    if existing and not args.force:
        print(f"ugraph: {root} already looks like a knowledge base.")
        for p in existing:
            print(f"  exists: {p.name}")
        print("  use --force to overwrite the scaffold (content is never touched)")
        return 1

    # A knowledge base needs its own directory. Pointing `init` at an Obsidian vault
    # root — the obvious thing to try — used to scatter concepts/, entities/, raw/ and
    # sources/ in among the user's real folders, write an index.md that could clobber
    # an existing note, drop the config file OUTSIDE the vault, and then report every
    # personal note as a malformed page. Refuse, and say where to put it instead.
    if not args.force:
        suggestion = (root / "knowledge") if root.name != "knowledge" else (root / "kb")
        try:
            shown = suggestion.relative_to(Path.cwd())
        except ValueError:
            shown = suggestion

        # Any of the markdown note apps, not just Obsidian — a Logseq user pointing
        # init at their graph root hits exactly the same mess.
        marker = next((m for m in (".obsidian", ".logseq", ".foam")
                       if (root / m).is_dir()), None)
        if marker:
            app = {".obsidian": "an Obsidian vault", ".logseq": "a Logseq graph",
                   ".foam": "a Foam workspace"}[marker]
            print(f"ugraph: {root} is {app} root.")
            print()
            print("  A knowledge base needs its own folder inside the vault, otherwise")
            print("  its directories land beside your real notes and `ugraph lint` treats")
            print("  every note you already have as a malformed page.")
            print()
            print(f"  Try:  ugraph init {shown}")
            return 1

        strays = [p for p in root.glob("*.md")
                  if p.name not in {"SCHEMA.md", "README.md", "index.md"}]
        strays += [p for p in root.glob("*/*.md")][:1]
        if strays:
            print(f"ugraph: {root} already contains markdown files.")
            for p in strays[:4]:
                print(f"    {p.relative_to(root)}")
            if len(strays) > 4:
                print(f"    … and {len(strays) - 4} more")
            print()
            print("  A knowledge base needs an empty directory of its own — `ugraph lint`")
            print("  would report every one of these as a malformed page.")
            print()
            print(f"  Try:  ugraph init {shown}")
            print("  Or pass --force if this really is meant to be the knowledge base.")
            return 1

    for rel in config_mod.CONTENT_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    for name in ("SCHEMA.md", "taxonomy.json"):
        shutil.copy2(templates / name, root / name)

    cfg_path = root.parent / config_mod.CONFIG_FILENAME
    if not cfg_path.exists():
        from ugraph import wizard
        cfg_path.write_text(
            wizard.toml_for(answers, cfg_path) if answers
            else f'kb = "{root.name}"\n',
            encoding="utf-8")

    from ugraph import indexes
    cfg = config_mod.load(kb=root)
    indexes.write_all(cfg)

    print(f"Initialized knowledge base at {root}")
    print(f"  wrote SCHEMA.md, taxonomy.json, {len(config_mod.CONTENT_DIRS)} directories")
    print(f"  wrote {cfg_path}")

    # The wizard asked which model backend and whether to ingest a channel. Answering
    # those and then printing the same generic block as a bare `init` wastes the only
    # thing the questions were for — somebody who picked Ollama needs to hear about
    # `ollama pull`, not about skills install.
    if answers:
        if answers.get("channel"):
            _ingest_from_init(cfg, answers)
        from ugraph import wizard
        print(wizard.summary(answers, cfg_path))
        return 0

    # Config resolution walks UP from the working directory, so a bare `ugraph ingest`
    # only finds ugraph.toml when you are at or below its directory. Printing the bare
    # command here sent people straight into "cannot find a knowledge base" — the very
    # next thing they ran after a successful init. Emit commands that work from where
    # the user is actually standing.
    try:
        shown = root.relative_to(Path.cwd())
    except ValueError:
        shown = root
    reachable = config_mod.find_config(Path.cwd()) is not None
    prefix = "" if reachable else f"--kb {shown} "

    print()
    print("Next:")
    print(f"  ugraph {prefix}ingest youtube <channel-url> --limit 25")
    print(f"  ugraph {prefix}skills install     # agent instructions for the extraction pass")
    if not reachable:
        print()
        print(f"  (or `cd {cfg_path.parent.name}` and drop the --kb flag)")
    return 0


def _ingest_from_init(cfg, answers: dict) -> None:
    """Fetch the channel the wizard asked about, if the user named one.

    Asking "which channel to ingest" and then only printing a command to type is a
    question that did nothing. But this must never abort a successful scaffold: a
    missing yt-dlp or a dead network leaves a perfectly good empty KB, so failures
    here degrade to the command the user can run later.
    """
    from ugraph.sources import youtube

    url, limit = answers["channel"], answers.get("limit", 25)
    print(f"\nFetching up to {limit} transcripts from {url} …")

    def progress(i, total, vid, title):
        print(f"  [{i}/{total}] {title[:58]}")

    try:
        result = youtube.ingest(cfg, url, limit=limit, progress=progress)
    except FileNotFoundError:
        answers["retry_channel"] = answers["channel"]
        answers["channel"] = None  # so the summary prints the ingest command again
        print("  yt-dlp is not installed — skipping for now.")
        print("  Install it (brew install yt-dlp) and run the ingest command below.")
        return
    except Exception as exc:
        answers["channel"] = None
        print(f"  ingest failed: {exc}")
        print("  The knowledge base is fine — run the ingest command below when ready.")
        return

    print(f"  ingested {result['written']}, skipped {result['skipped']}")


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def cmd_ingest(args) -> int:
    cfg = _config(args)
    if args.source != "youtube":
        sys.exit(f"ugraph: unknown source '{args.source}' (only 'youtube' so far)")

    from ugraph.sources import youtube

    def progress(i, total, vid, title):
        print(f"[{i}/{total}] {vid}  {title[:58]}")

    try:
        result = youtube.ingest(
            cfg, args.url,
            limit=args.limit, slug=args.slug, dry_run=args.dry_run,
            sleep=args.sleep, force=args.force, progress=progress,
        )
    except FileNotFoundError as exc:
        sys.exit(f"ugraph: {exc}")
    except RuntimeError as exc:
        sys.exit(f"ugraph: {exc}")

    if args.dry_run:
        for v in result.get("videos", []):
            print(f"  {v['id']}  {v.get('title', '')[:70]}")
        print(f"\n{len(result.get('videos', []))} video(s) would be ingested.")
        return 0

    for warning in result.get("warnings", []):
        print(f"  [warn] {warning}")
    print(f"\nIngested {result['written']}, skipped {result['skipped']}. "
          f"{result['total_ingested']}/{result['listed']} of the listing now in the KB.")
    print("Next: ugraph index && ugraph lint")
    return 0


# ---------------------------------------------------------------------------
# index / lint / verify / status
# ---------------------------------------------------------------------------

def cmd_index(args) -> int:
    from ugraph import indexes
    cfg = _config(args)
    if args.check:
        stale = indexes.check(cfg)
        if stale:
            print("Stale indexes (run `ugraph index`):")
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
    from ugraph import lint as lint_mod
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
    from ugraph import verify as verify_mod
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
    from ugraph import status as status_mod
    cfg = _config(args)
    stats = status_mod.collect(cfg)
    if args.json:
        print(json.dumps(stats, indent=2, default=str))
        return 0
    print(status_mod.render(stats, clusters=args.clusters,
                            pending=args.pending, thin=args.thin))
    return 0


def cmd_graph(args) -> int:
    from ugraph import graph as graph_mod
    cfg = _config(args)
    types = {"concept", "entity", "moc"} if args.concepts_only else None
    g = graph_mod.build(cfg, include_provenance=not args.no_provenance, types=types)
    try:
        if args.format == "d3":
            rendered = graph_mod.to_d3(g)
        else:
            rendered = graph_mod.render(g, args.format, config=cfg)
    except ValueError as exc:
        sys.exit(f"ugraph: {exc}")

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



def cmd_ledger(args) -> int:
    from ugraph import ledger as ledger_mod
    cfg = _config(args)

    if args.action == "record":
        try:
            if not args.rec_slug or not args.rec_stage:
                sys.exit("ugraph: usage — ugraph ledger record <slug> <stage>")
            entry = ledger_mod.record(cfg, args.rec_slug, args.rec_stage,
                                      by=args.by, detail=args.detail)
        except ValueError as exc:
            sys.exit(f"ugraph: {exc}")
        print(f"recorded {entry['stage']}  {entry['slug']}")
        return 0

    if args.slug:
        events = ledger_mod.history(cfg, args.slug)
        if not events:
            print(f"no recorded transitions for {args.slug}")
            print("  (state is still derived from the files — try `ugraph ledger --json`)")
            return 0
        for e in events:
            detail = f"  {e['detail']}" if e.get("detail") else ""
            print(f"  {e['ts']}  {e['stage']:<13} {e.get('by', ''):<22}{detail}")
        return 0

    items = ledger_mod.collect(cfg)
    if args.pending:
        items = [i for i in items if not i.done]
    if args.stuck is not None:
        items = [i for i in items if i.stuck and (i.age_days or 0) >= args.stuck]
        items.sort(key=lambda i: -(i.age_days or 0))

    if args.write:
        # The report is always the full ledger; a filtered view would be a report
        # about a filter. Count what was written, not what the flags selected —
        # "3 sources → ledger.md" on a file holding 150 is a lie about the artefact.
        everything = ledger_mod.collect(cfg)
        path = ledger_mod.write_report(cfg, everything)
        if args.json:
            print(json.dumps({"path": str(path), "sources": len(everything)}, indent=2))
        else:
            print(f"{len(everything)} sources → {path}")
        return 0

    if args.json:
        print(ledger_mod.to_json(items))
        return 0

    print(ledger_mod.render_table(items, limit=args.limit))
    return 0



def cmd_extract(args) -> int:
    from ugraph import extract as extract_mod
    cfg = _config(args)

    settings = cfg.raw.get("extract", {}) or {}
    backend_name = args.backend or settings.get("backend") or "claude-code"
    model = args.model or settings.get("model")

    # claude-code is not something this process can drive — the agent does the work.
    # Say so plainly rather than pretending to dispatch it.
    if backend_name == "claude-code":
        pending = extract_mod.pending_sources(cfg)
        print(f"{len(pending)} source(s) waiting to be extracted.")
        print()
        print("The claude-code backend runs in your agent, not here:")
        print("    ugraph skills install")
        print("    then in Claude Code:  /channel-to-kb")
        print()
        print("To have ugraph do the extraction itself instead:")
        print("    ugraph extract --backend ollama    # local, free")
        print("    ugraph extract --backend api       # ANTHROPIC_API_KEY / OPENAI_API_KEY")
        return 0

    try:
        backend = extract_mod.make_backend(backend_name, model)
    except extract_mod.BackendError as exc:
        sys.exit(f"ugraph: {exc}")

    def progress(i, total, slug, title):
        print(f"[{i}/{total}] {title[:62]}")

    result = extract_mod.run(cfg, backend, limit=args.limit, progress=progress)

    if args.json:
        payload = {k: v for k, v in result.items() if k != "results"}
        print(json.dumps(payload, indent=2))
        return 1 if result["failed"] else 0

    print()
    print(f"Extracted {result['written']}/{result['attempted']} "
          f"→ {result['concepts']} candidate concepts")
    if result["rejected"]:
        # Not a warning about the KB — a measurement of the model. The gate did its job.
        print(f"  {result['rejected']} candidate(s) rejected as not verbatim")
    for failure in result["failed"]:
        print(f"  FAILED {failure['slug']}: {failure['error']}")
    if result["written"]:
        print()
        print("Next: the merge step needs an agent — see `ugraph skills install`")
    return 1 if result["failed"] else 0


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------

def cmd_skills(args) -> int:
    if args.action != "install":
        sys.exit("ugraph: only `ugraph skills install` is supported")
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
        prog="ugraph",
        description="Build an agent-navigable knowledge base from a YouTube channel.",
    )
    p.add_argument("--version", action="version", version=f"ugraph-kit {__version__}")
    p.add_argument("--kb", metavar="PATH",
                   help="knowledge base root (default: ugraph.toml, $UGRAPH_KB, or cwd)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="scaffold a new knowledge base")
    sp.add_argument("path", nargs="?",
                    help="where to create it; omit for the interactive setup")
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

    sp = sub.add_parser("ledger", help="lifecycle state of every source")
    sp.add_argument("action", nargs="?", choices=["record"], default=None,
                    help="`record` appends a transition; omit to view")
    sp.add_argument("rec_slug", nargs="?", metavar="SLUG",
                    help="source slug (with `record`)")
    sp.add_argument("rec_stage", nargs="?", metavar="STAGE",
                    help="stage name (with `record`)")
    sp.add_argument("--slug", help="show the recorded history of one source")
    sp.add_argument("--by", default="", help="what performed the transition")
    sp.add_argument("--detail", default="", help="free-text note")
    sp.add_argument("--pending", action="store_true", help="not yet complete")
    sp.add_argument("--stuck", type=int, metavar="DAYS", nargs="?", const=0,
                    help="pulled but unprocessed for DAYS+ days")
    sp.add_argument("--limit", type=int, default=40)
    sp.add_argument("--write", action="store_true",
                    help="write a markdown report into the logs directory")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_ledger)

    sp = sub.add_parser("extract", help="model-driven candidate extraction (Phase A)")
    sp.add_argument("--backend", choices=["claude-code", "ollama", "api"],
                    help="default: [extract].backend in ugraph.toml, else claude-code")
    sp.add_argument("--model", help="override the backend's model")
    sp.add_argument("--limit", type=int, default=10, help="max sources this run")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_extract)

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
        # A downstream reader closed the pipe — `ugraph graph | head`, `| jq .nodes[0]`.
        # That is normal usage, not an error, but Python will also try to flush stdout
        # on exit and raise a second time. Pointing the fd at devnull first is the
        # documented way to exit quietly.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 141  # 128 + SIGPIPE, what a shell expects


if __name__ == "__main__":
    raise SystemExit(main())
