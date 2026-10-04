---
name: pdf-acroform-court-form-filler
description: "Fill an interactive (AcroForm) PDF such as California SC-100 from a prose case description. Enumerate fields and tooltips to map semantics, discover each checkbox's real on-state from appearance states instead of guessing, fill case-derived text values, and answer EVERY required paired Yes/No eligibility question (negative option when the narrative is silent on the condition; derive count/amount-based answers from the stated facts) while leaving page-1 court caption fields and unmentioned optional subsections empty and standalone opt-in boxes off. Verify by re-deriving the expected answer set from the request and form, then diffing against a fresh value dump and rendered pages, zooming into ambiguous checkbox areas."
---

# pdf-acroform-court-form-filler

## When to use
User provides a blank fillable PDF form (court/agency form like SC-100) plus a prose description of the facts, and asks to save a filled copy, filling only necessary fields and using a mandated date format (e.g., xxxx-xx-xx).

## Do not apply when
- Never guess a checkbox export value (e.g., '/Yes'); read the widget's on-state from /AP/N keys (pypdf) or widget.button_states() (pymupdf) and map [0]/[1] to the printed Yes/No or option-letter labels by position.
- Never leave a required paired Yes/No eligibility question blank because the narrative is silent: for attorney-fee-dispute, public-entity, filing-frequency and claim-size questions, an unmentioned condition means the required answer is 'No' (or is derived from the stated amount/history), and exactly one option must be on.
- Leave every page-1 court caption field empty — court name/address (CourtInfo), case number, case name, trial date/time/department rows, clerk signature/date; do not infer the county court from a party's city.
- Keep standalone opt-in checkboxes (attachments, arbitration, claims filed against public entities, military-duty) and optional text subsections (second plaintiff/defendant, alternate mailing address) empty unless the description affirmatively applies them.
- Do not sign the signature line; type/print the name and date only.
- Do not set only /V for checkboxes — also set /AS (pypdf) or call widget.update() (pymupdf), otherwise the check may exist in data but not render.
- Do not declare success after writing; tool execution success is not task success — verify by re-deriving the expected answer set from the request and form, then diffing against a fresh value dump and rendered pages.

## Procedure
1. Enumerate all form fields with `pypdf.PdfReader(...).get_fields()`: capture full hierarchical names (e.g. SC-100[0].Page2[0]...), field types (/Tx vs /Btn), and the /TU tooltip text, which states each field's meaning (e.g., which checkbox is 'more than 12 claims' vs 'not', 'claim over $2,500' vs not).
2. Map fields to the printed layout (render pages, dump page text, list widget rects via `page.widgets()`) and classify EVERY question on the form into: required paired Yes/No, required single-choice lettered options (venue), standalone opt-in box, optional text subsection, or court/clerk-filled. Record the classification — it, not the narrative's silence, decides what may be left blank.
3. For every checkbox to be set, discover its on-state: list /AP/N keys via pypdf (e.g. Checkbox50[0] -> ['/1']) or `widget.button_states()['normal'][0]` via pymupdf, and confirm [0]/[1] semantics by comparing widget rect coordinates with nearby label word positions (`page.get_text("words")`).
4. Fill only what the step-2 classification allows: (a) case-derived text — party names/phones/addresses/emails, claim amount and reason narrative, incident start/through dates in the mandated xxxx-xx-xx format, venue zip, declaration date + typed name; (b) required selections — venue letter matching the stated reason, payment-demand Yes, filing-frequency and claim-size answers derived from the stated history/amount, AND the negative option of every other required paired Yes/No question (e.g., attorney-client fee dispute -> No, suing a public entity -> No), because silence on the condition IS the answer, not a reason to skip; (c) nothing else — page-1 court caption, optional subsections and opt-in boxes stay untouched. Write via pypdf (/V on text widgets, /V and /AS on checkboxes, `writer.set_need_appearances_writer(True)`) or pymupdf (`w.field_value = ...; w.update()`); track matched targets and assert none are missing before saving. (Counterexample: an externally graded run that omitted the attorney-fee and public-entity 'No' checks failed exactly those two completeness assertions.)
5. Verify the saved PDF independently: first re-derive the expected answer set from the request and the form's question list (which texts, which Yes/No/venue selections including required 'No' answers, which fields must stay empty), then re-open the output, dump all non-empty/non-/Off field values, and diff in BOTH directions — missing required decisions and extra unsupported fills are equally failures. Render filled pages (pymupdf get_pixmap or pdftoppm) and visually inspect entries and check marks, cropping/zooming into ambiguous checkbox regions. (Counterexample: the failed run's own re-read confirmed only its intended writes and so never noticed the two unanswered required questions.)

## Verify
- Expected answer set is re-derived from the request plus the form's question list BEFORE reading the output: required texts, required Yes/No/venue selections (including required 'No' answers), and fields that must stay empty.
- Post-write dump diff: exactly one on-state per required paired question (payment demand, venue, attorney-fee dispute, public entity, >12 claims, claim-size) — a missing required 'No' fails just as an extra unsupported fill does.
- Page-1 court caption fields (CourtInfo, case number/name, trial rows, clerk signature/date) and unmentioned optional subsections are absent from the dump; standalone opt-in boxes remain /Off.
- Rendered pages (get_pixmap/pdftoppm) show legible typed values and visibly correct check marks; ambiguous checkbox regions re-rendered at higher DPI and cropped for confirmation.

## Stop
Stop when the output PDF exists at the requested path, the dump-vs-expectation diff is empty in both directions (all case-derived values and all required Yes/No selections present; court, optional and opt-in fields empty), all dates follow the mandated format, and rendered pages visually confirm the entries and check marks.

## Limits
- Field names are specific to this SC-100 revision; the enumeration/tooltip-driven mapping and the required-vs-optional question classification are the reusable parts.
- The negative default applies only to required paired Yes/No eligibility questions, not to standalone opt-in boxes or optional text sections; classify each question from its tooltip and printed labels on any new form.
- One external validation run (skill usage confirmed) failed only the two required-negative checkbox assertions this revision targets; the corrected rule is provisional until re-validated.
- No session exercised recovery for missing pypdf/pymupdf, XFA-only forms, or fields that accept data but do not render.
