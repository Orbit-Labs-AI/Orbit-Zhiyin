"""Instruction: explicit user control requirements and prompt structure."""

from .extraction import (
    INSTRUCTION_VERSION,
    extract_instruction_constraints,
    summarize_control_patterns,
)
from .scope import resolve_instruction_scope
from .structure import structure
from .text import instruction_text

__all__ = [
    "INSTRUCTION_VERSION", "extract_instruction_constraints", "instruction_text",
    "resolve_instruction_scope", "structure", "summarize_control_patterns",
]
