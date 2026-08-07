from __future__ import annotations

import json
from types import SimpleNamespace

from tests.test_roundtrip import scaffold
from ugraph import person as person_mod
from ugraph.cli import build_parser
from ugraph.store import read_md

URL = "https://www.youtube.com/watch?v=kPN564Kol14&t=3768s"


def kun() -> person_mod.Person:
    return person_mod.Person(
        name="Kun Chen",
        handle="@kunchenguid",
        profile_url="https://www.youtube.com/channel/UCb69t9ZkE5z1KvCmfJoaifA",
        source_url=URL,
        source_title="L8 Principal Building a Full Stack App with Agentic Engineering",
    )


def test_supported_url_is_exact_youtube_url():
    assert person_mod.is_supported_url(URL)
    assert person_mod.is_supported_url("https://youtu.be/kPN564Kol14")
    assert not person_mod.is_supported_url("look at https://youtube.com/watch?v=x")
    assert not person_mod.is_supported_url("https://example.com/person")


def test_resolve_youtube_preserves_supplied_timestamp(monkeypatch):
    payload = {
        "title": "L8 Principal Building a Full Stack App with Agentic Engineering",
        "channel": "Kun Chen",
        "channel_url": "https://www.youtube.com/@kunchenguid",
        "uploader_id": "@kunchenguid",
    }
    monkeypatch.setattr(person_mod.shutil, "which", lambda _name: "/bin/yt-dlp")
    monkeypatch.setattr(
        person_mod.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(payload), stderr=""
        ),
    )

    person = person_mod.resolve(URL)

    assert person.name == "Kun Chen"
    assert person.handle == "@kunchenguid"
    assert person.source_url == URL


def test_add_person_writes_canonical_and_redirect(tmp_path):
    cfg = scaffold(tmp_path)
    result = person_mod.add(cfg, kun())

    assert result.created
    assert result.canonical_path == cfg.kb / "entities/people/kun-chen.md"
    assert result.redirect_path == cfg.kb / "resources/people/kun-chen.md"
    canonical_meta, canonical_body = read_md(result.canonical_path)
    redirect_meta, redirect_body = read_md(result.redirect_path)
    assert canonical_meta["subtype"] == "person"
    assert canonical_meta["handles"] == ["@kunchenguid"]
    assert canonical_meta["discovered_from"] == [URL]
    assert URL in canonical_body
    assert redirect_meta["moved_to"] == "../../entities/people/kun-chen.md"
    assert "../../entities/people/kun-chen.md" in redirect_body


def test_add_person_is_idempotent_and_preserves_canonical(tmp_path):
    cfg = scaffold(tmp_path)
    first = person_mod.add(cfg, kun())
    first.canonical_path.write_text(
        first.canonical_path.read_text() + "\nHuman-authored note.\n",
        encoding="utf-8",
    )

    second = person_mod.add(cfg, kun())

    assert not second.created
    assert second.canonical_path == first.canonical_path
    assert "Human-authored note." in second.canonical_path.read_text()
    assert len(list((cfg.kb / "entities/people").glob("*.md"))) == 1


def test_person_cli_contract():
    args = build_parser().parse_args(["person", URL, "--yes"])
    assert args.url == URL
    assert args.yes is True
    assert args.func.__name__ == "cmd_person"
