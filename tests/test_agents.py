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

    def _fake_run(*, meta, repo_root, job_id, question_override=None):
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
