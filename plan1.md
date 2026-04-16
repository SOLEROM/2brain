<!-- /autoplan restore point: /home/user/.gstack/projects/SOLEROM-2brain/main-autoplan-restore-20260416-144132.md -->
# 2brain Designs

| Area                | Decision                                     |
| ------------------- | -------------------------------------------- |
| Approved layer      | **File/wiki-oriented**                       |
| Approval unit       | **Whole page**                               |
| Workspace model     | **Multiple domain trees**                    |
| Knowledge format    | **Flexible Markdown**                        |
| Query scope         | **Approved + candidate content included**    |
| Source discovery    | **Agents may suggest sources automatically** |
| Review UI           | **Lightweight reviewer editing**             |
| Confidence          | **Always visible**                           |
| Contradictions      | **Inline annotations**                       |
| Main agent strength | **Deep research**                            |

---

# 2brain — Refined System Spec

## 1. Product Definition

**2brain is a multi-domain, file-based AI knowledge wiki system.**

It ingests raw sources, digests them into complete Markdown candidate pages, lets a human approve or reject each whole page, and then promotes approved pages into one or more domain-specific knowledge trees.

Agents can search for new sources, perform deep research, propose new candidate pages, maintain cross-links, and annotate contradictions inline. Users interact through a lightweight web UI that supports review, browsing, querying, and research workflows.

The main storage model is simple:

```text
2brain/
  domains/
    edge-ai/
    robotics/
    investing/
    personal/
  inbox/
  candidates/
  logs/
  config/
```

The system should feel like a **Git-backed Obsidian-style wiki with agents, approval, provenance, confidence, and deep research built in**.

---

# 2. Core Architecture

## 2.1 File-Based Domain Trees

Each domain is an independent knowledge tree.

Example:

```text
2brain/
  domains/
    edge-ai/
      index.md
      log.md
      topics/
      concepts/
      entities/
      sources/
      reports/
      questions/

    robotics/
      index.md
      log.md
      topics/
      concepts/
      entities/
      sources/
      reports/
      questions/
```

Each domain can have its own:

```text
domain.yaml
schema.md
agent_policy.md
index.md
log.md
```

This allows different domains to evolve differently. For example, an **Edge AI** tree may care about chips, benchmarks, operators, models, vendors, power, and latency, while a **business intelligence** tree may care about companies, products, people, funding, market movements, and risks.

---

# 3. Knowledge Lifecycle

## 3.1 Raw Input

Raw sources enter the system through:

* manual URL submission
* pasted notes
* uploaded files
* web UI forms
* API calls from future tools
* agent-suggested sources
* periodic deep-research jobs

Raw inputs are stored immutably.

Example:

```text
inbox/raw/
  2026-04-16_1530_voxl2-nnapi-blog/
    source.md
    metadata.yaml
    assets/
```

## 3.2 Digest to Candidate Page

The digest phase produces **whole candidate pages**, not fragments.

A candidate page may be:

* source summary page
* concept page
* entity page
* topic page
* comparison page
* research report
* contradiction note
* deep research synthesis
* question answer page

Example:

```text
candidates/edge-ai/
  pending/
    2026-04-16_voxl2-nnapi-benchmark.md
```

Candidate pages contain all metadata needed for review.

---

# 4. Page Format

Because you chose **flexible Markdown**, the system should not require a rigid database schema for every claim. But every page should still have a lightweight frontmatter block.

## 4.1 Standard Markdown Page Template

```markdown
---
title: "VOXL 2 NNAPI Benchmark Notes"
domain: "edge-ai"
type: "source-summary"
status: "candidate"
confidence: 0.72
sources:
  - raw_id: "raw_2026_04_16_1530"
    title: "VOXL 2 NNAPI Benchmark Blog"
    url: "https://example.com/post"
created_at: "2026-04-16T15:30:00+03:00"
updated_at: "2026-04-16T15:40:00+03:00"
generated_by: "digest-agent"
reviewed_by:
reviewed_at:
tags:
  - voxl
  - nnapi
  - edge-ai
---

# VOXL 2 NNAPI Benchmark Notes

## Summary

...

## Key Claims

- Claim text here.  
  **Confidence:** 0.72  
  **Evidence:** source paragraph / section reference.

## Notes

...

## Inline Contradictions

> [!contradiction]
> This source appears to conflict with [[VOXL 2 Delegate Support]] regarding NNAPI behavior.
> Existing page says: ...
> New source says: ...
> Suggested reviewer action: keep both, clarify version dependency.

## Links

- [[VOXL 2]]
- [[NNAPI]]
- [[TFLite Delegates]]
```

