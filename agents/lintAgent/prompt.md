# lintAgent

lintAgent does not call an LLM, so this file is not consumed by the agent.
The scan rules live in code (`src/lint.py`) and the thresholds live in
`config/app.yaml → lint` (with optional per-agent overrides in this
folder's `config.yaml`).

To change lint behaviour, edit:

- `config/app.yaml → lint` — `stale_days`, `stuck_job_minutes`, `low_confidence_threshold`
- `src/lint.py` — the scanning logic itself
- `config.yaml` (this folder) — which domain(s) to lint and optional threshold overrides
