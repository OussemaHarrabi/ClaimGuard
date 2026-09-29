---
name: ux-polish
description: Use for any interactive component, form, button, toast, tooltip, or data view in ClaimGuard — covers feedback, loading/empty/error states, validation, persistence, and mobile behaviour.
---

# UX Polish

## Rules

- **Feedback within 100ms** for every action.
- Buttons have `hover`, `active`, `focus-visible` and `disabled` states.
- Destructive actions: prefer an **undo toast** over a confirmation dialog.
- Forms: inline validation **on blur**, clear error text, **preserve input on failure**.
- Every data view has **loading (skeleton), empty (with a next action) and error (with retry)**.
- Tooltips show keyboard shortcuts.
- Touch targets at least **40px** on mobile; the sidebar becomes a drawer under 768px.
- Persist theme, panel sizes, filters and time range in `localStorage`, wrapped in `try/catch`.
- Toasts bottom-right, auto-dismiss 4s, **max 3 stacked**.
- **Never block the whole screen with a spinner.**

## ClaimGuard specifics

- The three states must be *explicit and distinct*: `stale` is not `unavailable`,
  and neither is `healthy`. This is a safety property, not styling.
- A failed telemetry source degrades one panel — it must never blank the page.
- Copy: plain operational English. No marketing tone, no clinical or adjudicative
  language (the product is "review, not adjudicate").
