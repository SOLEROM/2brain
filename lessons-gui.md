# lessons-gui.md

> Best-practice lessons distilled from building the 2brain web UI.
> Intended as the seed of a skill / rules file for future projects.

This is what **consistently worked for me** in a file-backed Python/FastAPI
app with Jinja2 templates. Tune to taste, but do not skip the "why" on each
rule — the reasoning is what makes a rule portable.

---

## 1. Layout & navigation

### 1.1 One `base.html`, many small templates

Keep **a single layout template** that every page extends. The layout owns:
- `<head>` (title, favicon, style links)
- Header + nav
- Domain/session picker
- Theme toggle
- Main content slot (`{% block content %}`)
- Footer (if any)

Pages stay small because they only render the interesting middle. Makes
redesigns (e.g. nav reorder, adding a tab) one-file changes.

### 1.2 Nav order reflects daily flow, not feature history

Put tabs in the order a user *actually* traverses them:

```
Wiki → Ingest → Digest → Review → Query → Health → Jobs → Sources → Config → About
                                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                                        Admin/diagnostic — always last
```

**Wiki/browse is first** because the most common intent is "I want to look
something up," not "I want to add something." Put readers before writers.

### 1.3 Active-tab highlight via a per-template flag

```jinja
{% extends "base.html" %}
{% set nav_active = 'wiki' %}
```

Then in `base.html`:

```jinja
<a href="/wiki/{{ d }}" class="{% if nav == 'wiki' %}active{% endif %}">Wiki</a>
```

Dumb, reliable, zero JS. Don't try to infer from URL — explicit is clearer.

### 1.4 Landing page = most-used tab, not a splash

`/` should 302 to the tab the user will open 90% of the time. For a wiki
that's `/wiki/<default_domain>`, not a branded landing page.

---

## 2. Theme system

### 2.1 CSS variables, one scope per theme

```css
:root, [data-theme="light"] { --c-bg: #f6f7fb; --c-text: #1a1f2e; ... }
[data-theme="dark"]         { --c-bg: #0f1218; --c-text: #e4e7ef; ... }
[data-theme="hackers-green"]{ --c-bg: #000;    --c-text: #00ff41; --font-body: var(--font-mono); ... }
```

**Every colour in the app goes through a variable.** No hardcoded hex in
component styles. If you can't theme a piece, it's not themable — fix the
variable, not the component.

### 2.2 Apply theme *before* first paint

The single most important theming rule: set `data-theme` in a tiny inline
script in `<head>`, **before** `<link rel="stylesheet">`. If you wait for
DOMContentLoaded the user sees a flash of the wrong colours.

```html
<script>
  (function() {
    try {
      var t = localStorage.getItem('app-theme') || window.__DEFAULT_THEME__;
      document.documentElement.setAttribute('data-theme', t);
    } catch (e) {}
  })();
</script>
<link rel="stylesheet" href="/static/style.css">
```

### 2.3 Server supplies the default; client can override

- `config/app.yaml` has `ui.default_theme`.
- Server injects that value into every template via a Jinja global.
- Client reads it from `window.__DEFAULT_THEME__`, but `localStorage`
  wins when present.

This way new users get the admin-chosen theme; power users get their
persistent preference; and changing the server default shifts every new
browser without stomping on existing ones.

### 2.4 Theme list is config-driven

Themes live in `ui.themes: [light, dark, hackers-green]`. The toggle button
cycles through that list. Adding a fourth theme is a YAML edit + a
`[data-theme="..."]` block in CSS — zero Python changes.

### 2.5 Cycling toggle > dropdown

For 2-3 themes, one button that cycles `light → dark → hackers-green → light`
is faster than a dropdown. Beyond 4 themes, switch to a menu.

---

## 3. Session state & per-page scoping

### 3.1 One session-wide selector, not N per-page selectors

**Anti-pattern:** Each page with a "target domain" dropdown. The user
selects once and expects it to stick; re-selecting on every tab is friction
and a source of mistakes.

**Pattern:** Put the selector in the top bar. Every page reads from that
selection via cookie/middleware. Per-page forms show the active domain
**readonly** ("Target domain: `edge-ai` — change in the top bar").

### 3.2 Middleware + `request.state` = free context

```python
@app.middleware("http")
async def inject_session(request: Request, call_next):
    request.state.current_domain = current_domain(request, repo_root)
    request.state.all_domains = list_domains(repo_root)
    return await call_next(request)
```

No route handler has to remember to pass domain context. Templates read
`request.state.current_domain` directly.

