#!/usr/bin/env bash
# Usage: bash scripts/init-domain.sh <domain-name>
set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
    echo "Usage: $0 <domain-name>" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN_DIR="$ROOT/domains/$DOMAIN"

if [[ -d "$DOMAIN_DIR" ]]; then
    echo "Domain '$DOMAIN' already exists at $DOMAIN_DIR" >&2
    exit 1
fi

echo "Creating domain: $DOMAIN"

mkdir -p \
    "$DOMAIN_DIR/topics" \
    "$DOMAIN_DIR/concepts" \
    "$DOMAIN_DIR/entities" \
    "$DOMAIN_DIR/sources" \
    "$DOMAIN_DIR/reports/deep-research" \
    "$DOMAIN_DIR/reports/comparisons" \
    "$DOMAIN_DIR/reports/contradictions" \
    "$DOMAIN_DIR/questions" \
    "$DOMAIN_DIR/indexes" \
    "$DOMAIN_DIR/.archive" \
    "$ROOT/candidates/$DOMAIN/pending" \
    "$ROOT/candidates/$DOMAIN/rejected" \
    "$ROOT/candidates/$DOMAIN/archived" \
    "$ROOT/inbox/raw" \
    "$ROOT/inbox/suggested_sources" \
    "$ROOT/jobs/queued" \
    "$ROOT/jobs/running" \
    "$ROOT/jobs/completed" \
    "$ROOT/jobs/failed" \
    "$ROOT/audit"

cat > "$DOMAIN_DIR/domain.yaml" << EOF
name: $DOMAIN
display_name: "$(echo "$DOMAIN" | tr '-' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)}1')"
description: ""

default_query_scope: approved+candidates
confidence_visible: true
approval_unit: page
contradiction_style: inline
source_discovery: true
deep_research_enabled: true
max_candidate_age_days: 90
auto_digest: false

web_research:
  enabled: false
  max_sources_per_job: 20
EOF

cat > "$DOMAIN_DIR/index.md" << EOF
# $DOMAIN Index

> Auto-maintained by agent. Do not edit manually.

## Topics
## Concepts
## Entities
## Sources
## Reports
## Questions
EOF

cat > "$DOMAIN_DIR/log.md" << EOF
# $DOMAIN Log

> Append-only. Never delete entries.

EOF

cat > "$DOMAIN_DIR/schema.md" << EOF
# $DOMAIN Domain Schema

> Edit this file to tell agents how to write pages for this domain.

## Preferred page types
- topic
- concept
- entity
- source-summary
- comparison
- research-report

## Link conventions
- Link entities to related concepts.
- Link benchmarks/comparisons to hardware and model pages.

## Required details
Describe any required sections or fields for pages in this domain.
EOF

touch "$DOMAIN_DIR/indexes/contradictions.md" \
      "$DOMAIN_DIR/indexes/low-confidence.md" \
      "$DOMAIN_DIR/indexes/stale-pages.md" \
      "$DOMAIN_DIR/indexes/orphans.md" \
      "$DOMAIN_DIR/indexes/suggested-sources.md"

touch "$ROOT/audit/approvals.log" \
      "$ROOT/audit/ingest.log" \
      "$ROOT/audit/agent-actions.log"

echo "Done. Domain '$DOMAIN' created at $DOMAIN_DIR"
