---
name: obsidian-ui
description: Use when building or editing any UI — components, layouts, styling, dashboards, metrics charts, log viewers, sidebars, command palettes, dark theme, or design tokens. Enforces a dark-first, restrained, Obsidian-like design system for ClaimGuard.
---

# Obsidian UI

Dark-first, restrained, keyboard-first. Restraint is the aesthetic: the interface
disappears and the data is the subject.

## Rules

- **Restraint over decoration.** No gradients, no heavy shadows, no emoji icons.
  Use 1px borders instead of shadows.
- **Density with breathing room.** Compact rows, generous padding around groups.
- **Accent is functional only.** Accent colour is for focus, selection and links.
  Red/amber/green are for status only — never for decoration.
- **Never hardcode colours.** Always use these variables.
- **Spacing** in multiples of 4px.

## Tokens

```css
--bg-0:#161616; --bg-1:#1e1e1e; --bg-2:#262626; --border:#2f2f2f;
--text-0:#dadada; --text-1:#a3a3a3; --text-2:#6b6b6b;
--accent:#7c6cf0; --accent-soft:#7c6cf026;
--ok:#4ade80; --warn:#fbbf24; --err:#f87171;
--radius:6px;
```

These map onto the existing `.ops-dark` scope. **Migrate the `--ops-*` names onto
these values rather than defining a second parallel palette** — one source of
truth per surface. If a token is genuinely missing, extend this list and update
`DESIGN-OPS.md`; do not invent a one-off colour.

## Layout

- Collapsible left sidebar + main area + optional right detail pane.
- Tabs for open views.
- Resizable panes with persisted sizes (`react-resizable-panels`).
- Command palette (`cmdk`, Ctrl/Cmd+K): **every action must be reachable from it**.

## Logs

- Monospace 12–13px, virtualized (`@tanstack/react-virtual`).
- Level shown as a small dot or 2-letter tag — never colour the whole row.
- Live tail with a **visible Pause**, and auto-pause when the user scrolls up.
- Search syntax like `level:error service:api`.
- Collapsible JSON.

## Metrics

- Top row of 3–5 key numbers with tiny sparklines.
- One accent colour per chart.
- **Direct labels instead of legends.**
- Always show the time range selector and the last-updated time.

## Typography

- Inter (or Geist) for UI.
- JetBrains Mono for logs and code.

## Accessibility

- Text contrast at least 4.5:1.
- Visible focus ring using `--accent`.

## Dependencies

Do **not** install packages to satisfy this skill. `cmdk`,
`react-resizable-panels`, `@tanstack/react-virtual` and `motion` are proposed but
**not yet approved** — if a rule needs one, implement the accessible fallback and
ask, or report that the library is required.
