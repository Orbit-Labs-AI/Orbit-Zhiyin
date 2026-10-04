---
name: pdf-scheduling-and-form-filling
description: "Workflows for two recurring PDF tasks: (1) parsing a visual daily-calendar PDF with PyMuPDF (gridline calibration, color-coded blocks where blue = overwritable), jointly scheduling meeting requests with backtracking and lexicographic earliest-start comparison, and writing formatted reply .txt files plus results.json; (2) filling the California SC-100 small-claims AcroForm from a case description using pypdf/PyMuPDF \u2014 including a three-bucket output contract (stated values vs. mandatory Yes/No decisions that must never be left blank vs. court-filled/unsupported fields such as CourtInfo that must stay empty and must not be inferred), hierarchical field-name mapping, checkbox on-state handling, and two-direction verification (missing required answers AND extra unsupported content both fail)."
---

# PDF Scheduling & Form-Filling Workflows

## 0. First steps (any PDF task)
- `ls -la` the input dir and `file` the PDF to confirm it exists and its type.
- Probe tooling: `which python3 pip3 pdftoppm pdfinfo`; `python3 -c "import pymupdf"`, `import pypdf`. Observed environments have PyMuPDF (use `import pymupdf`; `import fitz` works but warns), pypdf 5.x, pdfrw, and pdftoppm.
- Run all logic via `python3 << 'EOF' ... EOF` heredocs in bash.
- ALWAYS verify final artifacts twice: (a) programmatic read-back of values, and (b) render pages to PNG (`page.get_pixmap(dpi=110)` or `pdftoppm -png -r 110 in.pdf /tmp/out`) and view them with the read tool. Crop/zoom (PIL) when a small region (e.g., a checkbox) is ambiguous.

## 1. Visual calendar PDF -> meeting scheduling

### 1.1 Parse the calendar
- `page.get_text()` for all labels; `page.get_text("dict")` for span bboxes (the hour labels on the axis give you anchor positions); `page.get_drawings()` for vector graphics: gridlines (type `s`, thin gray strokes) and appointment blocks (type `f`, wide rects with `fill` RGB tuples).
- Calibrate y -> time; do NOT hardcode coordinates:
  - Gridlines are evenly spaced (task states the quantum, e.g., 15 min). Find y of the first gridline (midnight) `y0` and spacing `step = (y_last - y_first) / n_intervals`.
  - `minutes = round((y - y0) / step) * quantum_minutes`.
  - Blocks are typically inset ~1pt from their gridlines; expand rect top/bottom by ~1 and round to the quantum.
- Classify blocks by fill color: blue-ish fill (b clearly greater than r, e.g., ~(0.47, 0.53, 0.80)) = flexible/overwritable per the task spec; every other color (red/gray/yellow) = busy. Confirm classification on a rendered PNG.
- Match each block rect to its event label by overlapping y ranges.
- Note the timezone stated in the calendar header; ALL output times use that timezone.

### 1.2 Parse the requests
- From each email extract: duration (normalize: "45-minute" -> 45 min, "1.5 hour" -> 90 min), date, and the availability window.
- If the requester states availability in another timezone (e.g., PST), convert to the calendar timezone (Pacific -> Eastern is +3h) before scheduling.
- If vague wording conflicts with an explicit numeric range (e.g., "prefer morning slots between 3:30pm and 5:30pm"), the explicit range wins.

### 1.3 Solve jointly (not greedy)
- Build busy intervals in minutes-since-midnight, EXCLUDING the blue (overwritable) blocks.
- "Earliest compatible time, provided ALL requests can be accommodated" means a per-email greedy earliest pick can be wrong (it may push another request out of its window). Use backtracking/DFS over candidate start times stepped by the grid quantum: place request i at its earliest feasible start (no overlap with busy intervals or already-placed meetings), recurse; backtrack on failure. Try alternate request orders if needed.
- When several complete assignments exist, compare them request-by-request in input order (lexicographically earliest start vector). Do NOT optimize an aggregate objective such as minimizing the sum of start times — that can trade one request's earliness against another's and pick different slots.