### 3.3 URL paths for scoped resources; cookie for session knobs

- `/wiki/<domain>/page/<rel_path>` — domain is part of the *thing*.
- `/digest`, `/ingest`, `/jobs`, `/config` — no per-page domain in the URL;
  those read the cookie.

When the top-bar picker changes: write cookie + either rewrite the path (for
path-scoped routes) or just reload the current page.

### 3.4 Persist choices in localStorage for per-view UI state

Theme, display mode (list/cards/compact), expanded sections — browser-local,
per-user. Cookies are for the server; localStorage is for the UI. Don't
over-engineer with server-side user prefs unless you have real multi-user.

---

## 4. Forms, actions, destructive operations

### 4.1 Every destructive button confirms

Rule: any action that deletes, overwrites, or moves user data must have a
confirmation. One line of JS is plenty:

```html
<form onsubmit="return confirm('Delete {{ item.name }} permanently?');">
```

The wording matters — "Delete X permanently. This cannot be undone." is
better than "Are you sure?"

### 4.2 Audit everything that mutates

Every mutation writes a line to `audit/<category>.log` with:
- ISO timestamp
- operation verb
- domain / target path
- who did it (when known)
- any extra identifier (candidate_id, raw_id, etc.)

Cheap to add, priceless when you wonder "why is this file gone" six months
later. Use `append_line` with parent-dir-auto-create.

### 4.3 Atomic writes for anything another process might read

```python
def atomic_write(path, content):
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    tmp.write_text(content)
    os.replace(tmp, path)
```

Especially important for index files, log files, job YAMLs — anything the
lint or UI might read while you're writing. Never write half a file.

### 4.4 Path-traversal guards at the route boundary

Any route that takes a user-supplied path fragment must:

1. Validate with a regex / allowlist (`_safe_name("/" in name or ".." in name`).
2. Resolve to an absolute path and assert it's inside the expected base:

```python
target = (repo_root / rel_path).resolve()
base = (repo_root / "domains" / domain).resolve()
target.relative_to(base)  # raises ValueError if escaped
```

Do this **even when the field is a hidden input** — hidden inputs are
user-controlled.

### 4.5 Nested forms: use `form="id"` attribute association

HTML disallows `<form>` inside `<form>`. When a page has both a bulk-action
form and per-row inline-action forms, use the HTML5 `form="..."` attribute:

```html
<form id="bulk-form" method="post" action="/jobs/bulk-delete"></form>
<table>
  <tr>
    <td>
      <input type="checkbox" form="bulk-form" name="item" value="{{ id }}">
    </td>
    <td>...</td>
    <td>
      <form method="post" action="/jobs/{{ id }}/delete" class="inline-form">
        <button>Delete</button>
      </form>
    </td>
  </tr>
</table>
```

Checkboxes associate with the bulk form by id; the per-row form is a
sibling. Clean, standards-compliant.

### 4.6 Bulk-action toolbar: one form, many `formaction` buttons

```html
<button type="submit" form="bulk-form" formaction="/jobs/bulk-delete">
  Delete selected
</button>
<button type="submit" form="bulk-form" formaction="/jobs/delete-all"
        onclick="return confirm('Delete ALL? Cannot be undone.')">
  Delete all
</button>
```

One set of checkboxes, many actions. Prefer this over a dropdown.

### 4.7 Cascade hooks are opt-in, default-on, visible

Example: "Drop raw source(s) on approve" — a checkbox next to the Approve
button. Default **checked** because it's what the user usually wants, but
**visible and disable-able** because sometimes they don't.

Quick-approve paths (e.g. list view) pass the cascade as a hidden input
with the same default, so bulk workflows match single workflows.

---

## 5. Live progress & long-running jobs

### 5.1 Server-Sent Events for server-driven progress

For anything that runs on the server and produces a stream of updates
(digest jobs, research agents, long queries), use **SSE**, not WebSockets,
not polling.

- Browser: `const src = new EventSource(url); src.onmessage = ...;`
- Server: `async def event_stream(): yield f"data: {json.dumps(evt)}\n\n"`
- Add `event: end\ndata: {}\n\n` as the terminator.

Reasons SSE wins for this use case: unidirectional, auto-reconnects,
trivially pluggable into nginx, no handshake dance.

### 5.2 Keepalives matter

If your LLM call takes 20 seconds without sending anything, proxies can
drop the connection. Every ~15 seconds, yield a comment line:

```python
yield ": keepalive\n\n"
```

Clients ignore comment lines; proxies see traffic.

