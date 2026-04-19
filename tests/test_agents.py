from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.agents.registry import AGENT_RUN_FNS, list_agents, load_agent
from src.agents.runner import run_agent
from src.agents.schedule import agent_is_due, agents_due, parse_interval_seconds
from src.agents.state import load_state, save_state, update_state


# ---------------------------------------------------------------------------
# Agent folder scaffolder
# ---------------------------------------------------------------------------

def _scaffold_agent(
    repo_root: Path,
    name: str,
    *,
    schedule: str = "manual",
    config_extra: dict | None = None,
    prompt_body: str = "do the thing",
):
    folder = repo_root / "agents" / name
    folder.mkdir(parents=True, exist_ok=True)
    cfg = {
        "name": name,
        "description": f"test agent {name}",
        "schedule": schedule,
        "domain": "edge-ai",
        "model": "claude-sonnet-4-6",
    }
    cfg.update(config_extra or {})
    (folder / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False))
    (folder / "prompt.md").write_text(prompt_body)
    return folder


# ---------------------------------------------------------------------------
# Schedule primitives
# ---------------------------------------------------------------------------

def test_parse_interval_seconds_known():
    assert parse_interval_seconds("hourly") == 3600
    assert parse_interval_seconds("daily") == 86400
    assert parse_interval_seconds("weekly") == 604800


def test_parse_interval_seconds_off_and_manual():
    assert parse_interval_seconds("off") is None
    assert parse_interval_seconds("manual") is None


def test_parse_interval_seconds_unknown_returns_none():
    assert parse_interval_seconds("gibberish") is None
    assert parse_interval_seconds("") is None


def test_agent_is_due_when_never_run():
    assert agent_is_due("hourly", None) is True


def test_agent_is_due_false_when_manual():
    assert agent_is_due("manual", None) is False
    assert agent_is_due("off", None) is False


def test_agent_is_due_uses_last_run_at():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=30)).isoformat()
    old = (now - timedelta(hours=25)).isoformat()
    assert agent_is_due("hourly", recent, now=now) is False
    assert agent_is_due("hourly", old, now=now) is True
    assert agent_is_due("daily", recent, now=now) is False
    assert agent_is_due("daily", old, now=now) is True


# ---------------------------------------------------------------------------
# State IO
# ---------------------------------------------------------------------------

def test_load_state_returns_default_when_missing(repo_root):
    (repo_root / "agents" / "foo").mkdir(parents=True)
    state = load_state("foo", repo_root)
    assert state["last_run_at"] is None
    assert state["last_status"] is None
    assert state["last_outputs"] == []


def test_save_and_reload_state(repo_root):
    (repo_root / "agents" / "foo").mkdir(parents=True)
    save_state("foo", repo_root, {
        "last_run_at": "2026-04-17T10:00:00+00:00",
        "last_status": "ok",
        "last_duration_s": 1.5,
        "last_message": "done",
        "last_job_id": "job_123",
        "last_outputs": ["cand_x.md"],
    })
    state = load_state("foo", repo_root)
    assert state["last_status"] == "ok"
    assert state["last_outputs"] == ["cand_x.md"]


def test_update_state_merges(repo_root):
    (repo_root / "agents" / "foo").mkdir(parents=True)
    save_state("foo", repo_root, {"last_status": "running"})
    merged = update_state("foo", repo_root, last_status="ok", last_duration_s=2.0)
    assert merged["last_status"] == "ok"
    assert merged["last_duration_s"] == 2.0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_list_agents_reads_disk(repo_root):
    _scaffold_agent(repo_root, "alpha")
    _scaffold_agent(repo_root, "beta")
    found = [m.name for m in list_agents(repo_root)]
    assert found == ["alpha", "beta"]


def test_load_agent_parses_config_and_prompt(repo_root):
    _scaffold_agent(repo_root, "alpha", prompt_body="Hello\n")
    meta = load_agent("alpha", repo_root)
    assert meta is not None
    assert meta.name == "alpha"
    assert meta.config["domain"] == "edge-ai"
    assert meta.prompt == "Hello\n"
    assert meta.config_exists is True
    assert meta.prompt_exists is True


def test_load_agent_returns_none_when_missing(repo_root):
    assert load_agent("ghost", repo_root) is None