### 1.4 Outputs
- One `/root/reply_{messageID}.txt` per email, using the task's template verbatim. If the input JSON has no messageID field, use the email's array index and note that choice in the final summary.
- Obey formatting rules exactly: date `Day, Month DD, YYYY` with zero-padded day (e.g., `Monday, March 09, 2026`); zero-padded 12-hour times (`09:00 AM - 10:30 AM`, not `9:00`); duration in hours as stated (`1`, `1.5`, `0.75`, `2`).
- Write `/root/results.json`: `{"sent_results": [{"filename": "reply_X.txt", "recipient": "<from_email>"}, ...]}`. The filenames in results.json must exactly match the files on disk, and each recipient must be the from_email of the matching request.
- Read back every written file to confirm content.

## 2. SC-100 (California small claims) AcroForm filling

### 2.0 Output contract — classify EVERY field into a bucket before writing
External validation counterexamples showed two opposite failure modes: (a) leaving mandatory Yes/No questions blank because the description never mentioned them, and (b) writing values that were inferred but never stated (e.g., a court name derived from the parties' city). Both fail. Sort every field into one of three buckets BEFORE filling:

1. **Stated values (fill)**: content explicitly present in, or a direct restatement of, the case description: party names, street/city/state/zip, phones, emails, claim amount, why-owed reason, incident start/end dates, how the amount is documented, venue zip, declaration signing date, typed plaintiff name.
2. **Required Yes/No (or a/b/c) decisions (ALWAYS answer)**: every choice question on the form is mandatory even when the description is silent. Items 4, 5, 7, 8, 9 and 10 each need exactly one box checked. Use the description when it speaks ("first time filing" -> item 9 No; "filed more than 12..." -> Yes; amount > $2,500 -> item 10 Yes, else No); otherwise check the default negative (No). The task's "leave unmentioned fields empty" rule does NOT apply to these — an unanswered Yes/No question is a missing required decision.
3. **Court-filled or unsupported fields (leave EMPTY)**: page-1 court caption — `CourtInfo` (court name/street address), `CaseNumber`, `CaseName` — all `Trial*` fields, and clerk signature/date fields. Also: second plaintiff/defendant sections, "mailing address if different", military duty, fictitious business name, item-8's public-entity date (`Date4`) and its sub-checkbox (`Checkbox14`), attorney-fee/arbitration sub-items, SC-100A/SC-101 attachments, pages 5-6 county-advisor fields, Print/Save/Reset buttons. Do NOT infer the county or court from the parties' city: if the description does not state the court name/address, `CourtInfo` stays empty even though the printed form invites the filer to complete it.

### 2.1 Discover and map fields
- `pypdf.PdfReader(path).get_fields()` returns ~155 fields with hierarchical names like `SC-100[0].Page2[0].List1[0].Item1[0].PlaintiffName1[0]`. Print `/FT`, `/T`, `/TU` (the tooltip explains each field's purpose), `/V`.
- Render pages 1-4 to PNG to map the printed item numbers (1-10) to field names. Use `page.get_text("words")` near widget rects to confirm which checkbox is "Yes" vs "No" or option a/b/c.
- Checkbox on-states: inspect widget `/AP` `/N` keys (pypdf) or `widget.button_states()` (PyMuPDF). Observed convention: `[0]` = first option (e.g., Yes) with state `/1`; `[1]` = second option (e.g., No) with state `/2`.

### 2.2 Standard SC-100 field mapping (consistent across sessions)
- Page captions: `PageN[0].PxCaption[0].Plaintiff[0]` = plaintiff name (repeat on pages 2-4).
- Item 1 plaintiff: `Page2[0].List1[0].Item1[0].{PlaintiffName1,PlaintiffPhone1,PlaintiffAddress1,PlaintiffCity1,PlaintiffState1,PlaintiffZip1,EmailAdd1}[0]`.
- Item 2 defendant: `Page2[0].List2[0].item2[0].{DefendantName1,DefendantPhone1,DefendantAddress1,DefendantCity1,DefendantState1,DefendantZip1}[0]`.
- Item 3 claim: `Page2[0].List3[0].PlaintiffClaimAmount1[0]` (amount — mirror the digit string in the description; do not add or remove thousands separators); `...List3[0].Lia[0].FillField2[0]` (why owed — concise 1-2 sentence restatement of the description).
- 3b when: `Page3[0].List3[0].Lib[0].Date2[0]` (date started), `Date3[0]` (through); 3c calculation: `Page3[0].List3[0].Lic[0].FillField1[0]` (how the amount is documented).
- Item 4 asked for payment first: `Page3[0].List4[0].Item4[0].Checkbox50[0]`=Yes / `[1]`=No.
- Item 5 venue: option a (where defendant lives) = `Page3[0].List5[0].Lia[0].Checkbox5cb[0]`; Item 6 venue zip: `Page3[0].List6[0].item6[0].ZipCode1[0]`.
- Item 7 attorney-fee dispute `Page3[0].List7[0].item7[0].Checkbox60[0]`=Yes / `[1]`=No — REQUIRED answer, No unless the description says it is an attorney-client fee dispute.
- Item 8 public entity `Page3[0].List8[0].item8[0].Checkbox61[0]`=Yes / `[1]`=No — REQUIRED answer, No unless the defendant is a public entity; when No, also leave `Checkbox14` and `Date4` untouched.
- Item 9 (>12 other CA small claims in 12 months): `Page4[0].List9[0].Item9[0].Checkbox62[0]`=Yes / `[1]`=No ("first time filing" -> No).
- Item 10 (claim > $2,500): `Page4[0].List10[0].li10[0].Checkbox63[0]`=Yes / `[1]`=No — derive from the amount.
- Declaration: `Page4[0].Sign[0].Date1[0]` (signing/filing date from the description), `PlaintiffName1[0]` (typed name; leave the signature line itself blank).
- Page 1: leave EVERYTHING empty — `CourtInfo`, `CaseNumber`, `CaseName`, all `Trial*`, clerk signature/date (see bucket 3 in 2.0).
- Date format `xxxx-xx-xx` means `YYYY-MM-DD` (convert e.g. "November 2, 2025" -> `2025-11-02`).

### 2.3 Fill programmatically
pypdf approach:
```python
reader = PdfReader(src); writer = PdfWriter()
writer.clone_document_from_reader(reader)
writer.set_need_appearances_writer(True)   # so viewers render the values
# iterate writer.pages -> page['/Annots'] -> obj = annot.get_object()
# rebuild full field name by walking /Parent chain and joining /T parts
# text:      obj[NameObject('/V')] = TextStringObject(value)
# checkbox:  obj[NameObject('/V')] = obj[NameObject('/AS')] = NameObject('/1')  # on-state
```
PyMuPDF alternative: iterate `page.widgets()`; for text set `w.field_value = s`; for checkboxes `w.field_value = w.button_states()['normal'][0]`; call `w.update()` after each; then `doc.save(out)`.
- Keep a set of intended targets and assert none are missing after the loop (field-name typos silently no-op).

### 2.4 Verify BOTH directions (missing decisions AND extra content)
- Re-open the output with pypdf and print every field whose `/V` is not None/''/Off.
- Completeness: assert each of items 4, 5, 7, 8, 9, 10 has exactly one on-state checkbox. A missing required negative is a failure even when every intended write succeeded.
- No extras: assert the filled set equals the intended set. In particular `CourtInfo`, `CaseNumber`, `CaseName`, all `Trial*`, clerk fields, second-party fields, and pages 5-6 must be empty. Unsupported extra content is a failure even when all required values are present.
- Render pages 2-4 and visually confirm values sit in the right boxes and the correct checkboxes show marks (crop/zoom on any ambiguous checkbox).

## 3. Final report
- For scheduling: state the parsed calendar table, each request -> chosen slot with reasoning (timezone conversions, blue-block overwrites, why an earlier slot was impossible), and files written.
- For form filling: list each item -> value filled (including the required Yes/No answers and their justification), and explicitly list the categories intentionally left blank (court caption, trial/clerk fields, unmentioned optional fields).
