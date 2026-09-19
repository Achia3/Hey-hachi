# Academic Studio design notes

## Overview

This document records the Academic Studio surface implemented in `templates/academic.html`, `static/academic.css`, and `static/academic.js`. Its scope is this local extension of Hachi's existing cream, ink, and gold interface. It does not establish a new application-wide design system.

A course form sits beside a saved academic document. Each generation has its own history entry, status, and exportable outputs. PO numbers are the primary input; official descriptions can be added through an optional disclosure.

## Colors

The CSS custom properties are the source of truth. Light and dark modes use the same semantic roles:

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--bg` | `#f8f6f0` | `#12110e` | Workspace canvas |
| `--side` | `#fcfbf8` | `#171612` | Header and form sidebar |
| `--paper` | `#fff` | `#1e1d18` | Fields, document symbol, JSON |
| `--ink` | `#1c1a15` | `#eae6dc` | Primary text |
| `--muted` | `#656054` | `#b6af9f` | Help and metadata |
| `--line` | `#ddd7c9` | `#494538` | Borders and ruled rows |
| `--accent` | `#806014` | `#e0b655` | Links, identifiers, active progress |
| `--accent-bg` | `#efe3c6` | `#342b18` | Selected history and quiet-button hover |
| `--button` | `#29271f` | `#eae6dc` | Primary button fill |
| `--button-ink` | `#fff` | `#1c1a15` | Primary button text |
| `--error` | `#922b27` | `#ffaaa2` | Failed or interrupted states |
| `--focus` | `#936b19` | `#e0b655` | Keyboard focus outline |
| `--success` | `#326342` | `#a3cfad` | Completed status and stages |

## Typography

Locally served WOFF2 fonts use `font-display: swap`. Inter with a sans-serif fallback carries body copy and controls at `14px/1.55`. Fraunces with a serif fallback carries the brand (`27px`, weight 500), empty-state title (`clamp(30px,4vw,48px)/1.15`), and document title (`clamp(28px,3vw,40px)/1.17`). IBM Plex Mono with a monospace fallback carries course codes, run references, week numbers, and JSON, generally at 11–12px.

Course metadata follows the document title. Helpers and outcome metadata use 12px muted text; the description is limited to 72ch. Long titles and generated content wrap instead of forcing the document wider.

## Layout

The desktop grid is `345px minmax(0,1fr)`. The sidebar uses `28px 25px 40px` padding; the document area uses `30px 42px 60px`. Horizontal rules organize outcomes, weekly disclosures, and grading. The empty state is centered within a 620px maximum width.

At widths up to 1050px, the sidebar becomes 310px and the document padding becomes 25px. At widths up to 740px, the form and document stack, header actions wrap, document padding becomes `25px 20px`, and saved history scrolls within a 260px maximum height. Form fields become 16px; primary buttons, quiet buttons, and disclosure summaries have 44px minimum heights. Weekly detail indentation disappears and its label column narrows to 85px.

## Elevation & Depth

The surface has no box shadows. Background tones and one-pixel rules separate regions. The empty-state document symbol is a flat bordered HTML element; no raster assets are shipped by this surface.

## Shapes

Inputs and action buttons have 7px corners. History rows have 3px corners. Document content uses open rows and dividers. Weekly disclosure chevrons are 7px CSS border shapes that rotate when open.

## Components

- **Course form:** Required course metadata and comma-separated PO numbers lead to the full-width Generate syllabus action. Optional PO descriptions use one `number: description` entry per line. Grading and generation settings remain in a separate disclosure. Submission errors appear in an alert region.
- **Buttons and fields:** Controls use one-pixel borders. Quiet buttons gain the accent background on hover; primary buttons brighten. Disabled buttons use 0.5 opacity and a waiting cursor. Keyboard focus uses a 2px outline with a 3px offset. Short 0.15s transitions are removed when reduced motion is requested.
- **Saved generations:** Each button shows a title, timestamp, textual status, course code, and shortened run ID. The selected entry uses `aria-current` and an accent background. “Use inputs” copies inputs into the form; submitting creates a separate saved run.
- **Progress and recovery:** Queued and running states expose cancellation. Failed and interrupted states expose an error message. Completed status reads “Saved · review ready.” Live status regions announce changes. Validated outcomes can be exported before a full syllabus exists; an inactive partial run offers “Continue saved outcomes,” which creates a separate run. A successful history refresh clears its previous connection error while preserving unrelated announcements.
- **Document results:** Preview and JSON tabs appear after outcomes exist. Outcomes pair a mono CO number with description, Bloom level, and PO references. Weekly native `details` elements reveal activity, assessment, evidence, and learning outcomes. Weeks 7 and 14 accent their week numbers. The grading area combines a formula with an assessment table. Its CO and Weeks columns reserve 56px and 68px; CO identifiers and the Weeks heading stay unbroken while week lists and assessment prose wrap.
- **Review scope:** With outcomes alone, the note says “Course outcome checks passed.” After a syllabus is present, it says “Syllabus structural checks passed.” Both states require review of topic depth, assessment quality, and PO alignment, and explain that PO numbers alone do not establish alignment with official descriptions.
- **Content handling:** Generated strings are inserted using `textContent`, text nodes, and constructed DOM elements. JSON is displayed as literal text in a wrapping `pre`. Model output is never treated as HTML.
- **Theme and print:** Theme preference and the selected run are remembered in local storage when available. Print styles hide controls, progress, tabs, and JSON, and expose weekly details on a white page.

## Do's and Don'ts

- Do retain Hachi's existing palette, font roles, flat surfaces, and ruled document hierarchy when extending this page.
- Do keep generation identity, partial outputs, and recovery actions visible through their relevant states.
- Do keep generated text literal and allow long content to wrap.
- Don't describe structural validation as approval of academic quality or official PO alignment.
- Don't introduce a replacement visual identity or raster artwork to explain this existing document workflow.
