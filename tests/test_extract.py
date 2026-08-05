"""
The verbatim gate is the whole safety argument for letting a small local model do
extraction. If it can be fooled, a 7B model's paraphrase ends up in a concept page as
something a speaker never said — and nothing downstream would catch it.

These tests do not call a model. They test the gate, which is the part that must not be
wrong.
"""

from __future__ import annotations

import json

from tests.test_roundtrip import scaffold
from ugraph import extract, store

TRANSCRIPT = """\
# Talk

[00:00:00] Welcome everybody, thanks for having me.
[00:00:31] The thing nobody tells you is that context windows degrade
long before they fill up.
[00:01:04] So we treat the window as a budget.
"""


def _candidate(**concept):
    base = {"name": "n", "claim": "c", "verbatim_quote": "", "timestamp": "00:00:31",
            "domain": "ai_engineering"}
    base.update(concept)
    return {"slug": "demo/talk", "concepts": [base]}


def test_verbatim_quote_passes():
    kept, rejected = extract.gate(
        _candidate(verbatim_quote="context windows degrade"), TRANSCRIPT)
    assert len(kept) == 1 and rejected == []


def test_paraphrase_is_rejected():
    """The failure mode a small model actually has."""
    kept, rejected = extract.gate(
        _candidate(verbatim_quote="context windows get worse over time"), TRANSCRIPT)
    assert kept == []
    assert "not verbatim" in rejected[0]


def test_line_wrapping_does_not_count_as_paraphrase():
    """The transcript wraps mid-sentence; a quote spanning the break is still verbatim."""
    kept, rejected = extract.gate(
        _candidate(verbatim_quote="context windows degrade long before they fill up"),
        TRANSCRIPT)
    assert len(kept) == 1, rejected


def test_a_wrong_timestamp_is_corrected_not_rejected():
    """A verbatim quote tells us exactly which paragraph it came from, so a bad marker
    is a recoverable field on a good concept — not a reason to throw the concept away.

    The observed local-model failure was naming the *next* marker, consistently. The
    old behaviour rejected those, which discarded correct extractions over a number we
    can simply compute."""
    kept, rejected = extract.gate(
        _candidate(verbatim_quote="context windows degrade", timestamp="00:09:99"),
        TRANSCRIPT)
    assert rejected == []
    assert kept[0]["timestamp"] == "00:00:31"


def test_the_gate_is_not_weaker_than_the_verifier():
    """`verify` requires a quote to sit in the paragraph its citation names. If the gate
    only checked the marker existed *somewhere*, extract would write candidate files
    that verify immediately rejects — the tool contradicting itself."""
    cand = _candidate(verbatim_quote="we treat the window as a budget",
                      timestamp="00:00:00")   # a real marker, but the wrong one
    kept, _ = extract.gate(cand, TRANSCRIPT)
    assert kept[0]["timestamp"] == "00:01:04"


def test_empty_quote_is_rejected():
    kept, rejected = extract.gate(_candidate(verbatim_quote=""), TRANSCRIPT)
    assert kept == [] and "no quote" in rejected[0]


def test_good_and_bad_are_separated_not_all_or_nothing():
    """One bad quote must not discard the concepts that were fine."""
    cand = {"concepts": [
        {"name": "good", "verbatim_quote": "we treat the window as a budget",
         "timestamp": "00:01:04"},
        {"name": "bad", "verbatim_quote": "something never said", "timestamp": "00:01:04"},
    ]}
    kept, rejected = extract.gate(cand, TRANSCRIPT)
    assert [c["name"] for c in kept] == ["good"]
    assert len(rejected) == 1


def test_json_survives_a_model_wrapping_it_in_a_fence():
    assert extract.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract.parse_json('```\n{"a": 1}\n```') == {"a": 1}


def test_json_survives_a_model_adding_prose():
    """Small models narrate. Cheaper to find the braces than to prompt harder."""
    got = extract.parse_json('Sure! Here is the JSON:\n{"a": 1}\nHope that helps.')
    assert got == {"a": 1}


def test_unparseable_response_returns_none_rather_than_raising():
    assert extract.parse_json("no json at all") is None


def test_pending_skips_already_extracted_and_already_done(tmp_path):
    cfg = scaffold(tmp_path)
    # scaffold()'s single source is summary_status: done
    assert extract.pending_sources(cfg) == []

    src = cfg.sources / "demo" / "example-talk.md"
    meta, body = store.read_md(src)
    meta["summary_status"] = "pending"
    store.write_md(src, body, meta)
    assert len(extract.pending_sources(cfg)) == 1

    # A candidate on disk means Phase A already ran.
    cfg.candidates.mkdir(parents=True, exist_ok=True)
    (cfg.candidates / "example-talk.json").write_text("{}", encoding="utf-8")
    assert extract.pending_sources(cfg) == []


