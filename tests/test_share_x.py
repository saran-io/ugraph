from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from ugraph.cli import build_parser
from ugraph.share import receipts, secrets
from ugraph.share import x as x_mod
from ugraph.share.draft import ShareDraft, ShareError


@pytest.fixture()
def share_home(tmp_path, monkeypatch):
    home = tmp_path / "cfg"
    monkeypatch.setenv("UGRAPH_CONFIG_HOME", str(home))
    for key in secrets.ENV_MAP.values():
        monkeypatch.delenv(key, raising=False)
    return home


def test_feature_boundary_cli():
    args = build_parser().parse_args(["x", "--dry-run", "hello"])
    assert args.func.__name__ == "cmd_x"
    assert args.dry_run is True


def test_secrets_written_private_and_never_echoed(share_home):
    path = secrets.set_x_credentials("k", "s", "t", "file-ts-secret")
    assert path == share_home / "share" / "x.toml"
    mode = path.stat().st_mode
    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0
    assert secrets.get_x_credentials()["api_key"] == "k"
    assert secrets.get_x_credentials()["access_token_secret"] == "file-ts-secret"
    status = secrets.x_status()
    assert status["configured"] is True
    assert status["file_private"] is True
    dumped = json.dumps(status)
    assert "api_secret" not in dumped
    assert '"access_token"' not in dumped
    assert "file-ts-secret" not in dumped


def test_refuses_world_readable_secrets(share_home):
    path = secrets.set_x_credentials("k", "s", "t", "ts")
    path.chmod(0o644)
    with pytest.raises(ShareError, match="permissions are too open"):
        secrets.get_x_credentials()


def test_env_overrides_file(share_home, monkeypatch):
    secrets.set_x_credentials("file-k", "file-s", "file-t", "file-ts")
    monkeypatch.setenv("UGRAPH_X_API_KEY", "env-k")
    monkeypatch.setenv("UGRAPH_X_API_SECRET", "env-s")
    monkeypatch.setenv("UGRAPH_X_ACCESS_TOKEN", "env-t")
    monkeypatch.setenv("UGRAPH_X_ACCESS_TOKEN_SECRET", "env-ts")
    creds = secrets.get_x_credentials()
    assert creds["api_key"] == "env-k"


def test_validate_text_enforces_limit():
    with pytest.raises(ShareError, match="280"):
        x_mod.validate_text("x" * 281)
    assert x_mod.validate_text("  hi  ") == "hi"


def test_dry_run_does_not_call_network(share_home, monkeypatch):
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("network should not be used in dry-run")

    monkeypatch.setattr(x_mod.urllib.request, "urlopen", boom)
    result = x_mod.post(ShareDraft(text="hello from ugraph"), dry_run=True)
    assert result.dry_run is True
    assert called["n"] == 0
    lines = receipts.receipts_path().read_text().strip().splitlines()
    assert json.loads(lines[-1])["dry_run"] is True


def test_post_success_records_receipt(share_home, monkeypatch):
    secrets.set_x_credentials("k", "s", "t", "ts")

    class Resp:
        status = 201

        def read(self):
            return json.dumps({"data": {"id": "12345", "text": "hi"}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        x_mod.urllib.request, "urlopen", lambda *a, **k: Resp()
    )
    result = x_mod.post(ShareDraft(text="hi"))
    assert result.post_id == "12345"
    assert result.url.endswith("/12345")
    receipt = json.loads(receipts.receipts_path().read_text().strip().splitlines()[-1])
    assert receipt["post_id"] == "12345"
    assert "api_secret" not in receipt
    assert "access_token" not in receipt


def test_media_rejected_in_v1(share_home):
    with pytest.raises(ShareError, match="media"):
        x_mod.post(ShareDraft(text="hi", media=(Path("a.png"),)), dry_run=True)