def test_agents_due_filters_by_schedule_and_state(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "hourly-agent", schedule="hourly")
    _scaffold_agent(repo_root, "manual-agent", schedule="manual")
    now = datetime.now(timezone.utc)

    # hourly-agent has no state → due.
    # manual-agent has schedule=manual → never due.
    due = agents_due(repo_root, now=now)
    assert "hourly-agent" in due
    assert "manual-agent" not in due


def test_agents_due_skips_running_agents(repo_root):
    _scaffold_agent(repo_root, "hourly-agent", schedule="hourly")
    save_state("hourly-agent", repo_root, {"last_status": "running"})
    due = agents_due(repo_root)
    assert "hourly-agent" not in due


# ---------------------------------------------------------------------------
# Runner — with a stub run fn injected into the registry
# ---------------------------------------------------------------------------

def test_run_agent_records_ok(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "stub-ok", schedule="manual")

    calls = {"n": 0}

    def _fake_run(**kwargs):
        calls["n"] += 1
        return {"message": "did the work", "outputs": ["artefact.md"]}

    monkeypatch.setitem(AGENT_RUN_FNS, "stub-ok", _fake_run)
    result = run_agent("stub-ok", repo_root)
    assert result.status == "ok"
    assert calls["n"] == 1

    state = load_state("stub-ok", repo_root)
    assert state["last_status"] == "ok"
    assert state["last_outputs"] == ["artefact.md"]
    assert state["last_job_id"] == result.job_id

    # Completed job YAML written.
    job_file = repo_root / "jobs" / "completed" / f"{result.job_id}.yaml"
    assert job_file.exists()


def test_run_agent_records_failure(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "stub-fail", schedule="manual")

    def _boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(AGENT_RUN_FNS, "stub-fail", _boom)
    result = run_agent("stub-fail", repo_root)
    assert result.status == "failed"
    assert "boom" in (result.error or "")

    state = load_state("stub-fail", repo_root)
    assert state["last_status"] == "failed"
    assert "boom" in (state["last_error"] or "")

    # Failed job YAML written.
    job_file = repo_root / "jobs" / "failed" / f"{result.job_id}.yaml"
    assert job_file.exists()


def test_run_agent_unknown_agent_records_failed(repo_root):
    result = run_agent("ghost", repo_root)
    assert result.status == "failed"
    assert "ghost" in (result.error or "")


def test_run_agent_unwired_records_failed(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "unwired", schedule="manual")
    # Ensure no run fn for "unwired".
    monkeypatch.delitem(AGENT_RUN_FNS, "unwired", raising=False)
    result = run_agent("unwired", repo_root)
    assert result.status == "failed"
    assert "no run function registered" in (result.error or "")
    state = load_state("unwired", repo_root)
    assert state["last_status"] == "failed"


# ---------------------------------------------------------------------------
# deepSearch agent is registered on import
# ---------------------------------------------------------------------------

def test_deep_search_is_registered():
    assert "deepSearch" in AGENT_RUN_FNS


