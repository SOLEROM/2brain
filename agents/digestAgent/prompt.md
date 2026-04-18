# digestAgent

This agent does not use this prompt file directly. The digest prompt is built
per raw source from the target domain's `schema.md` by `src/digest.py`.

To change how this agent writes candidates, edit:

- `domains/<domain>/schema.md` — controls content/shape rules for the domain.
- `config/agents.yaml → digest_agent` — controls model + token budgets.
- `config.yaml` (this folder) — controls routing (domain, scope, per-run cap).