### 5.3 Stream + persist in parallel

Every event emitted over SSE should also be **appended to disk** as
`jobs/<state>/<job_id>.events.jsonl`. Reasons:

- User might navigate away mid-job and come back.
- Another user might want to watch.
- After the job ends, the full log is still browseable.

The stream is for live viewers; the file is the record.

### 5.4 Running-state URL redirects when the job transitions

A live log page at `/jobs/running/<file>` will 404 the moment the job moves
to `completed/`. Handle that by making the detail route check all buckets:

```python
if not path.exists():
    for alt in STATE_DIRS:
        alt_path = repo_root / "jobs" / alt / filename
        if alt_path.exists():
            return RedirectResponse(f"/jobs/{alt}/{filename}", 303)
    raise 404
```

Now `<meta http-equiv="refresh" content="3">` on the detail page gives
free auto-follow from running → completed/failed.

### 5.5 Progress log UI: color-coded border, monospace, scrollable

```css
.log-info  { border-left: 3px solid var(--c-info);     }
.log-warn  { border-left: 3px solid var(--c-warning); background: var(--c-warning-bg); }
.log-error { border-left: 3px solid var(--c-danger);  background: var(--c-danger-bg); color: var(--c-danger); }
.log-done  { border-left: 3px solid var(--c-success); background: var(--c-success-bg); font-weight: 600; }
```

Left-border is subtle but scannable. `white-space: pre-wrap; word-break:
break-word` so long error strings don't blow out the layout.

### 5.6 Pre-flight visibility: show in-progress jobs on the action page

If a user is on `/digest` while another digest is running, show it at the
top: "⚙️ 1 digest job running · View live log →". The user can always
attach to an existing run; they don't have to remember the URL.

---

## 6. Lists, cards, and switchable views

### 6.1 Render once, swap layouts via CSS data-attribute

Don't duplicate HTML for different view modes. Render each item once with
all its data, then rewrite the layout via CSS:

```html
<div id="root" data-view="list">
  <article class="item">
    <div class="thumb">...</div>
    <div class="body">title, badges, tags</div>
    <div class="actions">Open →</div>
  </article>
</div>
```

```css
[data-view="list"]  .item  { display: grid; grid-template-columns: 1fr auto auto; }
[data-view="list"]  .thumb { display: none; }
[data-view="cards"] .item  { display: flex; flex-direction: column; border-radius: 8px; }
[data-view="compact"] .item { display: grid; grid-template-columns: 18px 1fr auto; font-size: 13px; }
[data-view="compact"] .item .meta { display: none; }
[data-view="compact"] .item.expanded .meta { display: flex; }
```

JS is tiny: button click → set attribute → persist in localStorage. No
re-render, no framework.

### 6.2 Sensible defaults: List for scanning, Cards for browsing, Compact for density

- **List** = fastest to parse row-by-row, good for tables with columns.
- **Cards** = visual, good for "which one catches my eye."
- **Compact** = maximum density; add expand-on-click to reveal metadata.

Three is the sweet spot — fewer feels like an oversight, more becomes clutter.

### 6.3 Thumb placeholders without images

Few apps have real thumbnails. Use a coloured block with the first letter
of the title and a tiny type label:

```html
<div class="thumb">
  <span class="letter">H</span>
  <span class="type">concept</span>
</div>
```

Looks intentional, stays small, theme-able via gradient variables.

---

## 7. Filters (client-side, data-attribute driven)

### 7.1 Put all filter data on the elements themselves

```html
<article class="item"
         data-title="{{ page.title | lower }}"
         data-tags="{{ page.tags | join(' ') | lower }}"
         data-updated="{{ page.updated_at[:10] }}">
```

Then a single JS filter function toggles `style.display` on each element.
No server roundtrip, instant feedback, works offline.

### 7.2 Tag chips with OR semantics

Multi-select tags almost always want **OR** (show items matching *any*
selected tag), not AND. Users click "rust" and "go" to mean "show me
anything in either language," not "show me things that are both."

Make the active state **obvious** (primary background + white text). Make
unselected chips low-contrast so users don't mistake them for filters that
are already on.

### 7.3 Live result count

"Showing 7 of 142 pages." Update on every keystroke. Lets users know the
filter is working even when the result set is empty.

### 7.4 Empty state when filters exclude everything

A zero-result filter isn't an error — it's a message: "No pages match.
Reset filters to see all." Never leave the user staring at a blank area.

### 7.5 Reset button is mandatory

As soon as you have ≥2 filter controls, ship a Reset button. Clearing four
inputs by hand is friction.