def test_deep_search_needs_api_key(repo_root, monkeypatch):
    _scaffold_agent(
        repo_root, "deepSearch", schedule="manual",
        config_extra={"question": "test question"},
        prompt_body="Template {domain} {now} {candidate_id}",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_agent("deepSearch", repo_root)
    assert result.status == "failed"
    assert "ANTHROPIC_API_KEY" in (result.error or "")


# ---------------------------------------------------------------------------
# work_scope + seen ledger
# ---------------------------------------------------------------------------

from src.agents.seen import (
    SeenTracker,
    clear_seen,
    load_seen,
    normalize_scope,
    save_seen,
)


def test_normalize_scope_defaults_to_all():
    assert normalize_scope("all") == "all"
    assert normalize_scope("new") == "new"
    assert normalize_scope("") == "all"
    assert normalize_scope("junk") == "all"
    assert normalize_scope(None) == "all"


def test_seen_load_save_roundtrip(repo_root):
    (repo_root / "agents" / "foo").mkdir(parents=True)
    save_seen("foo", repo_root, {"a", "b", "c"})
    assert load_seen("foo", repo_root) == {"a", "b", "c"}


def test_seen_missing_returns_empty_set(repo_root):
    (repo_root / "agents" / "foo").mkdir(parents=True)
    assert load_seen("foo", repo_root) == set()


def test_seen_tracker_marks_only_additions():
    t = SeenTracker(initial={"a", "b"})
    t.mark("c")
    t.mark_many(["d", "e"])
    assert t.marked == {"c", "d", "e"}
    assert t.final == {"a", "b", "c", "d", "e"}


def test_seen_tracker_filter_new():
    t = SeenTracker(initial={"x", "y"})
    items = [{"id": "x"}, {"id": "z"}]
    fresh = t.filter_new(items, key=lambda it: it["id"])
    assert fresh == [{"id": "z"}]


def test_clear_seen_removes_file(repo_root):
    (repo_root / "agents" / "foo").mkdir(parents=True)
    save_seen("foo", repo_root, {"x"})
    clear_seen("foo", repo_root)
    assert load_seen("foo", repo_root) == set()


def test_runner_persists_seen_after_success(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "tracker-ok", schedule="manual",
                    config_extra={"work_scope": "new"})

    def _run(**kwargs):
        seen = kwargs["seen"]
        assert kwargs["work_scope"] == "new"
        seen.mark("item-1", "item-2")
        return {"message": "ok", "outputs": []}

    monkeypatch.setitem(AGENT_RUN_FNS, "tracker-ok", _run)
    result = run_agent("tracker-ok", repo_root)
    assert result.status == "ok"
    assert load_seen("tracker-ok", repo_root) == {"item-1", "item-2"}


def test_runner_does_not_persist_seen_on_failure(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "tracker-fail", schedule="manual",
                    config_extra={"work_scope": "new"})

    def _run(**kwargs):
        kwargs["seen"].mark("item-should-not-persist")
        raise RuntimeError("mid-run crash")

    monkeypatch.setitem(AGENT_RUN_FNS, "tracker-fail", _run)
    result = run_agent("tracker-fail", repo_root)
    assert result.status == "failed"
    assert load_seen("tracker-fail", repo_root) == set()


def test_runner_extends_existing_seen_set(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "tracker-extend", schedule="manual",
                    config_extra={"work_scope": "new"})
    save_seen("tracker-extend", repo_root, {"old-1"})

    def _run(**kwargs):
        assert "old-1" in kwargs["seen"].initial
        kwargs["seen"].mark("new-1")
        return {"message": "ok"}

    monkeypatch.setitem(AGENT_RUN_FNS, "tracker-extend", _run)
    run_agent("tracker-extend", repo_root)
    assert load_seen("tracker-extend", repo_root) == {"old-1", "new-1"}


def test_runner_defaults_work_scope_to_all(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "no-scope", schedule="manual")  # no work_scope in config

    captured = {}

    def _run(**kwargs):
        captured["scope"] = kwargs["work_scope"]
        return {"message": "ok"}

    monkeypatch.setitem(AGENT_RUN_FNS, "no-scope", _run)
    run_agent("no-scope", repo_root)
    assert captured["scope"] == "all"


# ---------------------------------------------------------------------------
# digestAgent
# ---------------------------------------------------------------------------

from src.agents import digest_agent as digest_agent_mod
from src.agents.seen import load_seen


def _scaffold_raw(repo_root: Path, raw_id: str, *, domain_hint: str = "edge-ai"):
    raw_dir = repo_root / "inbox" / "raw" / raw_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "source.md").write_text("# Source\nHello.\n", encoding="utf-8")
    (raw_dir / "metadata.yaml").write_text(
        yaml.dump({"id": raw_id, "title": raw_id, "domain_hint": domain_hint}),
        encoding="utf-8",
    )
    return raw_dir


def test_digest_agent_is_registered():
    assert "digestAgent" in AGENT_RUN_FNS