## 4.2 Required Frontmatter Fields

Minimum required fields:

```yaml
title:
domain:
type:
status:
confidence:
sources:
created_at:
updated_at:
tags:
```

## 4.3 Optional Frontmatter Fields

```yaml
generated_by:
reviewed_by:
reviewed_at:
supersedes:
related_pages:
open_questions:
```

---

# 5. Whole-Page Approval

Since approval is at the **whole page** level, the candidate review flow should be simple and fast.

## 5.1 Review Actions

Reviewer can:

* approve page
* reject page
* edit and approve
* request regeneration
* move to another domain
* change page type
* merge manually into existing page
* mark as duplicate

## 5.2 Approval Rule

A candidate becomes trusted only when the whole page is approved.

When approved:

```yaml
status: "approved"
reviewed_by: "user"
reviewed_at: "timestamp"
```

The file moves from:

```text
candidates/edge-ai/pending/page.md
```

to:

```text
domains/edge-ai/topics/page.md
```

or another approved path.

## 5.3 Whole-Page Tradeoff

Whole-page approval is simpler than claim-level approval, but it means the page should clearly label weak parts. This is why confidence must always be visible and contradictions should be inline.

A page can be approved even if it contains uncertain claims, as long as they are marked clearly.

---

# 6. Candidate Inclusion in Queries

You chose to include candidate content in queries. That is powerful but must be visually explicit.

## 6.1 Query Scope

Default query should search:

```text
approved + candidates
```

But answers must label source status:

```text
[APPROVED] Edge AI / VOXL 2 / NNAPI.md
[CANDIDATE] pending / new_hailo_report.md
```

## 6.2 Answer Rules

When answering, the system should separate:

* approved knowledge
* candidate knowledge
* conflicts
* missing evidence
* suggested follow-up

Example answer structure:

```markdown
## Answer

Based on approved knowledge...

## Candidate Additions

Pending candidate pages suggest...

## Conflicts / Uncertainty

...

## Suggested Next Actions

...
```

## 6.3 UI Requirement

Every query result must show a status badge:

* Approved
* Candidate
* Rejected
* Archived
* Superseded

This prevents candidate material from accidentally being treated as trusted.

---

# 7. Confidence Always Visible

Confidence should appear everywhere:

* page cards
* page header
* review queue
* search results
* query citations
* contradiction blocks
* deep research reports

## 7.1 Confidence Levels

Suggested mapping:

|     Score | Label     | Meaning                         |
| --------: | --------- | ------------------------------- |
| 0.90–1.00 | Very high | Strong source support           |
| 0.75–0.89 | High      | Good support, minor uncertainty |
| 0.55–0.74 | Medium    | Useful but needs review/context |
| 0.35–0.54 | Low       | Weak, incomplete, or inferred   |
| 0.00–0.34 | Very low  | Speculative or unresolved       |

## 7.2 Page Header Display

```text
Status: Candidate
Confidence: Medium, 0.68
Sources: 3
Contradictions: 1
Last updated: 2026-04-16
```

---

# 8. Inline Contradictions

Contradictions should live inside pages where the user reads them, not hidden in a separate issue tracker.

## 8.1 Markdown Format

Use callout blocks:

```markdown
> [!contradiction]
> **Conflict:** This page says the model uses NNAPI, but [[Benchmark Result A]] says the same model fell back to CPU.
> **Possible explanation:** Different firmware version or delegate flags.
> **Confidence:** 0.61
> **Status:** unresolved
```

## 8.2 Contradiction Statuses

* unresolved
* explained
* superseded
* rejected
* needs-source
* version-dependent

## 8.3 Indexing Contradictions

Even though contradictions are inline, the system should maintain a generated contradiction index:

```text
domains/edge-ai/indexes/contradictions.md
```

This page is generated automatically by scanning inline contradiction blocks.

---

# 9. Deep Research Agents

You selected **deep research** as a central capability.

## 9.1 Deep Research Job Purpose

A deep research agent should not merely summarize one source. It should investigate a research question across:

* approved pages
* candidate pages
* raw source archive
* web sources, if enabled
* previous research reports

## 9.2 Deep Research Output

Every deep research job should produce a candidate page.

Example:

```text
candidates/edge-ai/pending/
  2026-04-16_deep-research_hailo-vs-jetson-perception-ops.md
```

