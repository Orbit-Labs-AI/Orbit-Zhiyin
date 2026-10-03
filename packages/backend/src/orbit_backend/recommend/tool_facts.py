"""Canonical write/edit classification shared by recommendation facts and handoff."""

EDIT_KINDS = ("file.edit", "file.write")
EDIT_NAMES = ("edit", "write", "multiedit", "apply_patch")


def is_edit(name: str | None, kind: str | None = None) -> bool:
    return kind in EDIT_KINDS or (name or "").lower() in EDIT_NAMES