def test_digest_agent_requires_api_key(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "digestAgent", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_raw(repo_root, "raw_1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_agent("digestAgent", repo_root)
    assert result.status == "failed"
    assert "ANTHROPIC_API_KEY" in (result.error or "")


def test_digest_agent_no_raws_skips_cleanly(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "digestAgent", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = run_agent("digestAgent", repo_root)
    assert result.status == "ok"
    assert "Nothing to digest" in (result.message or "")


def test_digest_agent_filters_by_domain_hint(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "digestAgent", schedule="manual",
                    config_extra={"domain": "edge-ai",
                                  "require_domain_hint_match": True,
                                  "max_raws_per_run": 10})
    _scaffold_raw(repo_root, "raw_match", domain_hint="edge-ai")
    _scaffold_raw(repo_root, "raw_other", domain_hint="robotics")
    _scaffold_raw(repo_root, "raw_blank", domain_hint="")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    seen_raws: list[str] = []

    def _fake_digest(raw_id, domain, repo_root):
        seen_raws.append(raw_id)
        return [f"{raw_id}.md"]

    monkeypatch.setattr(digest_agent_mod, "digest_raw", _fake_digest)
    result = run_agent("digestAgent", repo_root)
    assert result.status == "ok"
    assert seen_raws == ["raw_match"]


def test_digest_agent_respects_max_raws_per_run(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "digestAgent", schedule="manual",
                    config_extra={"domain": "edge-ai",
                                  "max_raws_per_run": 2})
    for i in range(5):
        _scaffold_raw(repo_root, f"raw_{i}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls: list[str] = []

    def _fake(raw_id, domain, repo_root):
        calls.append(raw_id)
        return [f"{raw_id}.md"]

    monkeypatch.setattr(digest_agent_mod, "digest_raw", _fake)
    run_agent("digestAgent", repo_root)
    assert len(calls) == 2


def test_digest_agent_skips_seen_and_marks_on_success(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "digestAgent", schedule="manual",
                    config_extra={"domain": "edge-ai", "work_scope": "new",
                                  "max_raws_per_run": 10})
    _scaffold_raw(repo_root, "raw_a")
    _scaffold_raw(repo_root, "raw_b")
    # Pre-seed raw_a in the seen ledger.
    from src.agents.seen import save_seen
    save_seen("digestAgent", repo_root, {"raw_a"})

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls: list[str] = []

    def _fake(raw_id, domain, repo_root):
        calls.append(raw_id)
        return [f"{raw_id}.md"]

    monkeypatch.setattr(digest_agent_mod, "digest_raw", _fake)
    run_agent("digestAgent", repo_root)
    assert calls == ["raw_b"]
    # After success, raw_b is added to the ledger (raw_a already there).
    assert load_seen("digestAgent", repo_root) == {"raw_a", "raw_b"}


def test_digest_agent_failure_per_raw_does_not_abort_run(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "digestAgent", schedule="manual",
                    config_extra={"domain": "edge-ai", "work_scope": "new",
                                  "max_raws_per_run": 10})
    _scaffold_raw(repo_root, "raw_ok")
    _scaffold_raw(repo_root, "raw_err")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _fake(raw_id, domain, repo_root):
        if raw_id == "raw_err":
            raise RuntimeError("simulated LLM failure")
        return [f"{raw_id}.md"]

    monkeypatch.setattr(digest_agent_mod, "digest_raw", _fake)
    result = run_agent("digestAgent", repo_root)
    # Agent-run itself succeeds even though one raw failed — errors are captured.
    assert result.status == "ok"
    # Only the successful one is persisted in seen.
    assert load_seen("digestAgent", repo_root) == {"raw_ok"}


# ---------------------------------------------------------------------------
# lintAgent
# ---------------------------------------------------------------------------

LINT_LOW_CONF_PAGE = """\
---
title: "Low Conf Page"
domain: edge-ai
type: concept
status: approved
confidence: 0.20
sources: []
created_at: "2026-04-16T12:00:00+00:00"
updated_at: "2026-04-16T12:00:00+00:00"
tags: []
---
# Low Conf Page
body
"""


def _scaffold_domain(repo_root: Path, domain: str, *, with_low_conf_page: bool = False):
    dom = repo_root / "domains" / domain
    (dom / "concepts").mkdir(parents=True, exist_ok=True)
    (dom / "indexes").mkdir(parents=True, exist_ok=True)
    (repo_root / "candidates" / domain / "pending").mkdir(parents=True, exist_ok=True)
    (dom / "index.md").write_text("# Index\n")
    (dom / "log.md").write_text("# Log\n")
    if with_low_conf_page:
        (dom / "concepts" / "low.md").write_text(LINT_LOW_CONF_PAGE)


def test_lint_agent_is_registered():
    assert "lintAgent" in AGENT_RUN_FNS


def test_lint_agent_no_domain_configured_and_no_folders_skips(repo_root):
    _scaffold_agent(repo_root, "lintAgent", schedule="manual")
    # Drop the default "domain: edge-ai" from the helper so resolver has nothing.
    cfg_path = repo_root / "agents" / "lintAgent" / "config.yaml"
    cfg_path.write_text(yaml.dump({
        "name": "lintAgent",
        "schedule": "manual",
    }))
    # No domains/<x>/ folders either (conftest creates empty domains/).
    result = run_agent("lintAgent", repo_root)
    assert result.status == "ok"
    assert "No domains" in (result.message or "")


def test_lint_agent_runs_single_domain_and_regenerates_indexes(repo_root):
    _scaffold_agent(repo_root, "lintAgent", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai", with_low_conf_page=True)

    result = run_agent("lintAgent", repo_root)
    assert result.status == "ok"

    idx_dir = repo_root / "domains" / "edge-ai" / "indexes"
    assert (idx_dir / "low-confidence.md").exists()
    assert (idx_dir / "contradictions.md").exists()
    assert (idx_dir / "orphans.md").exists()
    assert (idx_dir / "stale-pages.md").exists()
    assert "Low Conf Page" in (idx_dir / "low-confidence.md").read_text()
    # Message reports the low-confidence count.
    assert "low-conf=1" in (result.message or "")


def test_lint_agent_supports_multi_domain_list(repo_root):
    _scaffold_agent(repo_root, "lintAgent", schedule="manual",
                    config_extra={"domains": ["edge-ai", "robotics"]})
    _scaffold_domain(repo_root, "edge-ai")
    _scaffold_domain(repo_root, "robotics")

    result = run_agent("lintAgent", repo_root)
    assert result.status == "ok"
    # Both domains' indexes exist.
    for dom in ("edge-ai", "robotics"):
        assert (repo_root / "domains" / dom / "indexes" / "low-confidence.md").exists()
    # Outputs list mentions both domains.
    joined = " ".join(result.outputs)
    assert "edge-ai" in joined and "robotics" in joined


def test_lint_agent_auto_discovers_domains_when_unset(repo_root):
    # Config with no `domain` or `domains` — agent should fall back to
    # enumerating domains/<x>/ folders.
    cfg_path = repo_root / "agents" / "lintAgent" / "config.yaml"
    (repo_root / "agents" / "lintAgent").mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.dump({"name": "lintAgent", "schedule": "manual"}))
    (repo_root / "agents" / "lintAgent" / "prompt.md").write_text("n/a")
    _scaffold_domain(repo_root, "edge-ai")

    result = run_agent("lintAgent", repo_root)
    assert result.status == "ok"
    assert (repo_root / "domains" / "edge-ai" / "indexes" / "low-confidence.md").exists()


def test_lint_agent_does_not_require_api_key(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "lintAgent", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = run_agent("lintAgent", repo_root)
    assert result.status == "ok"


# ---------------------------------------------------------------------------
# sourceDiscovery
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock

import src.agents.source_discovery as source_discovery_mod


def _fake_claude_reply(text: str, tokens_in: int = 10, tokens_out: int = 20):
    """Build a MagicMock that mimics anthropic's messages.create return."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage = MagicMock(input_tokens=tokens_in, output_tokens=tokens_out)
    return msg


def _patch_claude(monkeypatch, module, reply):
    """Swap in a fake Anthropic client whose messages.create returns `reply`."""
    client = MagicMock()
    client.messages.create.return_value = reply
    monkeypatch.setattr(module.anthropic, "Anthropic", lambda api_key: client)
    return client


def test_source_discovery_is_registered():
    assert "sourceDiscovery" in AGENT_RUN_FNS


def test_source_discovery_requires_api_key(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "sourceDiscovery", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_agent("sourceDiscovery", repo_root)
    assert result.status == "failed"
    assert "ANTHROPIC_API_KEY" in (result.error or "")


def test_source_discovery_requires_domain(repo_root, monkeypatch):
    cfg_path = repo_root / "agents" / "sourceDiscovery"
    cfg_path.mkdir(parents=True, exist_ok=True)
    (cfg_path / "config.yaml").write_text(yaml.dump({
        "name": "sourceDiscovery",
        "schedule": "manual",
    }))
    (cfg_path / "prompt.md").write_text("please suggest sources")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = run_agent("sourceDiscovery", repo_root)
    assert result.status == "failed"
    assert "domain" in (result.error or "").lower()


_SOURCE_DISCOVERY_REPLY = """```yaml
suggestions:
  - url: "https://vendor.example.com/datasheet-hailo8.pdf"
    title: "Hailo-8 Datasheet"
    why: "Primary source for peak TOPS numbers currently only cited from a blog."
    suggested_domain: "edge-ai"
    research_question: "What is the actual INT8 peak on Hailo-8?"
    confidence: 0.82
  - url: "https://arxiv.org/abs/2501.00001"
    title: "Edge NPU Benchmark Survey 2026"
    why: "Would fill the gap in cross-platform comparisons."
    suggested_domain: "edge-ai"
    research_question: "How do sub-5W NPUs compare head-to-head?"
    confidence: 0.70
```
"""


def test_source_discovery_writes_suggestions(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "sourceDiscovery", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai", with_low_conf_page=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _patch_claude(monkeypatch, source_discovery_mod,
                  _fake_claude_reply(_SOURCE_DISCOVERY_REPLY))

    result = run_agent("sourceDiscovery", repo_root)
    assert result.status == "ok", result.error
    sugg_path = repo_root / "domains" / "edge-ai" / "indexes" / "suggested-sources.md"
    content = sugg_path.read_text()
    assert "Hailo-8 Datasheet" in content
    assert "https://vendor.example.com/datasheet-hailo8.pdf" in content
    assert "Edge NPU Benchmark Survey 2026" in content
    assert result.outputs == ["domains/edge-ai/indexes/suggested-sources.md"]
    log_text = (repo_root / "domains" / "edge-ai" / "log.md").read_text()
    assert "source-discovery" in log_text


def test_source_discovery_dedups_against_existing_file(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "sourceDiscovery", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    sugg_path = repo_root / "domains" / "edge-ai" / "indexes" / "suggested-sources.md"
    sugg_path.write_text(
        "# Existing\nhttps://vendor.example.com/datasheet-hailo8.pdf\n"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _patch_claude(monkeypatch, source_discovery_mod,
                  _fake_claude_reply(_SOURCE_DISCOVERY_REPLY))

    result = run_agent("sourceDiscovery", repo_root)
    assert result.status == "ok"
    content = sugg_path.read_text()
    assert content.count("https://vendor.example.com/datasheet-hailo8.pdf") == 1
    assert "https://arxiv.org/abs/2501.00001" in content


def test_source_discovery_work_scope_new_filters_seen(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "sourceDiscovery", schedule="manual",
                    config_extra={"domain": "edge-ai", "work_scope": "new"})
    _scaffold_domain(repo_root, "edge-ai")
    save_seen("sourceDiscovery", repo_root, {"https://arxiv.org/abs/2501.00001"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _patch_claude(monkeypatch, source_discovery_mod,
                  _fake_claude_reply(_SOURCE_DISCOVERY_REPLY))

    result = run_agent("sourceDiscovery", repo_root)
    assert result.status == "ok"
    content = (repo_root / "domains" / "edge-ai" / "indexes"
               / "suggested-sources.md").read_text()
    assert "https://vendor.example.com/datasheet-hailo8.pdf" in content
    assert "https://arxiv.org/abs/2501.00001" not in content
    assert "https://vendor.example.com/datasheet-hailo8.pdf" in load_seen(
        "sourceDiscovery", repo_root
    )


def test_source_discovery_empty_list_is_ok(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "sourceDiscovery", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _patch_claude(monkeypatch, source_discovery_mod,
                  _fake_claude_reply("```yaml\nsuggestions: []\n```"))

    result = run_agent("sourceDiscovery", repo_root)
    assert result.status == "ok"
    assert "No new suggestions" in (result.message or "")
    sugg_path = repo_root / "domains" / "edge-ai" / "indexes" / "suggested-sources.md"
    assert not sugg_path.exists()


def test_source_discovery_drops_invalid_entries(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "sourceDiscovery", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    bad_reply = """```yaml
suggestions:
  - url: ""
    title: "No URL"
  - url: "ftp://old.example.com/file"
    title: "Wrong scheme"
  - url: "https://good.example.com/x"
    title: "Real one"
    why: "good"
    confidence: 0.5
```
"""
    _patch_claude(monkeypatch, source_discovery_mod, _fake_claude_reply(bad_reply))
    result = run_agent("sourceDiscovery", repo_root)
    assert result.status == "ok"
    content = (repo_root / "domains" / "edge-ai" / "indexes"
               / "suggested-sources.md").read_text()
    assert "https://good.example.com/x" in content
    assert "ftp://old.example.com/file" not in content


# ---------------------------------------------------------------------------
# conflicAgent
# ---------------------------------------------------------------------------

import src.agents.conflic_agent as conflic_agent_mod


def test_conflic_agent_is_registered():
    assert "conflicAgent" in AGENT_RUN_FNS


def test_conflic_agent_is_manual_only_on_disk():
    """The shipped config ships with schedule: manual. If someone flips it
    to a periodic cadence, this test should fail so we review the change."""
    shipped = Path("agents/conflicAgent/config.yaml")
    if not shipped.exists():
        pytest.skip("conflicAgent folder not present in this tree")
    cfg = yaml.safe_load(shipped.read_text())
    assert cfg.get("schedule") == "manual"


def test_conflic_agent_requires_api_key(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "conflicAgent", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_agent("conflicAgent", repo_root)
    assert result.status == "failed"
    assert "ANTHROPIC_API_KEY" in (result.error or "")


_CONFLIC_REPLY = """```yaml
conflicts:
  - page_a: "VOXL 2"
    page_b: "NNAPI Delegate Fallback"
    claim_a: "VOXL 2 supports NNAPI acceleration."
    claim_b: "VOXL 2 does not expose NNAPI."
    conflict_type: "direct-contradiction"
    explanation: "Both absolute claims cannot be true."
    resolution_hint: "Check firmware version."
    severity: 0.85
  - page_a: "Hailo-8"
    page_b: "Benchmark Survey"
    claim_a: "Peak 26 TOPS INT8."
    claim_b: "Peaks at 13 TOPS INT8."
    conflict_type: "numeric-disagreement"
    explanation: "Spread > 10% without context."
    resolution_hint: "Confirm mode (peak vs sustained)."
    severity: 0.72
  - page_a: "A"
    page_b: "B"
    claim_a: "x"
    claim_b: "y"
    conflict_type: "evidence-strength"
    explanation: "noise"
    severity: 0.10
```
"""


def test_conflic_agent_files_conflict_candidates(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "conflicAgent", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _patch_claude(monkeypatch, conflic_agent_mod, _fake_claude_reply(_CONFLIC_REPLY))

    result = run_agent("conflicAgent", repo_root)
    assert result.status == "ok", result.error
    pending = list((repo_root / "candidates" / "edge-ai" / "pending").iterdir())
    assert len(pending) == 2
    joined = "\n\n".join(p.read_text() for p in pending)
    assert "VOXL 2" in joined
    assert "Hailo-8" in joined
    assert "type: contradiction-note" in joined
    assert "candidate_operation: create" in joined
    log_text = (repo_root / "domains" / "edge-ai" / "log.md").read_text()
    assert "conflict-scan" in log_text


def test_conflic_agent_drops_below_severity_threshold(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "conflicAgent", schedule="manual",
                    config_extra={"domain": "edge-ai", "min_severity": 0.80})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _patch_claude(monkeypatch, conflic_agent_mod, _fake_claude_reply(_CONFLIC_REPLY))

    result = run_agent("conflicAgent", repo_root)
    assert result.status == "ok"
    pending = list((repo_root / "candidates" / "edge-ai" / "pending").iterdir())
    assert len(pending) == 1


def test_conflic_agent_dedups_via_seen_ledger(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "conflicAgent", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    _patch_claude(monkeypatch, conflic_agent_mod, _fake_claude_reply(_CONFLIC_REPLY))
    first = run_agent("conflicAgent", repo_root)
    assert first.status == "ok"
    first_count = len(list((repo_root / "candidates" / "edge-ai" / "pending").iterdir()))
    assert first_count == 2

    _patch_claude(monkeypatch, conflic_agent_mod, _fake_claude_reply(_CONFLIC_REPLY))
    second = run_agent("conflicAgent", repo_root)
    assert second.status == "ok"
    second_count = len(list((repo_root / "candidates" / "edge-ai" / "pending").iterdir()))
    assert second_count == first_count
    assert "No new conflicts" in (second.message or "")


def test_conflic_agent_handles_empty_list(repo_root, monkeypatch):
    _scaffold_agent(repo_root, "conflicAgent", schedule="manual",
                    config_extra={"domain": "edge-ai"})
    _scaffold_domain(repo_root, "edge-ai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _patch_claude(monkeypatch, conflic_agent_mod,
                  _fake_claude_reply("```yaml\nconflicts: []\n```"))

    result = run_agent("conflicAgent", repo_root)
    assert result.status == "ok"
    assert "No new conflicts" in (result.message or "")
    pending = list((repo_root / "candidates" / "edge-ai" / "pending").iterdir())
    assert pending == []