---

## 8. Badges, colours, and status signalling

### 8.1 Status badges are the whole vocabulary of list views

Approve / reject / candidate / archived / running / failed — every one gets
a distinct colour. Users learn the colour before they learn the word.

Keep the palette consistent across the app. A "failed" badge on Jobs should
look like a "failed" badge on Sources.

### 8.2 Pastel background + strong text

```css
.badge-approved { background: #e4f5eb; color: #0f7a3a; }
.badge-failed   { background: #fde4ea; color: #b0123a; }
```

Avoids the "traffic light overload" of saturated colour everywhere. Reserve
saturated colour for the *one* thing you want the user to click.

### 8.3 Per-theme badge overrides

In dark/high-contrast themes, the pastel-over-strong model breaks. Write
explicit overrides:

```css
[data-theme="hackers-green"] .badge-approved {
  background: var(--c-primary-bg);
  color: var(--c-primary);
  border: 1px solid var(--c-border);
}
```

Treat badges as a theme-level concern, not component-level.

### 8.4 Confidence as badge + number

`[ High · 0.78 ]` — a qualitative label *and* the raw number. Users can
scan labels when reading quickly and check numbers when making decisions.

---

## 9. Readonly state indicators

### 9.1 Avoid re-asking what's already known

If the user picked a domain in the top bar, don't make them pick it again
on the Digest form. Show the active value as a readonly pill:

```html
<div class="readonly-domain">
  <code>edge-ai</code>
  <span class="form-hint">Change via the Domain picker in the top bar.</span>
</div>
```

Style it distinctly from an input (dashed border, muted background) so
users don't confuse it with an editable field.

### 9.2 Hint where to go if they want to change it

Every readonly-looking value should either be click-through to its source
of truth, or tell the user where that source is. "Configured in
[Config](./config)." "Change via the top bar."

---

## 10. Error handling & boundary coercion

### 10.1 Normalise at the read boundary, not in every consumer

YAML auto-parses unquoted `2026-04-17T...` into `datetime` objects. A
template then does `fm.created_at[:10]` → `TypeError`. The fix isn't to
patch every template; it's to coerce once when parsing:

```python
def coerce_datetimes(obj):
    if isinstance(obj, (datetime, date)): return obj.isoformat()
    if isinstance(obj, dict): return {k: coerce_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, list): return [coerce_datetimes(x) for x in obj]
    return obj
```

Rule: **every read of external/user data must produce canonical types.**
Write boundary also normalises (quoted ISO strings) but don't rely on it —
frontmatter written by agents is user data too.

### 10.2 Validate at the ingest boundary with a clear result type

```python
class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []
```

Return a `ValidationResult` instead of raising. The UI renders errors
inline; the job record stores them in the YAML; the user sees exactly what
went wrong. Never throw through a template render.

### 10.3 Never let logging break the primary action

File-write failures inside an audit log must be caught silently. If the
audit log is full, the approval should still succeed — audit is
complementary, not blocking.

```python
try:
    with path.open("a") as f: f.write(line)
except Exception:
    pass
```

### 10.4 Stream crashes produce a last event, not a dead socket

In SSE handlers, wrap the work:

```python
try:
    run_the_work(on_event=push)
except Exception as exc:
    push({"level": "error", "step": "crash", "message": str(exc),
          "traceback": traceback.format_exc()})
finally:
    q.put(SENTINEL)
```

Client renders the crash event like any other, sees the stream end
gracefully, and knows to stop the spinner.

---

## 11. Keep templates thin, server smart

### 11.1 Shared template globals via `env.globals`

Don't make every route pass the same 5 context vars. Register them once:

```python
templates.env.globals["ui_defaults"] = _ui_defaults_factory(repo_root)
```

Templates call `{% set ui = ui_defaults() %}` and use the result. Routes
stay focused on page-specific data.

### 11.2 Middleware for per-request shared state

See §3.2 — `request.state.current_domain` set in middleware means no route
has to pass it.

### 11.3 No business logic in templates

Templates should format data; they shouldn't compute. If a template line
has more than one `|filter` + a Python method, extract to a Jinja global
or add the field to the route's context.

### 11.4 Tiny helpers per concern

Prefer `src/web/routes/shared.py` with `current_domain()`, `list_domains()`,
`get_source_types()`, `get_suggested_tags()` over a giant `utils.py`.
Importing a named function is self-documenting.

---

## 12. Config-first defaults

### 12.1 Every knob goes in `config/app.yaml`

