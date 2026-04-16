# 2brain — Agent Operating Manual

## What this project is

2brain is a **file-based, multi-domain, human-approved AI knowledge wiki**.

The core idea (from Karpathy): instead of raw-document RAG that re-derives knowledge from scratch on every query, an LLM incrementally builds and maintains a **persistent wiki** of synthesized Markdown pages. Knowledge compounds — cross-references, contradictions, and synthesis are already done when you ask a question.

2brain extends that pattern with:
- **Multi-domain trees** — each domain evolves independently with its own schema
- **Human approval gate** — no raw or agent-generated content becomes trusted knowledge without explicit review
- **Always-visible confidence** — every page, result, and report carries a numeric confidence score
- **Inline contradictions** — conflicts live inside the relevant page, not in a separate tracker
- **Deep research agents** — not just summarization; agents investigate questions across all available knowledge
- **Whole-page approval** — the unit of review is the full page, not individual claims; a candidate may propose creating, updating, replacing, merging, or archiving an approved page

The system should feel like a **Git-backed Obsidian-style wiki with agents, approval, provenance, confidence, and deep research built in**.

The human's role: curate sources, direct research, ask questions, approve or reject candidate pages.
The agent's role: everything else — digesting, synthesizing, cross-referencing, filing, indexing, flagging contradictions.

---

## File Layout

```
2brain/
  CLAUDE.md                  ← this file

  config/
    app.yaml                 ← global system config
    agents.yaml              ← agent behavior config

  inbox/
    raw/                     ← immutable raw sources (never modified after ingest)
      <raw_id>/
        source.md
        metadata.yaml
        original.ext         ← optional: original PDF/HTML if available
        assets/
    suggested_sources/       ← agent-proposed sources awaiting human decision

  candidates/
    <domain>/
      pending/               ← awaiting human review
      rejected/              ← reviewer said no
      archived/              ← superseded candidates

  domains/
    <domain>/
      domain.yaml            ← domain config
      schema.md              ← agent instructions for this domain
      index.md               ← content catalog (agent-maintained)
      log.md                 ← append-only chronological log (agent-maintained)
      topics/
      concepts/
      entities/
      sources/
      reports/
        deep-research/
        comparisons/
        contradictions/
      questions/
      indexes/               ← all auto-generated, do not edit manually
        contradictions.md
        low-confidence.md
        stale-pages.md
        orphans.md
        suggested-sources.md

  jobs/
    queued/                  ← job_<id>.yaml files
    running/
    completed/
    failed/

  audit/
    approvals.log
    ingest.log
    agent-actions.log
```

First domain to build: `domains/edge-ai/` (embedded boards, NPUs, perception models, benchmarks, toolchains).

---

## Naming Conventions

### Raw source ID and folder name

```
Format:  raw_YYYYMMDD_HHMM_<slug>_<hash8>
Example: raw_20260416_1530_voxl2-nnapi_a91f03bc
```

The slug is derived from the source title using slug rules below. The hash8 is the first 8 characters of the SHA-256 of the source URL or content. The raw folder name equals the raw ID.

### Candidate ID and filename

```
Format:  cand_YYYYMMDD_HHMM_<slug>_<hash8>
Example: cand_20260416_1610_voxl2-nnapi-bench_a83f91c2.md
```

The hash8 component makes filenames stable across renames. When a candidate is approved, the candidate ID is preserved in the approved page's frontmatter.

### Slug rules

- Lowercase only
- Spaces and underscores become hyphens
- Remove all punctuation except hyphens
- Collapse consecutive hyphens into one
- Max 60 characters; truncate at a word boundary
- If a conflict exists at the target path, append `-2`, `-3`, or a 4-char hash suffix

Examples:
```
"VOXL 2 NNAPI Benchmark Notes"  →  voxl-2-nnapi-benchmark-notes
"Hailo-8: INT8 vs FP16 Report"  →  hailo-8-int8-vs-fp16-report
```

### Type-to-folder mapping

Agents must use this mapping when proposing a `target_path` for a candidate:

