"""UI view adapters: prototype-shaped payloads for A1 overview, A2 persona, Lite and reveal.

The analysis worker builds one row per main session (``section.py`` → ``facts.py``) from the
analysis output plus read-only L1 facts; the gateway filters those rows and re-derives the
page payloads with the same formulas as the prototype's ``15-derive.js`` (``derive.py``).
No analysis core number is recomputed here: msgs / tools / corr come straight from
``analysis.sessions[].features``; every other field carries a basis and stays null when the
logs do not say.
"""

VERSION = "uiview-v1"
CONTRACT = "uiview-facts-v1"
