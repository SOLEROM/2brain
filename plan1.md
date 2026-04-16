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