```
source-summary      → domains/<domain>/sources/
concept             → domains/<domain>/concepts/
entity              → domains/<domain>/entities/
topic               → domains/<domain>/topics/
comparison          → domains/<domain>/reports/comparisons/
research-report     → domains/<domain>/reports/
deep-research-report→ domains/<domain>/reports/deep-research/
contradiction-note  → domains/<domain>/reports/contradictions/
question-answer     → domains/<domain>/questions/
```

---

## Raw Source Metadata

Every raw source folder must contain `metadata.yaml`:

```yaml
id:                    # raw_YYYYMMDD_HHMM_slug_hash8
title:
source_type:           # url | pdf | text | repo | image | video | api | note
origin:                # manual | agent | api | import
url:
submitted_by:
ingested_at:           # ISO 8601
content_hash:          # SHA-256 of source content
domain_hint:           # suggested domain, may be empty
tags: []
license:               # if known
fetch_status:          # ok | partial | failed
```

---

## Page Format

Every page — candidate or approved — uses this structure:

```markdown
---
title: "Page Title"
domain: "edge-ai"
type: "source-summary"            # see type list in Naming Conventions
status: "candidate"               # see Status Transitions
confidence: 0.72                  # 0.00–1.00
sources:
  - raw_id: "raw_20260416_1530_voxl2-nnapi_a91f03bc"
    title: "Source Title"
    url: "https://..."
created_at: "2026-04-16T15:30:00+03:00"
updated_at: "2026-04-16T15:40:00+03:00"
generated_by: "digest-agent"
reviewed_by:
reviewed_at:
tags:
  - tag1
  - tag2
# Candidate-only fields (remove or leave blank after approval):
candidate_id: "cand_20260416_1610_voxl2-nnapi-bench_a83f91c2"
candidate_operation: "create"     # create | update | replace | merge | archive | move | split
target_path: "domains/edge-ai/sources/voxl-2-nnapi-benchmark-notes.md"
raw_ids:
  - "raw_20260416_1530_voxl2-nnapi_a91f03bc"
duplicate_of:
possible_duplicates: []
# Approved-only fields (filled in at approval time):
origin_candidate_id:
---

# Page Title

## Summary
...

## Key Claims

Every claim must include evidence. No evidence-free claims.

- VOXL 2 supports NNAPI execution for some TFLite models.
  **Confidence:** 0.78
  **Evidence:** raw_20260416_1530_voxl2-nnapi_a91f03bc, section "Runtime"
  **Evidence type:** direct

Evidence types: `direct` | `derived` | `inferred` | `external-web` | `user-provided` | `unknown`

## Inline Contradictions

> [!contradiction]
> **Conflict:** This page says X, but [[Other Page]] says Y.
> **Possible explanation:** ...
> **Confidence:** 0.61
> **Status:** unresolved

## Suggested New Pages

List concepts that need their own page but do not yet exist. Do not create broken wikilinks.

- Hailo Quantization Constraints
- NNAPI Delegate Fallback Modes

## Links

Only link to pages that already exist.

- [[VOXL 2]]
- [[NNAPI]]
```

### Required frontmatter fields
`title`, `domain`, `type`, `status`, `confidence`, `sources`, `created_at`, `updated_at`, `tags`

### Candidate-only frontmatter fields
`candidate_id`, `candidate_operation`, `target_path`, `raw_ids`

### Approved-only frontmatter fields
`origin_candidate_id`, `reviewed_by`, `reviewed_at`

### Optional frontmatter fields
`generated_by`, `supersedes`, `related_pages`, `open_questions`, `duplicate_of`, `possible_duplicates`

### Confidence scale
| Score | Label | Meaning |
|------:|-------|---------|
| 0.90–1.00 | Very high | Strong source support |
| 0.75–0.89 | High | Good support, minor uncertainty |
| 0.55–0.74 | Medium | Useful but needs review/context |
| 0.35–0.54 | Low | Weak, incomplete, or inferred |
| 0.00–0.34 | Very low | Speculative or unresolved |

---

## Candidate Operations

A candidate page does not always propose a new page. It may propose a change to the approved tree.

