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
- **Whole-page approval** — the unit of review is the full page, not individual claims

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
      YYYY-MM-DD_HHMM_slug/
        source.md
        metadata.yaml
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
      questions/
      indexes/
        contradictions.md    ← auto-generated from inline blocks
        low-confidence.md    ← pages below threshold
        stale-pages.md       ← pages not updated in a while
        suggested-sources.md ← agent-discovered source suggestions

  jobs/
    queued/
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

## Page Format

Every page — candidate or approved — uses this structure:

```markdown
---
title: "Page Title"
domain: "edge-ai"
type: "source-summary"          # see types below
status: "candidate"             # candidate | approved | rejected | archived | superseded
confidence: 0.72                # 0.00–1.00
sources:
  - raw_id: "raw_2026_04_16_1530"
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
---

# Page Title

## Summary
...

## Key Claims

- Claim text.
  **Confidence:** 0.72
  **Evidence:** source section reference.

## Inline Contradictions

> [!contradiction]
> **Conflict:** This page says X, but [[Other Page]] says Y.
> **Possible explanation:** ...
> **Confidence:** 0.61
> **Status:** unresolved

## Links

- [[Related Page]]
- [[Another Page]]
```

### Required frontmatter fields
`title`, `domain`, `type`, `status`, `confidence`, `sources`, `created_at`, `updated_at`, `tags`

### Optional frontmatter fields
`generated_by`, `reviewed_by`, `reviewed_at`, `supersedes`, `related_pages`, `open_questions`

### Page types
`source-summary`, `concept`, `entity`, `topic`, `comparison`, `research-report`, `deep-research-report`, `contradiction-note`, `question-answer`

### Confidence scale
| Score | Label | Meaning |
|------:|-------|---------|
| 0.90–1.00 | Very high | Strong source support |
| 0.75–0.89 | High | Good support, minor uncertainty |
| 0.55–0.74 | Medium | Useful but needs review/context |
| 0.35–0.54 | Low | Weak, incomplete, or inferred |
| 0.00–0.34 | Very low | Speculative or unresolved |

---

## Knowledge Lifecycle

```
raw source (immutable)
  → digest agent
    → candidate page (pending/)
      → human review
        → approve  → domains/<domain>/<type>/page.md  (status: approved)
        → reject   → candidates/<domain>/rejected/
        → edit & approve → same as approve
        → regenerate → new candidate, old one archived
```

Raw sources are **never modified**. Agents read them but do not write to `inbox/raw/`.

Candidates only graduate to the approved tree via explicit human approval action.

---

## Agent Operations

### Ingest
When a new source arrives:
1. Store it in `inbox/raw/YYYY-MM-DD_HHMM_slug/` with `source.md` and `metadata.yaml`
2. Log the ingest in the relevant `domains/<domain>/log.md` and `audit/ingest.log`
3. Do not auto-digest unless instructed

### Digest
When asked to digest a raw source:
1. Read `inbox/raw/<id>/source.md` and assets
2. Produce one or more candidate pages in `candidates/<domain>/pending/`
3. Each candidate must have complete frontmatter
4. Identify and annotate any contradictions with existing approved or candidate pages
5. Propose `[[wikilinks]]` to existing pages; do not invent links that don't exist yet
6. Update `domains/<domain>/log.md` with a digest entry

### Query
When answering a question:
1. Read `domains/<domain>/index.md` first to identify relevant pages
2. Search both `domains/` (approved) and `candidates/<domain>/pending/` (candidates)
3. Structure answers as:
   - **Answer** — based on approved knowledge
   - **Candidate Additions** — from pending candidates (clearly labeled)
   - **Conflicts / Uncertainty** — contradictions or gaps
   - **Suggested Next Actions** — follow-up research, missing sources
4. Every citation must include a status badge: `[APPROVED]` or `[CANDIDATE]`
5. Good answers should be filed back into the wiki as new candidate pages

### Deep Research
When running a deep research job:
1. Investigate the question across: approved pages, candidate pages, raw sources, (web if enabled)
2. Produce a `deep-research-report` candidate page
3. Follow the deep research report template (Research Question, Short Answer, Evidence Summary, Findings, Contradictions/Uncertainty, Suggested New Pages, Suggested Follow-Up Research, Proposed Tree Placement)
4. Output goes to `candidates/<domain>/pending/`
5. Log the job in `jobs/completed/` and `audit/agent-actions.log`

### Lint / Health Check
When asked to health-check the wiki:
- Find pages with no inbound links (orphans)
- Find claims superseded by newer sources
- Find `[!contradiction]` blocks with status `unresolved`
- Regenerate `domains/<domain>/indexes/contradictions.md`
- Regenerate `domains/<domain>/indexes/low-confidence.md`
- Suggest new pages for concepts mentioned but not yet written
- Suggest follow-up research questions

### Source Discovery
Agents may suggest sources automatically. Suggestions go to:
- `inbox/suggested_sources/` or `domains/<domain>/indexes/suggested-sources.md`

Each suggestion must include: URL, title, why it matters, suggested domain, suggested research question, confidence, discovery date.

Agents may **never** promote a suggested source directly into the approved tree. The pipeline is always:
```
agent suggestion → raw source → digest → candidate → human approval → approved tree
```

---

## Index and Log Conventions

### index.md
- Content catalog: every approved page listed with link, one-line summary, type, confidence
- Organized by category (topics, concepts, entities, etc.)
- Agent updates it on every ingest, approval, or major edit
- Used by agent to navigate the domain before answering queries

### log.md
- Append-only. Never delete entries.
- Entry format: `## [YYYY-MM-DD] <operation> | <title>`
- Operations: `ingest`, `digest`, `approve`, `reject`, `deep-research`, `lint`, `query-filed`
- Example: `## [2026-04-16] ingest | VOXL 2 NNAPI Benchmark Blog`

---

## Contradiction Handling

Contradictions are annotated **inline** inside the relevant page using callout blocks:

```markdown
> [!contradiction]
> **Conflict:** ...
> **Possible explanation:** ...
> **Confidence:** 0.61
> **Status:** unresolved
```

Valid statuses: `unresolved`, `explained`, `superseded`, `rejected`, `needs-source`, `version-dependent`

The file `domains/<domain>/indexes/contradictions.md` is auto-generated by scanning all pages for `[!contradiction]` blocks. Do not edit it manually.

---

## Domain Schema

Each domain has a `schema.md` that tells agents how to write pages for that domain. Read it before digesting or writing pages in a domain.

The `edge-ai` domain schema covers: chips, boards, models, benchmarks, operators, vendors, toolchains, reports. Benchmark pages must include: hardware, model, runtime, quantization, input shape, latency, power, accuracy (if known).

---

## Rules the Agent Must Follow

1. **Never modify raw sources.** `inbox/raw/` is immutable.
2. **Never promote candidates to approved without human action.** Moving files from `candidates/` to `domains/` is a human-triggered operation only.
3. **Always show confidence.** Every page, every cited result.
4. **Always label candidate content.** Use `[CANDIDATE]` in citations and answers.
5. **Keep domain separation.** Do not mix pages across domains without explicit move action.
6. **Keep contradictions inline.** Do not hide them in a separate tracker.
7. **Update index.md and log.md** on every significant operation.
8. **File good answers back into the wiki** as candidate pages so explorations compound.
9. **Read domain schema.md before writing pages** in a new domain.
10. **Deep research output is always a candidate.** Never skip the approval step.

---

## MVP Scope

Must have:
1. File-based multi-domain wiki
2. Raw source inbox
3. Candidate Markdown page generation
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
