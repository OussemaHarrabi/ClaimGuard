# ClaimGuard — Operations Design System (dark)

> **Scope:** the **technical-manager observability surface** only (`/ops` and the
> seven technical workspace pages). The rest of the platform uses the light
> *Evidence Desk* system documented in `DESIGN.md`; that file remains authoritative
> for review, queue, findings and intake screens.
>
> **Status:** living document. It is the single source of truth for the dark
> surface — tokens, layout, type, motion, and libraries. Update it whenever a token
> or rule changes, and keep `.opencode/skills/obsidian-ui/SKILL.md` in step.

## 1. Posture

The observability surface exists so a technical manager never has to open Grafana,
Prometheus or Tempo. Two rules outrank every aesthetic choice:

1. **Honest state.** `stale` is not `unavailable`, and neither is `healthy`. A
   source that cannot answer must say so. Status colour never carries meaning
   alone — it is always paired with the literal word and an icon.
2. **No claim content.** This surface shows counts, durations, identifiers and
   system state. Never a claim, a patient identifier, a prompt, or an audit payload.

## 2. Tokens

Dark-first and restrained. **Never hardcode a colour**; use these variables, all
defined under the `.ops-dark` scope.

```css
--bg-0:#161616; --bg-1:#1e1e1e; --bg-2:#262626; --border:#2f2f2f;
--text-0:#dadada; --text-1:#a3a3a3; --text-2:#6b6b6b;
--accent:#7c6cf0; --accent-soft:#7c6cf026;
--ok:#4ade80; --warn:#fbbf24; --err:#f87171;
--radius:6px;
```

| Token | Role |
|---|---|
| `--bg-0` | page canvas |
| `--bg-1` | panel surface |
| `--bg-2` | raised surface, and card/row hover |
| `--border` | 1px boundary — **use borders, not shadows** |
| `--text-0` | primary text |
| `--text-1` | secondary text, labels |
| `--text-2` | muted, timestamps, placeholders |
| `--accent` | **focus, selection and links only** |
| `--accent-soft` | accent wash for selected rows |
| `--ok` `--warn` `--err` | **status only** — never decoration |

**Spacing** is always a multiple of 4px. **Radius** is 6px (4px for chips).

Migration note: the current `--ops-*` names map onto these values. When touching
the stylesheet, rename toward `--bg/--text/--accent` rather than maintaining two
parallel palettes.

## 3. Layout model

- Collapsible left sidebar + main content area + optional right detail pane.
- The sidebar is the platform's shared chrome; the **content area** is what goes
  dark for this role.
- Resizable panes with **persisted sizes** (`react-resizable-panels`).
- Tabs for open views.
- **Command palette** (`cmdk`, `Ctrl/Cmd+K`): every action must be reachable from it.
- Sidebar becomes a drawer below 768px.

Current page set (one section per page, all dark):

| Page | Content |
|---|---|
| Operations | platform verdict, components, source freshness, version strip |
| Metrics | category cards by signal family; drill to series; 5m/15m/1h |
| Traces | category cards by request family; drill to trace timeline |
| Audit Integrity | chain verification seal + event count |
| Intake Jobs | job counts by status |
| Versions | rule / model / prompt versions |
| Configuration | tenant-scoped intake toggle |

## 4. Typography

- **UI:** Inter (or Geist). Already the platform font via `next/font`.
- **Logs, code, identifiers, durations, metric names:** JetBrains Mono.
- Numeric columns use `font-variant-numeric: tabular-nums`.
- Log lines are 12–13px.

## 5. Data presentation

**Metrics:** category cards that group Prometheus series by signal family (HTTP
requests, latency, claim submissions, review decisions, intake jobs, AI
assistant turns, runtime, queue, database, other). Empty categories remain
visible and read "no data" so the manager sees the whole surface honestly.
Clicking a card opens a detail view where each line translates raw labels into
plain language — e.g. `status_class=2xx` becomes "Successful — handled without
error", `route_template=/v1/claims` + `method=POST` becomes "Submitting a claim",
and `outcome=fallback` becomes "Answered by the deterministic layer, not the
model". Each line shows the count, its unit, its share of the category, and an
animated proportion bar. A window switcher (5m/15m/1h) lives in the header.
Counter magnitude may be heat-encoded, but never let the ramp imply an alarm
about a metric that is merely large.