The `candidate_operation` field determines what happens when a reviewer approves it.

| Operation | Meaning |
|-----------|---------|
| `create`  | Add a new page to the approved tree at `target_path` |
| `update`  | Replace an existing approved page at `target_path` with this revised version |
| `replace` | Same as update but signals a significant rewrite rather than minor edit |
| `merge`   | Reviewer manually merges this candidate into the existing page at `target_path` |
| `archive` | Propose archiving an existing approved page (move to `.archive/`) |
| `move`    | Propose moving an existing approved page to a new path or domain |
| `split`   | Propose splitting one existing page into multiple; `source_paths` lists the origin |

### Approval semantics by operation

**create:**
- Move candidate to `target_path`
- Set `status: approved`, fill `reviewed_by`, `reviewed_at`, `origin_candidate_id`
- Move candidate file to `candidates/<domain>/archived/`
- Update `domains/<domain>/index.md` and `log.md`

**update / replace:**
- Git history preserves the previous version (no separate `.history/` folder needed)
- Overwrite `target_path` with candidate content
- Set `status: approved` and review fields
- Archive the candidate
- Update index and log

**merge:**
- Reviewer edits the existing approved page directly, incorporating candidate content
- Set candidate `status: archived` with a note
- Log the merge in `log.md`

**archive:**
- Move approved page from `domains/` to `domains/<domain>/.archive/`
- Set `status: archived` in the file
- Remove from `index.md`
- Archive the candidate

**move:**
- Move approved page to new path or domain
- Update all `[[wikilinks]]` pointing to the old path
- Update index in both affected domains
- Archive the candidate

**split:**
- Reviewer creates the target pages (or approves each split candidate separately)
- Archive the original page
- Archive the split proposal candidate

---

## Status Transitions

Valid transitions only:

```
candidate  → approved
candidate  → rejected
candidate  → archived
approved   → superseded
approved   → archived
rejected   → archived
superseded → archived
```

These transitions are **not allowed** without an explicit human restore action:
```
rejected  → approved    ✗
archived  → approved    ✗
```

---

## Knowledge Lifecycle

```
raw source (immutable)
  → digest agent
    → candidate page (candidates/<domain>/pending/)
      → human review
          approve (create)   → domains/<domain>/<folder>/slug.md
          approve (update)   → overwrites target_path, Git preserves history
          approve (merge)    → reviewer edits target page directly
          reject             → candidates/<domain>/rejected/
          edit & approve     → reviewer edits candidate, then approves
          regenerate         → new candidate created, old one archived
```

Raw sources are **never modified**. Agents read from `inbox/raw/` but never write to it.

If a digest fails, write a failure record to `jobs/failed/` and log to `audit/agent-actions.log`. Do not leave partial candidates in `pending/` without marking them `status: partial`.

---

## Agent Operations

### Ingest
When a new source arrives:
1. Generate a raw ID using the naming convention
2. Create `inbox/raw/<raw_id>/` with `source.md`, `metadata.yaml`, and `assets/`
3. If domain is known, log to `domains/<domain>/log.md` and `audit/ingest.log`
4. If domain is unknown, log only to `audit/ingest.log` — do not guess a domain
5. Do not auto-digest unless explicitly instructed or `auto_digest: true` is set in `domain.yaml`

### Digest
When asked to digest a raw source:
1. Read `inbox/raw/<raw_id>/source.md` and any assets
2. Read the target domain's `schema.md` before writing any pages
3. **Check for near-duplicates first.** Search `domains/<domain>/` and `candidates/<domain>/pending/` for pages covering the same subject. If a near-duplicate exists, create an `update` or `merge` candidate instead of a new `create` candidate
4. Assign a candidate ID using the naming convention
5. Produce one or more candidate pages in `candidates/<domain>/pending/`
6. Each candidate must have complete frontmatter including `candidate_operation` and `target_path`
7. Every Key Claim must have an Evidence line (no evidence-free claims)
8. For wikilinks: use `[[Existing Page]]` only for pages that exist. For valuable missing pages, list them in `## Suggested New Pages` instead
9. Annotate any contradictions with existing pages using `[!contradiction]` blocks
10. Create a job record in `jobs/completed/` and update `domains/<domain>/log.md`

