---
name: calendar-pdf-meeting-scheduler
description: "Schedule meetings from request emails against a graphical calendar PDF. Parse each email's duration/window/timezone, measure calendar event blocks by vector geometry against the 15-minute gridline axis (not plain text), treat blue-filled blocks as overwritable, solve for the earliest start times that still accommodate ALL requests, then write template-exact reply files and a results.json index, and re-read outputs to verify."
---

# calendar-pdf-meeting-scheduler

## When to use
User supplies a JSON file of meeting-request emails plus a calendar PDF rendered as a day timeline (adjacent horizontal lines = fixed minutes), asks to propose meeting times per constraints (colored blocks, blue = flexible), and to save reply_*.txt files plus results.json with exact date/time formats.

## Do not apply when
- Do not infer appointment times from a plain text dump alone; block start/end must be measured from vector rect positions against the gridline axis.
- Do not assume email availability windows are in the calendar's timezone; convert explicitly stated zones (e.g., PST to the calendar's Eastern Time) before scheduling.
- Do not treat blue blocks as busy, and do not treat red/gray/yellow blocks as overwritable.
- Do not greedily take each request's own earliest slot if that pushes another request out of its window; search for earliest starts such that all requests fit.
- Do not emit unpadded times ('9:00 AM') or ordinal dates ('January 8th'); follow the mandated zero-padded formats.
- Do not invent a messageID; if the input lacks one, fall back to the email's array index and note it.

## Procedure
1. Read the requests JSON first and record per email: duration, date, availability window, and any explicit timezone token in the body (flag windows whose zone differs from the calendar's, e.g. a 'PST' window against an 'Eastern Time' calendar).
2. Probe PDF tooling before parsing (e.g. `python3 -c "import pymupdf"`, `which pdftotext`); both sessions found PyMuPDF available and used it as the parser.
3. Dump the calendar page text (`page.get_text()`) to capture the date/timezone header line and the ordered hour-axis labels used later as calibration anchors.
4. Extract geometry: `page.get_text("dict")` for span bboxes (hour labels, event titles) and `page.get_drawings()` for filled rects with RGB `fill` tuples; keep only large event-sized fills as appointment blocks.
5. Calibrate y->time: gridline spacing corresponds to the stated minutes per line (15), anchor the first line to midnight, and compensate the ~1-unit block inset (top+1/bottom-1). Convert each block rect to start/end times, and classify blue-dominant fills (B channel > R and high) as flexible/overwritable, all other colors as busy. Example: `mins = round((y - y0) / step) * 15`.
6. Render the page to PNG (`page.get_pixmap(...)`) and view it to cross-check that measured intervals and color classifications match the visual calendar before scheduling.
7. Solve jointly: convert every window into the calendar timezone, exclude blue intervals from busy, and search 15-minute-aligned start times for the earliest assignment where ALL requests fit without overlapping busy blocks or each other; backtrack or reorder requests when the greedy order fails (a small recursive solver was used and confirmed the hand-derived schedule).
8. Write one reply_{messageID}.txt per email using the exact template (day-name date `Monday, March 09, 2026`, zero-padded `hh:MM AM/PM - hh:MM AM/PM`, duration in hours) and a results.json listing filename+recipient pairs; then `ls`/`cat` the outputs to confirm they exist and match the required format.

## Verify
- Block table cross-checked two ways: computed y->time conversion agrees with the rendered PNG image of the calendar.
- A programmatic solver (or explicit interval check) confirms no proposed meeting overlaps a non-blue busy block or another proposed meeting, and every meeting lies inside its requester's (timezone-converted) window.
- Re-read reply files and results.json after writing: filenames, recipients, template text, zero-padded date/time formats all present.

## Stop
Stop when every email has a reply file whose slot satisfies its window and duration, all slots are mutually non-conflicting with non-blue calendar blocks, results.json indexes all replies, and the verification reads pass.

## Limits
- Task outcomes were not externally validated; correctness of the chosen slots is asserted only by the agent's own solver/visual check.
- Blue detection relied on an RGB-dominance heuristic tied to this calendar's palette; other calendars may encode flexible blocks differently.
- PST->ET conversion assumed a fixed 3-hour offset without DST validation.
- Gridline calibration assumed uniform spacing and a ~1-unit block inset, verified visually only for this PDF.
- Input emails contained no messageID field; falling back to array indices for reply filenames is an unverified convention.