## 9.3 Deep Research Report Template

```markdown
---
title: "Hailo vs Jetson for Perception Micro-Benchmarks"
domain: "edge-ai"
type: "deep-research-report"
status: "candidate"
confidence: 0.74
sources:
  - ...
tags:
  - hailo
  - jetson
  - benchmarks
---

# Hailo vs Jetson for Perception Micro-Benchmarks

## Research Question

...

## Short Answer

...

## Evidence Summary

...

## Findings

### Finding 1

...

### Finding 2

...

## Contradictions / Uncertainty

> [!contradiction]
> ...

## Suggested New Pages

- [[Hailo8 Quantization Constraints]]
- [[Jetson TensorRT Benchmarking Method]]

## Suggested Follow-Up Research

...

## Proposed Tree Placement

`domains/edge-ai/reports/hailo-vs-jetson-perception-ops.md`
```

---

# 10. Source Discovery Agents

You chose “yes” for automatic source suggestions.

## 10.1 Allowed Behavior

Agents may:

* search for relevant new sources
* suggest URLs
* rank sources by relevance
* create raw source candidates
* propose research tasks

## 10.2 Approval Boundary

Agents may not silently promote external findings into approved knowledge.

Pipeline:

```text
agent discovery
  → source suggestion
  → raw source item
  → digest
  → candidate page
  → human approval
  → approved tree
```

## 10.3 Source Suggestion Page

The system should keep:

```text
domains/<domain>/indexes/suggested-sources.md
```

or a UI panel with:

* URL
* title
* why it matters
* suggested domain
* suggested research question
* confidence
* discovery agent
* date found

---

# 11. Lightweight Review UI

The review UI should optimize for fast triage, not heavy document editing.

## 11.1 Candidate Review Screen

Left panel:

* candidate page rendered as Markdown

Right panel:

* metadata
* confidence
* source list
* proposed target path
* detected links
* detected contradictions
* actions

Bottom or side:

* lightweight editor for direct fixes

## 11.2 Must-Have Review Actions

* Approve
* Reject
* Edit & Approve
* Regenerate
* Move domain
* Mark duplicate

## 11.3 Nice-to-Have

* side-by-side diff
* preview final approved path
* one-click “open source”
* one-click “show related approved pages”

---

# 12. Multi-Domain Tree Design

## 12.1 Domain Config

Each domain should have a config file:

```yaml
name: edge-ai
display_name: "Edge AI"
description: "Embedded AI, NPUs, perception models, benchmark systems"
default_query_scope: "approved+candidates"
confidence_visible: true
approval_unit: "page"
contradiction_style: "inline"
source_discovery: true
deep_research_enabled: true
```

## 12.2 Domain Schema Document

Each domain may also include:

```text
domains/edge-ai/schema.md
```

This tells agents how to write and organize that domain.

Example:

```markdown
# Edge AI Domain Schema

## Preferred page types

- chip
- board
- model
- benchmark
- operator
- vendor
- toolchain
- report

## Link conventions

- Link boards to chips.
- Link models to runtime backends.
- Link benchmarks to hardware and model pages.

## Required details for benchmark pages

- hardware
- model
- runtime
- quantization
- input shape
- latency
- power
- accuracy, if known
```

This is important because each domain can have different logic.

---

# 13. File Layout

Recommended layout:

```text
2brain/
  config/
    app.yaml
    agents.yaml

  inbox/
    raw/
    suggested_sources/

  candidates/
    edge-ai/
      pending/
      rejected/
      archived/
    robotics/
      pending/
      rejected/
      archived/

  domains/
    edge-ai/
      domain.yaml
      schema.md
      index.md
      log.md
      topics/
      concepts/
      entities/
      sources/
      reports/
      questions/
      indexes/
        contradictions.md
        low-confidence.md
        stale-pages.md

    robotics/
      domain.yaml
      schema.md
      index.md
      log.md
      topics/
      concepts/
      entities/
      sources/
      reports/
      questions/
      indexes/

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

This keeps the system inspectable with normal Linux tools, Git, and external editors.

---

# 14. MVP Definition

Given your decisions, the best MVP is:

## MVP must include

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

## MVP can skip

* claim-level database
* complex graph DB
* team permissions
* fine-grained workflow automation
* real-time collaborative editing
* model fine-tuning
* complex browser extension

---

# 15. V1 User Stories

## Ingest

As a user, I can submit a URL or file so that 2brain stores it as a raw source.

## Digest

As a user, I can ask the system to digest a raw source into a candidate Markdown page.

## Review

As a reviewer, I can approve, reject, edit, or regenerate a candidate page.

## Knowledge Tree

As a user, I can browse approved pages by domain and folder structure.

## Query

As a user, I can ask a question and receive an answer that clearly separates approved and candidate knowledge.

## Confidence

As a user, I can always see the confidence level of a page or query result.

## Contradictions

As a user, I can see contradictions inline inside the relevant page.

## Deep Research

As a user, I can launch a deep research job from a question and receive a candidate research report.

## Source Discovery

As a user, I can see agent-suggested sources and choose which ones to ingest.

---

# 16. Acceptance Criteria

## Candidate approval

A candidate page is not added to the approved tree until a reviewer approves the whole page.

## Query visibility

If candidate content is used in an answer, it must be labeled as candidate.

## Confidence visibility

Every page, candidate, query result, and research report must show confidence.

## Contradiction handling

Contradictions must be rendered inline in Markdown and indexed automatically.

## File transparency

All approved knowledge must be readable as Markdown files outside the web UI.

## Domain separation

Pages from one domain must not be silently merged into another domain without an explicit move or approval action.

## Deep research

Every deep research output must become a candidate page before it can become approved knowledge.

---

# 17. Strong First Domain to Build With

For you, I would start the first 2brain domain as:

```text
domains/edge-ai/
```

Because you already have many natural source types:

* embedded boards
* NPUs
* perception models
* benchmark results
* ONNX/TFLite/TensorRT/RKNN/Hailo toolchains
* vendor docs
* hardware notes
* power/latency/accuracy comparisons

A useful first deep research task could be:

```text
What are the common atomic perception operations that should be used to benchmark embedded AI accelerators across Jetson, Hailo, RK3588, MAX78000, VOXL 2, and Coral?
```

That would immediately produce valuable candidate pages for your benchmark system idea.

---

# 18. Final Refined One-Liner

**2brain is a file-based, multi-domain, human-approved AI wiki where raw sources are digested into whole Markdown candidate pages, reviewed through a lightweight web UI, promoted into approved knowledge trees, and continuously improved by deep-research agents with visible confidence and inline contradictions.**

---

# /autoplan Review Findings

## Cross-Phase Themes

**Theme: "The spec describes WHAT but not HOW for operational/developer concerns"**
Flagged in CEO Phase (curation fatigue, no success metrics), Eng Phase (atomic writes, job stale lock, schema validator), and DX Phase (no init script, undefined config files). All three independent subagents converged on this. High-confidence signal. Fix: before writing a line of code, fill the operational gaps in CLAUDE.md and plan1.md.

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|---------------|-----------|-----------|---------|
| 1 | CEO | Use Approach C: CC agents + minimal web server UI | Mechanical | P5 | Matches spec, least abstraction | Approach A (no UI), B (too much infra) |
| 2 | CEO | Include all 4 test layers (unit/integration/e2e/regression) | Mechanical | P1 | Completeness — all layers needed | None |
| 3 | CEO | Scheduled jobs deferred to TODOS.md | Mechanical | P2 | Outside MVP blast radius | None |
| 4 | CEO | Add confidence calibration rubric to schema.md | Mechanical | P1 | 10-line addition, prevents useless scores | None |
| 5 | CEO | Add candidate aging config + lint rule (MVP) | Mechanical | P1 | Prevents curation backlog rot | None |
| 6 | CEO | Competitive analysis → nice-to-have in plan doc, not blocking MVP | Mechanical | P3 | Not blocking implementation | None |

## CEO Phase Findings

### Critical Gaps
1. **Curation fatigue** (Critical) — No mechanism for review queue pressure management. Fix: `max_candidate_age_days` in domain.yaml + lint rule to auto-archive stale candidates. **[ADDED TO MVP]**
2. **Confidence calibration** (High) — Scale defined, algorithm undefined. Fix: add explicit rubric to schema.md specifying how agents assign scores. **[ADDED TO MVP]**
3. **Wikilink validation at approval** (High) — When a candidate is approved, broken wikilinks are not checked. Fix: approval step should validate all `[[links]]` resolve to existing files.
4. **Timestamp collision in raw IDs** (Medium) — Two ingests in the same minute produce identical HHMM prefix. Fix: use HHMMSS or add counter suffix.
5. **index.md drift** (Medium) — No repair command if index.md gets out of sync. Fix: lint should detect and report orphaned/missing index entries.

### NOT in Scope (MVP)
- Scheduled background jobs (cron/Celery)
- Multi-user team permissions
- Claim-level database
- Browser extension
- Competitive analysis document
- Query analytics log

## Eng Phase Findings

### Architecture Concerns
1. **Flat-file concurrency (Critical)** — index.md + log.md need atomic write-then-rename pattern. Two concurrent operations silently corrupt.
2. **Frontmatter schema validator (Critical)** — LLM agent output must be validated before writing to pending/. Required fields, confidence range [0,1], status values.
3. **Path traversal in target_path (Critical/Security)** — Must validate target_path is within domains/<domain>/ before any file operation.
4. **Content sanitization on ingest (High/Security)** — Raw source content with YAML frontmatter delimiters must be escaped.
5. **jobs/running stale lock (High)** — Add heartbeat_at field + lint rule for >10min stale jobs.
6. **Web UI process model (High)** — job YAML as handoff, UI polls for job status. Must be explicitly specified.
7. **index.md O(n) at scale (Medium)** — append-only format or bulk regeneration via lint.
8. **merge operation (Medium)** — entirely manual with no tooling. TASTE DECISION #2 (see gate).

### Security Threat Model
| Threat | Vector | Fix |
|--------|--------|-----|
| Path traversal | target_path frontmatter field | Validate within domains/<domain>/ |
| Frontmatter injection | Raw source fetch content | Sanitize --- delimiters on ingest |
| Status spoofing | Raw content with status: approved | Never trust status from raw sources |

### Test Plan
Full test plan written to: `~/.gstack/projects/SOLEROM-2brain/main-test-plan-20260416.md`
Covers: unit (slug, frontmatter, log, contradiction scanner), integration (ingest, digest, lint), E2E (approval flow, web UI), security (path traversal, injection).

### TASTE DECISION #2: `merge` operation in MVP
- Option A: Keep `merge` as fully manual (reviewer edits target page directly) — no tooling, no diff
- Option B: Scope `merge` out of MVP entirely — only support create/update/replace/archive/reject at MVP
Surfacing at final gate.

## Design Phase Findings

### Design Scores (pre-review)
| Dimension | Score | Finding |
|-----------|-------|---------|
| Information hierarchy | 3/10 | Confidence/operation type buried in right panel — move to sticky banner |
| Interaction states | 2/10 | Zero states defined (empty queue, loading, error, partial, post-action) |
| User journey | 4/10 | No sticky action bar, no queue position indicator, no keyboard shortcuts |
| Component specificity | 3/10 | No wireframe, editor undefined, no color convention for badges |
| Edit & Approve workflow | 2/10 | Multi-state workflow undefined — edit/save/approve/lose-edit paths all missing |
| Query UI | 1/10 | Query input interaction pattern entirely absent from spec |
| Overall | 3/10 | Section 11 is the most underspecified section in the plan |

### Design Critical Gaps (all auto-added to implementation scope)
1. **Edit & Approve workflow state machine** (Critical) — at least 4 states unspecified. Must define: edit-then-approve, edit-then-close, auto-save, lost-edit recovery.
2. **Interaction states** (Critical for loading/error) — add UI states table: empty queue, job-in-progress, approval-error, post-approval, partial-candidate, empty-query.
3. **Sticky action bar** (High) — action buttons must be always-visible, not at bottom of long pages.
4. **Queue position indicator** (High) — "3 of 12 pending" is required for batch review.
5. **Keyboard shortcuts** (High) — `A`=approve, `R`=reject, `E`=edit minimum.
6. **ASCII wireframe for review screen** (High) — implementer needs this.
7. **Regenerate behavior** (High) — specify: new candidate created + old archived, UI shows job-in-progress, then auto-advances.
8. **Status badge color convention** (Medium) — TASTE DECISION #1 (see gate).

### TASTE DECISION #1: Status Badge Colors
Status badge color scheme for Approved/Candidate/Rejected/Archived/Superseded.
Options: (A) Semantic — green/yellow/red/gray/gray | (B) Neutral — all gray with text labels only
Surfacing at final gate.

## DX Phase Findings

### DX Scorecard
| Dimension | Pre-Review | Target | Fix |
|-----------|-----------|--------|-----|
| Getting started (TTHW) | 2/10 (45-90 min) | 8/10 (<15 min) | init-domain.sh script + quickstart |
| Config ergonomics | 3/10 | 8/10 | Canonical domain.yaml example in CLAUDE.md |
| Error handling | 3/10 | 7/10 | failed/partial frontmatter examples |
| Documentation navigation | 5/10 | 8/10 | Common-tasks section |
| Extension points | 4/10 | 7/10 | custom_types + extra_frontmatter_fields |
| Spec consistency | 3/10 | 9/10 | Consolidate domain.yaml (CLAUDE.md vs plan1.md conflict) |
| **Overall** | **3/10** | **8/10** | All fixable before first commit |

### DX Critical Gaps
1. **No getting-started path** (Critical) — TTHW 45+ min. No init script, no quickstart. Fix: `scripts/init-domain.sh <name>` + "Getting Started in 5 steps" at top of CLAUDE.md.
2. **domain.yaml schema conflict** (High) — CLAUDE.md shows only `web_research` stanza; plan1.md section 12.1 shows different fields. Neither is authoritative. Fix: define one canonical full `domain.yaml` in CLAUDE.md.
3. **app.yaml + agents.yaml undefined** (High) — Referenced in file layout, never specified. Fix: add complete examples with all fields.
4. **No error surface for malformed agent output** (High) — What does a `status: partial` candidate look like? What does `jobs/failed/job_*.yaml` with `error:` field look like? Fix: add one example of each.
5. **`source_paths` undefined** (Medium) — `split` operation references this field but it's not in the frontmatter spec.

### DX Developer Journey
| Stage | Current | Gap |
|-------|---------|-----|
| 0. Discover | README (empty) | No value prop on first screen |
| 1. Clone + setup | No instructions | init-domain.sh needed |
| 2. First ingest | Must hand-craft raw/ folder | init script should scaffold |
| 3. First digest | "Tell Claude to digest" — how? | Quickstart must show exact prompt |
| 4. First review | Web UI undefined | Port? Auto-start? |
| 5. First approval | Works once you figure out the UI | |
| 6. First query | Works | |
| 7. Add second domain | Not documented | Common-tasks needed |
| 8. Run lint | Not documented | Common-tasks needed |
| 9. Troubleshoot | No error messages | |

### What Already Exists
- CLAUDE.md — extremely detailed agent operating manual, doubles as schema for edge-ai domain seed
- plan1.md — comprehensive spec covering all MVP features
- Git repo initialized and ready

### Taste Decision Resolutions
- **Taste 1 (Badge colors):** Semantic colors — Approved=green, Candidate=yellow, Rejected=red, Archived/Superseded=gray
- **Taste 2 (merge in MVP):** Keep merge in MVP as fully manual (user preference — no tooling required)

---

## GSTACK REVIEW REPORT

| Review | Via | Status | Runs | Critical Gaps | Unresolved |
|--------|-----|--------|------|--------------|------------|
| CEO Review | /autoplan | issues_open | 1 | 2 | 3 |
| Design Review | /autoplan | issues_open | 1 | 0 | 3 |
| Eng Review | /autoplan | issues_open | 1 | 3 | 5 |
| DX Review | /autoplan | issues_open | 1 | 1 | 4 |
| Voices (CEO) | subagent-only | issues_open | 1 | — | confirmed: 2/6 |
| Voices (Design) | subagent-only | issues_open | 1 | — | confirmed: 0/7 |
| Voices (Eng) | subagent-only | issues_open | 1 | — | confirmed: 2/6 |
| Voices (DX) | subagent-only | issues_open | 1 | — | confirmed: 1/6 |

**VERDICT:** APPROVED with 23 auto-decisions. 6 critical gaps identified across eng/DX (all actionable pre-code). Run `/ship` when ready to implement.

### Top 5 Pre-Implementation Actions (before writing code)
1. Consolidate `domain.yaml` to one canonical full example in CLAUDE.md — removes the CLAUDE.md vs plan1.md conflict
2. Add `config/app.yaml` and `config/agents.yaml` examples — currently referenced but undefined
3. Add `scripts/init-domain.sh <name>` script — TTHW blocker
4. Add "Getting Started" quickstart at top of CLAUDE.md — 5-step flow: clone → init domain → ingest source → digest → review
5. Add ASCII wireframe for Section 11 (review UI) + UI states table — design implementation will diverge without it

### Top 3 Implementation-Time Guards (must not ship without)
1. **Frontmatter schema validator** — validates agent output before writing to `pending/`
2. **Path traversal validation** — `target_path` must be within `domains/<domain>/`
3. **Atomic write (tmp→rename)** for `index.md` and `log.md`


