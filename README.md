# 2brain

A file-based, multi-domain AI knowledge wiki. Raw sources are digested by Claude into Markdown candidate pages, reviewed through a web UI, and promoted into approved knowledge trees with visible confidence scores and inline contradictions.

## Requirements

- Python 3.10+
- An Anthropic API key (for digest and deep research)

## Setup

```bash
# 1. Clone and enter the repo
cd /data/proj/agents/2brain

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Bootstrap your first domain (already done for edge-ai)
bash scripts/init-domain.sh my-domain
```

## Run the web UI

```bash
bash run.sh
```

Opens at **http://localhost:5000**

Or manually:

```bash
python -m uvicorn src.web.app:get_app --factory --host 127.0.0.1 --port 5000
```

## Web UI pages

Root `/` redirects to `/wiki/<current_domain>`. Top nav is ordered so readers land on the wiki first.

| URL | Purpose |
|-----|---------|
| `/wiki/<domain>` | Browse approved pages — **wiki / graph / list / cards / compact** views with title + date + tag filters. Wiki view renders the LLM-maintained `index.md` landing page + an orphans chapter; graph view is an interactive Cytoscape map of wikilink / shared-source / related edges |
| `/wiki/<domain>/page/<rel_path>` | Read a single approved page. **Edit** button opens a markdown editor that overwrites the working version (git preserves history, `updated_at` auto-bumps on save) |
| `/ingest` | Add a raw source (URL or pasted text). GitHub URLs auto-fetch README + top-level tree. |
| `/digest` | Run the digest agent with a live SSE event log (verbose by default). Shows in-progress jobs. |
| `/candidates/<domain>` | Review queue — approve (optionally dropping raw source), reject, or delete |
| `/candidates/<domain>/<file>` | Candidate detail with rendered markdown + raw editor |
| `/query/<domain>?q=...` | Substring-scored search over approved + candidate pages |
| `/ask/<domain>?q=...` | LLM-grounded Ask — answers use approved pages (plus optional candidates) with `[APPROVED]`/`[CANDIDATE]` citations |
| `/health/<domain>` | Lint report — low-confidence / contradictions / orphans / stale / stuck jobs |
| `/agents` | Catalogue of registered agents (wikiGraph, wikiLLM, deepSearch, …) — schedule, last-run status, Run-now |
| `/agents/<name>` | Agent detail — edit `config.yaml` (model pick, schedule, tokens, domain, prompt) and `prompt.md`; manual trigger |
| `/jobs` | All job records. Per-row checkboxes + bulk delete + delete-all per state / globally |
| `/jobs/<state>/<file>` | Job detail with full event log (auto-refreshes while running) |
| `/sources` | Every raw source — Read / Digest / Delete |
| `/sources/<raw_id>` | Raw source preview + metadata |
| `/config` | Edit `config/app.yaml` — add/rename/delete domains, model catalog (main + secondary + available), theme, source types, suggested tags, digest limits, lint thresholds. Domain delete requires typing the name twice. |
| `/about` | System explainer |

The top bar has:

