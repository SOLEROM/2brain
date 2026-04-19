# wikiGraph prompt

The MVP wikiGraph agent is deterministic and does not call an LLM, so this
file is not consumed. It is kept for parity with other agents and reserved
for a future `llm_enrichment` mode that would ask an LLM to propose semantic
connections missing from the explicit wikilink / related_pages graph.

When that mode lands, this prompt will take `{domain}`, `{now}`, and a list
of page titles + summaries, and return a JSON list of suggested edges for
human review in `indexes/connection-suggestions.md`.
