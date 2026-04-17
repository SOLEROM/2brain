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

| URL | Purpose |
|-----|---------|
| `/candidates/edge-ai` | Review queue — pending candidates awaiting approval |
| `/candidates/edge-ai/<file>` | Review a single candidate page |
| `/wiki/edge-ai` | Browse approved knowledge pages |
| `/query/edge-ai?q=NNAPI` | Search approved + candidate pages |

## Ingest a source

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

1. Open the web UI → **Review Queue**
2. Click a candidate title to read it
3. Click **Approve** — the page moves to `domains/edge-ai/concepts/` (or wherever `target_path` points)
4. Click **Reject** to move it to `candidates/edge-ai/rejected/`

Or from Python:

```python
from src.approval import approve_candidate

approve_candidate("cand_20260416_161007_nnapi-overview_a83f91c2.md", "edge-ai", reviewed_by="vlad")
```

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
