---
name: ClaimGuard
description: Evidence-first claim assurance for healthcare administrators
colors:
  navigation-navy: "#082F53"
  action-blue: "#1677FF"
  evidence-aqua: "#19AEB4"
  canvas-ice: "#F3F8FC"
  panel-white: "#FCFEFF"
  ink-navy: "#0B2640"
  muted-slate: "#5D7287"
  line-blue: "#D6E4EE"
  finding-red: "#C9344F"
  caution-amber: "#A86208"
  ready-green: "#137A58"
typography:
  headline:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.2
  title:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.35
rounded:
  control: "8px"
  panel: "12px"
  shell: "18px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.action-blue}"
    textColor: "{colors.panel-white}"
    rounded: "{rounded.control}"
    padding: "12px 18px"
    typography: "{typography.label}"
  button-secondary:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.action-blue}"
    rounded: "{rounded.control}"
    padding: "11px 17px"
    typography: "{typography.label}"
  status-finding:
    backgroundColor: "#FCE8EC"
    textColor: "{colors.finding-red}"
    rounded: "{rounded.pill}"
    padding: "5px 10px"
    typography: "{typography.label}"
  evidence-chip:
    backgroundColor: "#E5F6F7"
    textColor: "#087077"
    rounded: "{rounded.control}"
    padding: "4px 8px"
    typography: "{typography.label}"
---

# Design System: ClaimGuard

## 1. Overview

**Creative North Star: "The Evidence Desk"**

ClaimGuard is a bright, evidence-first operations desk built for administrators who need to move quickly without surrendering control. The approved direction uses a persistent three-column cockpit: queue on the left, deterministic claim findings in the center, and explanation plus correction context on the right. The familiar navy, blue, and aqua atmosphere echoes the confidence and approachability of Velodoc's public product language, while ClaimGuard's density, evidence citations, and audit-first composition establish an original identity.

The physical scene is a billing reviewer working through a morning queue on a wide office monitor under bright ambient light, focused and slightly time-pressured. The interface is therefore light, crisp, and information-dense. Motion is responsive but restrained, with state changes in 100 to 250 milliseconds and no page-load choreography.

The system rejects generic AI dashboards, marketing-style gradients inside operational workflows, dense legacy hospital software, literal imitation of Velodoc, and autonomous-agent theatre.

**Key Characteristics:**

- Three persistent work zones with evidence always one scan away.
- Navy structure, blue action, and aqua evidence cues on tinted white surfaces.
- Compact humanist typography with tabular numbers and explicit labels.
- Flat by default, with depth reserved for the shell, sticky controls, and active overlays.
- Deterministic result first, bounded AI explanation second.

## 2. Colors

The palette uses blue-tinted neutrals to make long review sessions feel calm while reserving strong color for navigation, actions, evidence, and status.

### Primary

- **Navigation Navy**: Carries the app shell and anchors trust without turning the whole product dark.
- **Action Blue**: Marks primary actions, current navigation, links, focus, and selected records.

### Secondary

- **Evidence Aqua**: Identifies citations, provenance, and explanatory connections. It never replaces the primary action color.

### Tertiary

- **Finding Red**, **Caution Amber**, and **Ready Green**: Communicate result state together with an icon and text label, never through color alone.

### Neutral

- **Canvas Ice**: The primary application background.
- **Panel White**: The working surface for queue, findings, and explanation regions.
- **Ink Navy**: Primary text and data.
- **Muted Slate**: Secondary metadata that still meets WCAG AA.
- **Line Blue**: Dividers and control boundaries.

### Named Rules

**The Evidence Color Rule.** Aqua is reserved for evidence, citations, provenance, and the visual path between a finding and its source.

**The Operational Gradient Rule.** Gradients are prohibited behind claim data, findings, tables, inputs, and corrective actions. A subtle identity gradient may appear only inside the compact brand mark or navigation ornament.

## 3. Typography

**Display Font:** Inter (with Segoe UI and system-ui fallback)

**Body Font:** Inter (with Segoe UI and system-ui fallback)

**Label/Mono Font:** Inter for labels; ui-monospace only for immutable identifiers and hashes

**Character:** One humanist sans family keeps the workspace familiar and quiet. Weight, spacing, position, and color create hierarchy instead of decorative type pairing.

### Hierarchy

- **Headline** (700, 1.5rem, 1.2): Claim identity and primary page titles.
- **Title** (650, 1rem, 1.35): Findings, panels, and action groups.
- **Body** (400, 0.9375rem, 1.5): Explanations and supporting content, capped at 70 characters where prose runs long.
- **Label** (600, 0.8125rem, 1.35): Metadata, tabs, chips, and controls.