**Logs:** virtualized (TanStack Virtual); level as a small dot or 2-letter tag,
never a coloured row; a visible **Pause**, with auto-pause on scroll-up; search
syntax like `level:error service:api`; collapsible JSON.

**Traces:** category cards that group recent traces by request family (claim
submission, claims, review, intake, auth, ops, other). Each card shows a title,
description, trace count and the slowest duration in the family. Clicking a card
opens a detail timeline where each row explains that it is one request, that the
duration is total time from start to response, and labels each value as either
"total time" or "slowest". The list is sorted by start time and offers a pause
control so live WebSocket updates do not reorder values while they are being
read. Clicking a request opens a span-flow waterfall: the parent span and its
children nested by depth, each bar positioned by start time and sized by
duration, so a reader can see exactly where the time went (e.g. a database call
inside a rule-evaluation span). Empty categories stay visible and read
"no traffic" so the manager can see what parts of the API surface are idle.

## 6. Motion

Full rules live in the `motion-and-animation` skill. The essentials:

- Animation explains change; it never decorates. No parallax, no bouncing, no loops.
- 120–200ms hover/press · 200–300ms panels · **max 500ms** page-level.
- `cubic-bezier(0.16, 1, 0.3, 1)`; ease-out entering, ease-in exiting.
- Animate **only `transform` and `opacity`**.
- Stagger lists 30–40ms, capped at 8 items. No animation on virtualized rows
  while scrolling. New live log rows fade in once, never on re-render.
- Loading uses shimmer skeletons, **not spinners**.
- `prefers-reduced-motion`: drop movement, keep opacity fades.

## 7. Interaction rules

Full rules live in the `ux-polish` skill. The essentials:

- Feedback within 100ms; every button has hover / active / focus-visible / disabled.
- Every data view implements **loading, empty (with a next action), and error
  (with retry)** explicitly. A blocked telemetry source degrades one panel — it
  never blanks the page.
- Prefer an undo toast over a confirmation dialog for destructive actions.
- Persist theme, panel sizes, filters and time range in `localStorage` (try/catch).
- Toasts bottom-right, 4s, max 3 stacked. Never block the whole screen with a spinner.
- Focus-visible ring uses `--accent`; contrast at least 4.5:1.

## 8. Libraries

**Installed already:** Next.js 16 + React 19, Tailwind **v4**, shadcn/ui + Radix,
`class-variance-authority`, `cn`, `tw-animate-css`, `lucide-react`, vitest +
Testing Library.

**Proposed — pending approval, do not install unprompted:**

```powershell
cd frontend
npx shadcn@latest add command resizable      # pulls cmdk + react-resizable-panels
npm install @tanstack/react-virtual motion uplot
npm install -D @playwright/test
npx playwright install chromium
```

- `uplot` for dense metrics; `recharts` is the heavier alternative.
- Fonts need **no install** — `next/font/google` already provides Inter, Geist and
  JetBrains Mono.
- `tailwindcss-animate` is **not** needed: Tailwind v4 uses `tw-animate-css`.

Once approved, wire the tokens into Tailwind v4 through `@theme` in
`frontend/src/app/globals.css`.

## 9. Verification

The `visual-verify` skill governs the end-of-task check: screenshot the changed
views at 1440px and 390px, inspect spacing, alignment, contrast, overflow, focus
and dark-mode correctness, fix, re-screenshot, then report.

Playwright is **not installed yet**. Until it is, a UI task must report the visual
check as *not performed* rather than implying it.

## 10. Reference screenshots

<!-- Fill in with absolute links or repo-relative paths. Leave empty until real,
     synthetic-data screenshots exist — never commit a screenshot containing real
     or unsanitised claim data. -->

| View | 1440px | 390px | Notes |
|---|---|---|---|
| Operations overview | _pending_ | _pending_ | |
| Metrics | _pending_ | _pending_ | |
| Traces | _pending_ | _pending_ | |
| Audit Integrity | _pending_ | _pending_ | |
| Intake Jobs | _pending_ | _pending_ | dark variant of a shared component |
| Versions | _pending_ | _pending_ | dark variant of a shared component |
| Configuration | _pending_ | _pending_ | dark variant of a shared component |
