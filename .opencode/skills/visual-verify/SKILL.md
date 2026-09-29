---
name: visual-verify
description: Use at the END of every UI task in ClaimGuard to check the result visually before reporting done — screenshots, spacing, alignment, contrast, overflow, focus, dark mode.
---

# Visual Verify

Do not report a UI task complete until the rendered result has been looked at.

## Procedure

1. Start the dev server (`cd frontend && npm run dev -- --port 3001`, or use the
   running Docker stack at `http://localhost:3001`).
2. Use Playwright (or another available browser/screenshot tool) to screenshot the
   changed views at **1440px** and **390px** widths.
3. Check: spacing, alignment, contrast, overflow, focus states, and dark-mode correctness.
4. Fix what you find, **re-screenshot**, and only then report done.
5. If no browser tool is available, **say so** and suggest installing Playwright —
   do not claim a visual check you did not perform.

## ClaimGuard specifics

- Screenshot only with **synthetic** data. Never capture real patient or claim data.
- The reference authentication path is the seeded synthetic demo tenant
  (technical manager for the observability pages); never record or screenshot
  credentials.
- Check both the dark observability pages and the light Evidence Desk pages if the
  change touches shared CSS.

## Status in this repo

Playwright is **not installed**. Until it is approved, report the visual check as
*not performed* rather than inferring it, and describe exactly what should be
looked at so the human can verify.