def test_spec_is_the_same_file_the_agent_skill_uses():
    """If the API backend and the Claude Code skill drifted, two users of one tool
    would get differently-shaped candidates from the same transcript."""
    text = extract.spec()
    assert "verbatim_quote" in text
    assert "yield" in text


def test_unknown_backend_names_the_valid_ones():
    try:
        extract.make_backend("gpt5")
    except extract.BackendError as exc:
        assert "ollama" in str(exc) and "claude-code" in str(exc)
    else:
        raise AssertionError("expected BackendError")


def test_ollama_backend_reports_an_unreachable_server_clearly(monkeypatch):
    backend = extract.OllamaBackend(url="http://127.0.0.1:9")  # nothing listens
    try:
        backend.check()
    except extract.BackendError as exc:
        assert "ollama serve" in str(exc)
    else:
        raise AssertionError("expected BackendError")


def test_api_backend_without_a_key_says_what_to_do(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        extract.ApiBackend().check()
    except extract.BackendError as exc:
        assert "ANTHROPIC_API_KEY" in str(exc) and "ollama" in str(exc)
    else:
        raise AssertionError("expected BackendError")


def test_extraction_writes_a_candidate_and_records_the_transition(tmp_path):
    """End to end with a stub backend — no network, no model."""
    from ugraph import ledger

    cfg = scaffold(tmp_path)
    src = cfg.sources / "demo" / "example-talk.md"
    meta, body = store.read_md(src)
    meta["summary_status"] = "pending"
    store.write_md(src, body, meta)

    class Stub(extract.Backend):
        name = "stub"

        def complete(self, system, user):
            return json.dumps({"yield": "high", "concepts": [{
                "name": "context budget",
                "claim": "the window degrades before it fills",
                # Taken verbatim from the scaffold's transcript.
                "verbatim_quote": "they degrade",
                "timestamp": "00:00:31",
                "domain": "ai_engineering",
            }]})

    result = extract.run(cfg, Stub(), limit=5)
    assert result["written"] == 1 and result["concepts"] == 1

    written = json.loads((cfg.candidates / "example-talk.json").read_text())
    assert written["concepts"][0]["name"] == "context budget"
    assert ledger.history(cfg, "demo/example-talk")[0]["stage"] == "extracted"


def test_context_window_grows_with_the_transcript():
    """Ollama defaults to 4096 tokens whatever the model supports, truncates the prompt
    from the front rather than erroring, and the schema is the first thing lost — so
    the model answers in a format it invented. Sizing this is not an optimization."""
    small = extract.context_for("sys", "a short talk")
    big = extract.context_for("sys", "x" * 60_000)
    assert small == extract.MIN_CONTEXT
    assert big == extract.MAX_CONTEXT
    assert extract.context_for("x" * 5_000, "x" * 20_000) > small


def test_valid_json_in_the_wrong_schema_is_retried_not_believed(tmp_path):
    """The dangerous failure: JSON that parses, has no `concepts`, and would be written
    as a candidate recording that the talk contained no ideas at all."""
    cfg = scaffold(tmp_path)
    src = cfg.sources / "demo" / "example-talk.md"
    meta, body = store.read_md(src)
    meta["summary_status"] = "pending"
    store.write_md(src, body, meta)

    class OwnSchema(extract.Backend):
        name = "own-schema"

        def __init__(self):
            self.calls = 0

        def complete(self, system, user):
            self.calls += 1
            return json.dumps({"title": "A talk", "summary": "It was about agents"})

    backend = OwnSchema()
    result = extract.run(cfg, backend, limit=5)

    assert result["written"] == 0, "a made-up schema must not be recorded as a result"
    assert backend.calls == extract.MAX_ATTEMPTS, "should retry, not accept"
    assert not (cfg.candidates / "example-talk.json").exists()
    assert "concepts" in result["failed"][0]["error"]


def test_a_model_that_only_paraphrases_writes_nothing_useful(tmp_path):
    """The safety property, stated as a test: fabrication cannot reach the KB."""
    cfg = scaffold(tmp_path)
    src = cfg.sources / "demo" / "example-talk.md"
    meta, body = store.read_md(src)
    meta["summary_status"] = "pending"
    store.write_md(src, body, meta)

    class Liar(extract.Backend):
        name = "liar"

        def complete(self, system, user):
            return json.dumps({"concepts": [{
                "name": "invented",
                "verbatim_quote": "a sentence that appears nowhere in the transcript",
                "timestamp": "00:00:31",
            }]})

    result = extract.run(cfg, Liar(), limit=5)
    written = json.loads((cfg.candidates / "example-talk.json").read_text())
    assert written["concepts"] == []
    assert written["yield"] == "none"
    assert result["rejected"] >= 1
