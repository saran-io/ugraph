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


def _clipboard_text() -> str:
    """Read a desktop clipboard when a supported command is available."""
    import subprocess

    commands = [
        ["pbpaste"],
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"],
    ]
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return result.stdout
    return ""


def _add_person_flow(cfg, url: str, *, yes: bool = False,
                     name: str | None = None) -> int:
    """Resolve, preview, confirm, and write one person reference."""
    from dataclasses import replace

    from ugraph import person as person_mod

    try:
        person = person_mod.resolve(url)
    except person_mod.PersonResolutionError as exc:
        sys.exit(f"ugraph: {exc}")
    if name:
        person = replace(person, name=name.strip())

    print(f"Detected: {person.name}{f' ({person.handle})' if person.handle else ''}")
    print(f"  profile: {person.profile_url}")
    print(f"  source:  {person.source_title}")

    if not yes:
        if not sys.stdin.isatty():
            print("\nNothing written: confirmation needs a terminal.")
            print(f"Run: ugraph person {url!r} --yes")
            return 1
        answer = input("Add this person to your knowledge base? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("Nothing written.")
            return 0

    result = person_mod.add(cfg, person)
    action = "Created" if result.created else "Already exists"
    print(f"{action}:")
    print(f"  canonical → {result.canonical_path}")
    print(f"  redirect  → {result.redirect_path}")
    return 0


def _person_url(url: str | None = None) -> str:
    if url:
        return url.strip()
    clipboard = _clipboard_text().strip()
    if clipboard:
        print("(using clipboard)")
        return clipboard
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return input("Paste a YouTube link: ").strip()


def cmd_person(args) -> int:
    url = _person_url(getattr(args, "url", None))
    if not url:
        sys.exit("ugraph: no URL supplied")
    return _add_person_flow(
        _config(args),
        url,
        yes=getattr(args, "yes", False),
        name=getattr(args, "name", None),
    )


def cmd_smart(args) -> int:
    """Bare `ugraph`: route one pasted/copied URL to the smallest useful action."""
    from ugraph import person as person_mod

    url = _person_url()
    if not url:
        sys.exit("ugraph: no input supplied")
    if person_mod.is_supported_url(url):
        return _add_person_flow(_config(args), url)
    sys.exit(
        "ugraph: bare capture currently supports YouTube URLs\n"
        "  Try `ugraph --help` for explicit commands.\n"
        "  To post on X:  ugraph x"
    )


# ---------------------------------------------------------------------------
# share / x — outbound only (see docs/adr/0002-share-boundary.md)
# ---------------------------------------------------------------------------

def _share_text(args) -> str:
    """Resolve post text: positional args, else clipboard, else stdin/prompt."""
    parts = getattr(args, "text", None) or []
    if parts:
        return " ".join(parts).strip()
    clip = _clipboard_text().strip()
    if clip:
        print("(using clipboard)")
        return clip
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    print("Compose post, then Ctrl+D:", file=sys.stderr)
    return sys.stdin.read().strip()


def cmd_x(args) -> int:
    """Post text to X. Never runs from bare `ugraph`."""
    from ugraph.share import secrets as share_secrets
    from ugraph.share import x as x_mod
    from ugraph.share.draft import ShareDraft, ShareError

    words = list(getattr(args, "words", None) or [])
    if words and words[0] == "auth":
        args.auth_action = words[1] if len(words) > 1 else "status"
        if len(words) > 2:
            sys.exit("ugraph: usage: ugraph x auth [set|status]")
        return _cmd_x_auth(args)

    # Remaining words are the post body when provided positionally.
    args.text = words
    try:
        text = _share_text(args)
        draft = ShareDraft(text=text, destination="x")
        preview = x_mod.validate_text(draft.text)
    except ShareError as exc:
        sys.exit(f"ugraph: {exc}")

    print("Target: X")
    print(f"Chars:  {len(preview)}/{x_mod.MAX_CHARS}")
    print("---")
    print(preview)
    print("---")

    if getattr(args, "dry_run", False):
        x_mod.post(draft, dry_run=True)
        print(f"Dry run OK — would publish ({len(preview)} chars)")
        return 0

    if not getattr(args, "yes", False):
        if not sys.stdin.isatty():
            print("Nothing published: confirmation needs a terminal (or pass --yes).")
            return 1
        answer = input("Publish to X now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Nothing published.")
            return 0

    try:
        # Resolve credentials before the network call so missing secrets fail
        # closed with a clear setup command rather than a mid-request 401.
        share_secrets.get_x_credentials()
        result = x_mod.post(draft, dry_run=False)
    except ShareError as exc:
        sys.exit(f"ugraph: {exc}")

    print(f"Published: {result.url}")
    print(f"  post id: {result.post_id}")
    return 0


def _cmd_x_auth(args) -> int:
    from ugraph.share import secrets as share_secrets
    from ugraph.share.draft import ShareError

    sub = getattr(args, "auth_action", "status") or "status"
    if sub == "status":
        st = share_secrets.x_status()
        print("ugraph x auth status")
        print(f"  configured: {st['configured']}")
        if st["secrets_file"]:
            print(f"  secrets:    {st['secrets_file']}  ({st['file_mode']})")
            if st["file_private"] is False:
                print("  WARNING: secrets file is not mode 0600 — posting is refused")
        else:
            print("  secrets:    (none)")
        if st["env_vars_set"]:
            print(f"  env:        {', '.join(st['env_vars_set'])}")
        print()
        print("Next:")
        print("  ugraph x auth set     # store OAuth 1.0a user tokens (0600)")
        print("  ugraph x \"hello\"      # preview + confirm, then post")
        return 0

    if sub == "set":
        import getpass

        print("Paste X developer portal user-context credentials.")
        print("App must have Read and Write. Values are hidden and stored at mode 0600.")
        print(f"  → {share_secrets.x_secrets_path()}")
        try:
            api_key = getpass.getpass("API key: ")
            api_secret = getpass.getpass("API secret: ")
            access_token = getpass.getpass("Access token: ")
            access_token_secret = getpass.getpass("Access token secret: ")
            path = share_secrets.set_x_credentials(
                api_key, api_secret, access_token, access_token_secret,
            )
        except (ShareError, EOFError) as exc:
            sys.exit(f"ugraph: {exc}")
        print(f"saved X credentials → {path} (permissions 0600)")
        print("Test with:  ugraph x --dry-run \"ugraph share smoke test\"")
        return 0

    sys.exit("ugraph: `x auth` expects 'set' or 'status'")


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
            sleep=args.sleep, force=args.force, newest=args.newest,
            retry_failed=args.retry_failed, progress=progress,
        )
    except FileNotFoundError as exc:
        sys.exit(f"ugraph: {exc}")
    except RuntimeError as exc:
        sys.exit(f"ugraph: {exc}")

    # Recovering IDs from disk means the state file was missing or incomplete. Silent
    # self-healing is the wrong kind of quiet: the user should know their state was
    # rebuilt, because it is also the signal that something deleted or moved it.
    recovered = result.get("recovered_from_disk", 0)
    if recovered:
        print(f"  [state] recovered {recovered} previously-ingested video(s) "
              "from transcripts on disk")

    if args.dry_run:
        for v in result.get("videos", []):
            print(f"  {v['id']}  {v.get('title', '')[:70]}")
        print(f"\n{len(result.get('videos', []))} video(s) would be ingested.")
        if result.get("known_failed"):
            print(f"  ({result['known_failed']} previously failed, excluded — "
                  "use --retry-failed to reconsider)")
        return 0

    for warning in result.get("warnings", []):
        print(f"  [warn] {warning}")
    print(f"\nIngested {result['written']}, skipped {result['skipped']}.")
    # With --newest the listing is a window over the channel, not the channel, so
    # "151/10 of the listing" is not a ratio — it is two unrelated numbers.
    if args.newest:
        print(f"  {result['total_ingested']} video(s) held from this channel; "
              f"looked at the {result['listed']} most recent.")
    else:
        print(f"  {result['total_ingested']}/{result['listed']} "
              "of the listing now in the KB.")
    if result.get("failed"):
        print(f"  {result['failed']} video(s) recorded as unfetchable (no captions); "
              "they will not be retried. --retry-failed reconsiders them.")
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
    stats = status_mod.collect(cfg, **selectors(args))
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

    from ugraph import select

    items = ledger_mod.collect(cfg)
    sel = selectors(args)
    if any(v is not None for v in sel.values()):
        items = select.by_recency(items, **sel)
    if args.pending:
        items = [i for i in items if not i.done]
    if args.stuck is not None:
        # --stuck re-sorts by how long something has sat, which is the point of it.
        # That deliberately overrides publication order when both are given.
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
    from ugraph import select
    cfg = _config(args)

    settings = cfg.raw.get("extract", {}) or {}
    backend_name = args.backend or settings.get("backend") or "claude-code"
    model = args.model or settings.get("model")
    sel = selectors(args)

    # `--dry-run` exists because selection used to be invisible: `--limit 10` silently
    # meant "ten talks whose slug starts with a". Being able to see the batch, in
    # order, before spending an hour of local inference is worth one flag.
    if args.dry_run:
        batch = extract_mod.pending_sources(cfg, **sel)[:args.limit]
        if args.json:
            print(json.dumps([{
                "slug": str(p.meta.get("slug") or p.id),
                "published": p.meta.get("published"),
                "title": p.title,
            } for p in batch], indent=2))
            return 0
        phrase = select.describe(**sel)
        print(f"{len(batch)} source(s) would be extracted"
              + (f" ({phrase})" if phrase else "") + ":")
        for page in batch:
            date_str = str(page.meta.get("published") or "undated")
            print(f"  {date_str:<12} {page.title[:58]}")
        return 0

    # claude-code is not something this process can drive — the agent does the work.
    # Say so plainly rather than pretending to dispatch it.
    if backend_name == "claude-code":
        pending = extract_mod.pending_sources(cfg, **sel)
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

    result = extract_mod.run(cfg, backend, limit=args.limit, progress=progress, **sel)

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

