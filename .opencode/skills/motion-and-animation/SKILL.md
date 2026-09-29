---
name: motion-and-animation
description: Use when adding transitions, hover or focus effects, mount/unmount animation, list reordering, route transitions, scroll effects, loading skeletons, or animated counters to ClaimGuard UI work.
---

# Motion and Animation

Animation explains change; it never decorates.

## Rules

- No parallax, no bouncing, no looping decorative animation.
- **Durations:** 120–200ms hover/press; 200–300ms panels/modals; **max 500ms** page-level.
- **Easing:** `cubic-bezier(0.16, 1, 0.3, 1)` by default; ease-out entering, ease-in exiting.
- **Animate only `transform` and `opacity`** — never `width`, `height`, `top` or `left`.
- **Tools:** CSS transitions for hover/focus/colour; the `motion` library
  (Framer Motion) for mount/unmount, layout and list reordering; View Transitions
  API or `AnimatePresence` for routes.

## Specific behaviours

- Stagger list items 30–40ms, **capped at 8 items**.
- Command palette: fade + scale from `0.98`.
- Sidebar collapse: layout animation; content fades.
- Cards/rows on hover: border brightens and background lifts to `--bg-2`.
- Loading: soft shimmer skeletons, **not spinners**.
- New live log rows fade in **once** — never re-animate on re-render.
- Metric numbers count up in under 400ms.
- **No animation on virtualized rows while scrolling.**
- Respect `prefers-reduced-motion`: remove movement, keep opacity fades.
- Keep 60fps.

## Dependencies

`motion` is proposed but **not approved**. Until it is, use CSS transitions and
`@media (prefers-reduced-motion: reduce)`; do not install it yourself.