### Named Rules

**The Data Rhythm Rule.** Claim amounts, dates, counts, and identifiers use tabular numerals so rows remain visually stable.

## 4. Elevation

ClaimGuard is flat by default. Structure comes from layout, tonal surface changes, and one-pixel borders. Shadows appear only when an element is physically above another surface, such as the navigation shell, a sticky action bar, a dropdown, or a temporary notification.

### Shadow Vocabulary

- **Shell** (`0 10px 30px rgba(8, 47, 83, 0.10)`): The navigation shell and wide workspace frame.
- **Raised** (`0 8px 24px rgba(8, 47, 83, 0.12)`): Menus, sticky action regions, and active overlays.
- **Focus** (`0 0 0 3px rgba(25, 174, 180, 0.24)`): Keyboard focus support paired with a solid outline.

### Named Rules

**The Flat-by-Default Rule.** If every panel casts a shadow, the hierarchy has failed. Use borders and spacing first.

## 5. Components

### Buttons

- **Shape:** Confident compact corners (8px) with a minimum 44px interaction target.
- **Primary:** Action Blue with Panel White text and 12px by 18px padding.
- **Hover / Focus:** Darken perceptually on hover; use a 2px aqua focus-visible outline with 2px offset.
- **Secondary / Ghost / Tertiary:** White or transparent surfaces with explicit borders and equally complete keyboard states.

### Chips

- **Style:** Rounded pills for status and softly rounded rectangles for evidence IDs.
- **State:** Every semantic chip includes a readable label and optional icon; color never carries meaning alone.

### Cards / Containers

- **Corner Style:** Working panels use 12px corners; the outer shell uses 18px.
- **Background:** Panel White on Canvas Ice.
- **Shadow Strategy:** Flat at rest. Only the outer shell and active overlays receive elevation.
- **Border:** One-pixel Line Blue boundary.
- **Internal Padding:** 16px compact, 24px standard, and 32px for the explanation reading region on wide screens.

### Inputs / Fields

- **Style:** White fill, Line Blue stroke, 8px corners, persistent labels, and 44px minimum height.
- **Focus:** Action Blue border with aqua outer ring.
- **Error / Disabled:** Errors explain what happened and how to fix it; disabled state preserves readable contrast.

### Navigation

The wide layout uses a rounded navy horizontal shell with an embedded brand mark, primary destinations, and reviewer identity. On tablet it becomes a compact horizontal strip. On narrow screens it reduces to a top bar plus an accessible drawer.

### Claim Queue

The queue is a single interactive list, not a grid of cards. Rows expose claim ID, member-safe display data, date, amount, and status. Selection uses a full-row tint, check indicator, and `aria-current` semantics.

### Finding Stack

Findings are separated by spacing and one-pixel boundaries inside one region. Each finding exposes severity, concise correction guidance, rule ID, and evidence links without nesting another decorative card.

### Explanation Workspace

The right region begins with a clearly labelled **Draft explanation**, followed by evidence citations and suggested corrections. It never resembles an open-ended chat. It always echoes the deterministic status and states that the reviewer remains responsible for the decision.

## 6. Do's and Don'ts

### Do:

- **Do** keep queue, findings, and explanation visible together on wide screens.
- **Do** show deterministic evidence before AI prose and attach every factual model statement to an evidence ID.
- **Do** preserve familiar healthcare-administration interaction patterns while making ClaimGuard's evidence workflow distinct.
- **Do** design loading, empty, failure, long-content, keyboard, touch, and reduced-motion states.
- **Do** keep primary actions specific: `Recheck claim`, `Request correction`, and `Confirm ready`.

### Don't:

- **Don't** build a generic AI dashboard that leads with chat instead of the operator's queue.
- **Don't** use marketing-style gradients, oversized hero metrics, or decorative glass effects inside operational workflows.
- **Don't** reproduce dense legacy hospital software with small targets and unexplained codes.
- **Don't** create a literal Velodoc clone or use another company's private assets, copy, or proprietary identity.
- **Don't** imply that the AI can adjudicate, submit, or alter a deterministic claim outcome.
- **Don't** nest cards, use colored side stripes, use gradient text, or hide critical actions behind hover.

---

## Dark operations surface

The technical-manager observability surface (`/ops` and the seven technical
workspace pages) uses a separate, **dark-first** system documented in
[`DESIGN-OPS.md`](DESIGN-OPS.md). This file remains authoritative for the light
Evidence Desk screens — review, queue, findings, intake and clinic admin.