def add_selectors(sp, since: bool = True, channel: bool = True) -> None:
    """The recency flags, added from one place so they cannot drift apart.

    `--newest` meaning "most recently published" in `extract` and something subtly
    different in `ledger` would be worse than not offering it at all.
    """
    sp.add_argument("--newest", type=int, metavar="N",
                    help="the N most recently published")
    if since:
        sp.add_argument("--since", metavar="DATE",
                        help="published on or after DATE (YYYY-MM-DD, or 7d/2w/3m/1y)")
    if channel:
        sp.add_argument("--channel", metavar="SLUG",
                        help="restrict to one channel, e.g. ai-engineer")


def selectors(args) -> dict:
    """Resolve the selector flags into kwargs, exiting cleanly on a bad date."""
    from ugraph import select

    raw = getattr(args, "since", None)
    try:
        since = select.parse_since(raw) if raw else None
    except ValueError as exc:
        sys.exit(f"ugraph: {exc}")
    return {"newest": getattr(args, "newest", None), "since": since,
            "channel": getattr(args, "channel", None)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ugraph",
        description="Build an agent-navigable knowledge base from a YouTube channel.",
    )
    p.add_argument("--version", action="version", version=f"ugraph-kit {__version__}")
    p.add_argument("--kb", metavar="PATH",
                   help="knowledge base root (default: ugraph.toml, $UGRAPH_KB, or cwd)")
    p.set_defaults(func=cmd_smart)
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("init", help="scaffold a new knowledge base")
    sp.add_argument("path", nargs="?",
                    help="where to create it; omit for the interactive setup")
    sp.add_argument("--force", action="store_true", help="overwrite an existing scaffold")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("ingest", help="fetch source material")
    sp.add_argument("source", choices=["youtube"])
    sp.add_argument("url")
    sp.add_argument("--limit", type=int, default=10, help="max NEW items this run")
    # No --since here: yt-dlp's flat playlist listing returns NA for upload_date, so a
    # date filter would need a per-video metadata fetch — most of the cost of ingesting
    # anyway. Listing order is the only cheap recency signal, hence --newest.
    sp.add_argument("--newest", type=int, metavar="N",
                    help="only consider the N most recent uploads, held or not")
    sp.add_argument("--slug", help="override the channel slug")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--sleep", type=float, default=1.5,
                    help="seconds between fetches; raise it if you hit rate limits")
    sp.add_argument("--force", action="store_true", help="re-fetch items already recorded")
    sp.add_argument("--retry-failed", action="store_true",
                    help="reconsider videos recorded as unfetchable")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser(
        "person",
        help="resolve a person from a YouTube link and add them to the KB",
    )
    sp.add_argument("url", nargs="?",
                    help="video/channel/profile URL (defaults to clipboard)")
    sp.add_argument("--name", help="override the resolved display name")
    sp.add_argument("--yes", "-y", action="store_true",
                    help="write without interactive confirmation")
    sp.set_defaults(func=cmd_person)

    sp = sub.add_parser(
        "x",
        help="post text to X (outbound share — never runs from bare ugraph)",
    )
    sp.add_argument(
        "words", nargs="*",
        help="post text, or `auth set` / `auth status`",
    )
    sp.add_argument("--yes", "-y", action="store_true",
                    help="publish without interactive confirmation")
    sp.add_argument("--dry-run", action="store_true",
                    help="preview and validate only — no network publish")
    sp.set_defaults(func=cmd_x)

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
    add_selectors(sp)
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
    add_selectors(sp)
    sp.add_argument("--write", action="store_true",
                    help="write a markdown report into the logs directory")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_ledger)

    sp = sub.add_parser("extract", help="model-driven candidate extraction (Phase A)")
    sp.add_argument("--backend", choices=["claude-code", "ollama", "api"],
                    help="default: [extract].backend in ugraph.toml, else claude-code")
    sp.add_argument("--model", help="override the backend's model")
    sp.add_argument("--limit", type=int, default=10, help="max sources this run")
    add_selectors(sp)
    sp.add_argument("--dry-run", action="store_true",
                    help="list what would be extracted, in order, and stop")
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