Hardcoded magic numbers in Python = user has to know to read your code.
Same numbers in `app.yaml` with comments = user reads the file that
`/config` edits anyway.

Good candidates:
- Display limits (source types, max chars, max tokens)
- Timing thresholds (stale days, stuck minutes, keepalive seconds)
- Scoring thresholds (low-confidence cutoff)
- UI preferences (default theme, available themes)
- Tag suggestions

### 12.2 Deep-merge over defaults

Load order: `DEFAULT_APP_CONFIG` (Python dict) ← `config/app.yaml`.
Missing keys inherit from defaults. File may be empty, partial, or
completely absent — the app still runs.

```python
def load_app_config():
    defaults = deepcopy(DEFAULT_APP_CONFIG)
    if not path.exists(): return defaults
    user = yaml.safe_load(path.read_text()) or {}
    return deep_merge(defaults, user)
```

Deep-merge (not shallow) so users can override one nested knob without
having to restate the others in the same block.

### 12.3 Config page round-trips YAML

Form posts → build new dict → serialise → atomic write. Preserve unknown
keys so manual additions survive. Show the current YAML in a `<pre>` block
at the bottom so users can see exactly what's saved.

### 12.4 Server-side revalidation even on a config page

Validate types on save (int for ports, float for thresholds) with
fallbacks. Never trust the form; a submitted `port=abc` should render an
error, not crash the app on next start.

---

## 13. File-based trust hierarchy

### 13.1 Three layers, one-way promotion

```
inbox/raw/       # immutable once written
candidates/      # agent output awaiting review
domains/         # human-approved canonical knowledge
```

Agents write to layer 1 and 2. Humans promote layer 2 → 3. **Never
auto-promote.** The human click is the trust boundary.

### 13.2 Immutability is a policy, enforce it in code

Raw sources: no routes write to `inbox/raw/<id>/` after creation. Only
delete (via explicit user action) modifies the folder.

Candidate → approved: the approval route atomic-writes to `domains/` and
moves the candidate to `candidates/<domain>/archived/`. No in-place
mutation.

### 13.3 Audit trail across all boundaries

Every layer transition writes an audit line. When a user says "why is this
approved page here and not that one," `grep audit/approvals.log` answers.

---

## 14. Small things that compound

- **Keyboard-friendly confirms.** `confirm()` dialogs are ugly but they
  work on every device. Don't replace with a modal you have to maintain
  until you need it.
- **Always show a count.** "Showing 7 of 142." "Delete selected (3)."
  "Review Queue (12 pending)." Counts make the UI feel alive.
- **Readonly copies of file paths.** When the app shows a filesystem path,
  make it a `<code>` so users can triple-click to select.
- **Empty states that point forward.** "No pending candidates — ingest a
  source → digest it → come back here." Better than "No items."
- **Badge on the tile that matters.** "In progress" / "failed" / "new" —
  these earn their space. A badge on every tile is noise.
- **Progressive disclosure.** Primary action is a button. Secondary actions
  live under `<details>`. Admin actions live on the detail page, not the
  list. The list only shows what's needed for triage.
- **Favour server-rendered first, JS second.** A page that works without
  JS and gets *enhanced* by JS degrades gracefully. A page that doesn't
  render without JS is fragile.

---

## 15. When to break these rules

- **Prototype phase:** inline styles, hardcoded values, and a single HTML
  file are fine. Rules are for when the app is worth maintaining.
- **Single-user local tools:** skip the audit log if you don't need the
  paper trail. Keep the write path atomic anyway.
- **Deliberate visual identity:** if the product is a brand-forward tool
  (landing page, portfolio), the "use pastels" advice flips. Know why
  you're breaking the rule.
- **Performance-critical views:** 10k rows need virtualisation; the
  "render all, filter client-side" rule breaks ~2-5k items. Measure before
  optimising.

---

## Glossary

- **Session domain** — the currently-selected knowledge domain, persisted
  via cookie, available on every request via middleware.
- **Candidate** — a proposed-but-unapproved wiki page. Lives in
  `candidates/<domain>/pending/`.
- **SSE** — Server-Sent Events. One-way HTTP stream, `text/event-stream`,
  `EventSource` in the browser.
- **Running → completed/failed** — job state transition; URL may redirect
  from the old running location.
- **Cascade hook** — a side-effect of a primary action that the user can
  opt out of (e.g. "drop raw source on approve").

---

*Keep this document living. Every time you catch yourself writing a
template filter or a form helper, check whether it belongs here as a
pattern.*