- A **domain picker** (session-wide; persists in a cookie — no per-page domain dropdowns).
- A **theme toggle** that cycles through `light → dark → hackers-green` (or whatever's in `ui.themes`). Choice persists in `localStorage`.

## Ingest a source

Simplest: open `/ingest` in the web UI, paste a URL or text, click Ingest.

- **GitHub URLs** are handled specially: the ingester fetches the repo's
  README (via the GitHub API) **and** the top-level directory tree,
  composes them into one markdown document, and tags the raw source
  `github` + owner. Blob URLs (`.../blob/<branch>/<path>`) fetch the raw
  file content.
- **Other URLs** are fetched with `httpx.get` and the HTML `<title>` is
  extracted as the source title.

Tell the agent in a Claude Code session:

```
Ingest this source: https://example.com/article-about-nnapi
```

Or from Python:

```python
from src.ingest import ingest_source

raw_id = ingest_source(
    content="# NNAPI Overview\nNNAPI is Android's Neural Networks API...",
    title="NNAPI Overview",
    source_type="text",
    domain_hint="edge-ai",
)
print(raw_id)  # raw_20260416_153042_nnapi-overview_a91f03bc
```

Raw sources land in `inbox/raw/<raw_id>/`.

## Digest a source to a candidate page

```python
from src.digest import digest_raw

candidates = digest_raw("raw_20260416_153042_nnapi-overview_a91f03bc", "edge-ai")
# Candidates written to candidates/edge-ai/pending/
```

Or tell the agent: `Digest raw_20260416_153042_nnapi-overview_a91f03bc into edge-ai`

## Approve a candidate

1. Open the web UI → **Review**
2. Click a candidate title to read it
3. Click **Approve** — the page moves to `domains/edge-ai/concepts/` (or wherever `target_path` points)
4. Click **Reject** to move it to `candidates/edge-ai/rejected/`

Approving a `create`/`update`/`replace`/`merge` candidate will **also delete
its cited raw source(s)** by default (checkbox on the detail page, hidden
input on the list view — uncheck to preserve the raw). Destroys nothing on
`archive`/`move`/`split`.

Or from Python:

```python
from src.approval import approve_candidate

approve_candidate("cand_20260416_161007_nnapi-overview_a83f91c2.md", "edge-ai", reviewed_by="vlad")
```

## Edit an approved page

Approved pages aren't frozen — open any page under `/wiki/<domain>/page/...`
and click **Edit page** to rewrite its markdown (frontmatter + body) in a
textarea. Saving overwrites the working file; git history keeps the prior
version, `updated_at` is bumped automatically, and the change is logged
to `domains/<domain>/log.md` and `audit/approvals.log`.

## Agents

Registered background workers live under `agents/<name>/` (config, prompt,
state, seen ledger). The built-ins:

- **digest** — raw → candidate pipeline (runs on-demand via `/digest`).
- **wikiGraph** — no-LLM builder for `indexes/connections.json`; powers the graph view.
- **wikiLLM** — maintains `domains/<d>/index.md` as the wiki landing page.
- **deepSearch** — investigates a research question across the wiki, files a `deep-research-report` candidate.

Each agent's model, schedule (`off` / `manual` / `hourly` / `daily` / `weekly`),
work scope (`all` / `new`), and prompt are editable from `/agents/<name>`.
The model dropdown is populated from `config/app.yaml → models.available`,
with `models.main` / `models.secondary` flagged inline.

## Query the knowledge base

```python
from src.query import search_pages

results = search_pages("NNAPI delegate fallback", "edge-ai")
for r in results:
    print(f"[{r.status.upper()}] {r.title}  confidence={r.confidence:.2f}")
```

## Run a health check

```python
from src.lint import lint_domain

report = lint_domain("edge-ai")
print(f"Low confidence: {len(report.low_confidence_pages)}")
print(f"Unresolved contradictions: {len(report.unresolved_contradictions)}")
print(f"Orphaned pages: {len(report.orphans)}")
# Index files written to domains/edge-ai/indexes/
```

## Add a second domain

```bash
bash scripts/init-domain.sh robotics
# Then edit domains/robotics/schema.md to describe your domain
```

## Run tests

```bash
python -m pytest tests/ -v
```

## File layout

```
2brain/
  config/          # app.yaml, agents.yaml
  inbox/raw/       # immutable raw sources
  candidates/      # pending / rejected / archived candidates
  domains/         # approved knowledge trees
  jobs/            # digest and research job records
  audit/           # approval and ingest logs
  src/             # Python source
  scripts/         # shell utilities
  tests/           # pytest suite
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes (for digest/research) | Your Anthropic API key |

## Further reading

- `CLAUDE.md` — full operating manual (file layout, naming, page format,
  approval semantics, web UI reference).
- `lessons-gui.md` — GUI best practices / design rules distilled from this
  project. Reusable as a skill file for future Python + Jinja apps.