### Query
When answering a question:
1. Read `domains/<domain>/index.md` first to identify relevant pages
2. Search both `domains/` (approved) and `candidates/<domain>/pending/` (candidates)
3. Structure the answer as:
   - **Answer** — based on approved knowledge
   - **Candidate Additions** — from pending candidates, clearly labeled
   - **Conflicts / Uncertainty** — contradictions or gaps
   - **Suggested Next Actions** — follow-up research, missing sources
4. Every citation must include a status badge: `[APPROVED]` or `[CANDIDATE]`
5. When an answer contains reusable synthesis, **propose** filing it as a candidate page. Do not create the candidate unless the user instructs. Exception: deep research answers are always filed as candidates automatically

### Deep Research
When running a deep research job:
1. Create a job YAML in `jobs/running/` before starting
2. Investigate the question across: approved pages, candidate pages, raw sources, web (if `web_research.enabled: true` in `domain.yaml`)
3. Produce a `deep-research-report` candidate page using the template (Research Question, Short Answer, Evidence Summary, Findings, Contradictions/Uncertainty, Suggested New Pages, Suggested Follow-Up Research, Proposed Tree Placement)
4. Set `candidate_operation: create` and fill `target_path`
5. Move job to `jobs/completed/` and log to `audit/agent-actions.log`

### Lint / Health Check
When asked to health-check the wiki:
- Find pages with no inbound links → update `indexes/orphans.md`
- Find `[!contradiction]` blocks with `Status: unresolved`
- Find pages with `confidence < 0.35` → update `indexes/low-confidence.md`
- Find pages not updated in 90+ days → update `indexes/stale-pages.md`
- Regenerate `indexes/contradictions.md` by scanning all pages
- Suggest new pages for concepts mentioned but not yet written
- Suggest follow-up research questions

### Source Discovery
Agents may suggest sources automatically. Suggestions go to `domains/<domain>/indexes/suggested-sources.md`.

Each suggestion must include: URL, title, why it matters, suggested domain, suggested research question, confidence, discovery date.

Agents may **never** promote a suggested source directly into the approved tree. The pipeline is always:
```
agent suggestion → raw source → digest → candidate → human approval → approved tree
```

---

## Index and Log Conventions

### Ownership

| File | Owner | Rule |
|------|-------|------|
| `index.md` | Agent | Update on every ingest, digest, approval, archive |
| `log.md` | Agent | Append-only, never delete entries |
| `indexes/contradictions.md` | Auto-generated | Do not edit manually |
| `indexes/low-confidence.md` | Auto-generated | Do not edit manually |
| `indexes/stale-pages.md` | Auto-generated | Do not edit manually |
| `indexes/orphans.md` | Auto-generated | Do not edit manually |
| `indexes/suggested-sources.md` | Auto-generated | Do not edit manually |

### index.md
- Lists every approved page: link, one-line summary, type, confidence
- Organized by category (topics, concepts, entities, sources, reports, questions)
- Agent reads this first when answering any query

### log.md
- Append-only. Never delete entries.
- Entry format: `## [YYYY-MM-DD] <operation> | <title>`
- Operations: `ingest`, `digest`, `approve`, `reject`, `merge`, `archive`, `deep-research`, `lint`, `query-filed`
- Example: `## [2026-04-16] ingest | VOXL 2 NNAPI Benchmark Blog`

### Job files
Job YAML schema (`jobs/<state>/job_<id>.yaml`):

```yaml
job_id:          # job_YYYYMMDD_HHMM_type_hash8
job_type:        # digest | deep-research | lint | source-discovery | query-file
domain:
status:          # queued | running | completed | failed
created_at:
started_at:
completed_at:
input:           # raw_id or research question
outputs: []      # list of candidate_ids or file paths produced
agent:
error:           # if failed
```

---

## Contradiction Handling

Contradictions are annotated **inline** inside the relevant page using callout blocks:

```markdown
> [!contradiction]
> **Conflict:** This page says X, but [[Other Page]] says Y.
> **Possible explanation:** ...
> **Confidence:** 0.61
> **Status:** unresolved
```

Valid statuses: `unresolved`, `explained`, `superseded`, `rejected`, `needs-source`, `version-dependent`

`indexes/contradictions.md` is auto-generated by scanning all pages for `[!contradiction]` blocks. Do not edit it manually.

---

## Domain Schema

Each domain has a `schema.md` that tells agents how to write pages for that domain. **Read it before digesting or writing any pages in a domain.**

The `edge-ai` domain schema covers: chips, boards, models, benchmarks, operators, vendors, toolchains, reports. Benchmark pages must include: hardware, model, runtime, quantization, input shape, latency, power, accuracy (if known).

Domain config (`domain.yaml`) includes a `web_research` section:

```yaml
web_research:
  enabled: false
  max_sources_per_job: 20
```

If `web_research.enabled` is false, agents must not fetch external URLs during deep research jobs.

---

## Git Policy

All file changes are committed to Git. Git history is the version history — no separate `.history/` folder is needed.

Suggested commit message format:
```
<domain>: <operation> <title>

Examples:
edge-ai: approve VOXL 2 NNAPI Benchmark Notes
edge-ai: update NNAPI concept page
edge-ai: digest voxl2-nnapi blog post
robotics: deep-research indoor localization report
```

What to commit: raw sources, candidates, approved pages, indexes, logs, audit logs, job files.

What to exclude from commits: large binary assets (>1MB). Use Git LFS or keep them local if not configured.

---

## Asset Handling

Assets (images, PDFs, diagrams) stay in their raw source folder:
```
inbox/raw/<raw_id>/assets/
```

Candidate and approved pages may reference assets using paths relative to the repo root. Do not copy assets into `domains/`. Do not duplicate assets.

Example reference in a page:
```markdown
![Block diagram](../../inbox/raw/raw_20260416_1530_voxl2-nnapi_a91f03bc/assets/diagram.png)
```

---

## Rules the Agent Must Follow

1. **Never modify raw sources.** `inbox/raw/` is immutable once written.
2. **Never promote candidates to approved without human action.** Moving files from `candidates/` to `domains/` is a human-triggered operation only.
3. **Always show confidence.** Every page, every cited result, every research report.
4. **Always label candidate content.** Use `[CANDIDATE]` in citations and answers.
5. **Keep domain separation.** Do not mix pages across domains without explicit move action.
6. **Keep contradictions inline.** Do not hide them in a separate tracker.
7. **Update index.md and log.md** on every significant operation.
8. **Read domain schema.md before writing pages** in a domain.
9. **Deep research output is always a candidate.** Never skip the approval step.
10. **Check for near-duplicates before creating new candidates.** Prefer update/merge over new pages.
11. **Every Key Claim must have evidence.** No evidence-free claims.
12. **Use wikilinks only for existing pages.** List missing valuable pages in `## Suggested New Pages` instead.
13. **Propose query answers for filing; do not auto-file.** Exception: deep research results are always filed.
14. **Follow slug and naming conventions exactly.** Inconsistent filenames break wiki navigation.
15. **Do not edit auto-generated index files.** Only regenerate them via lint.

---

## MVP Scope

Must have:
1. File-based multi-domain wiki
2. Raw source inbox
3. Candidate Markdown page generation (all candidate operations)
4. Whole-page approval flow
5. Lightweight web UI
6. Approved + candidate query mode
7. Always-visible confidence
8. Inline contradiction blocks
9. Agent source suggestion
10. Deep research report generation
11. Generated index and log files

Out of scope for MVP: claim-level database, graph DB, team permissions, real-time collaboration, model fine-tuning, browser extension.

---

## One-liner

**2brain is a file-based, multi-domain, human-approved AI wiki where raw sources are digested into whole Markdown candidate pages, reviewed through a lightweight web UI, promoted into approved knowledge trees, and continuously improved by deep-research agents with visible confidence and inline contradictions.**
