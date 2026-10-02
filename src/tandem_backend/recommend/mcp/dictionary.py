"""MCP capabilities and declared access requirements."""

from typing import Literal

from pydantic import Field

from ..contracts import Contract


class ItemFeatures(Contract):
    service: str | None = None
    tool_list: list[str] = Field(default_factory=list)
    read_actions: list[str] = Field(default_factory=list)
    write_actions: list[str] = Field(default_factory=list)
    auth_type: str | None = None
    permissions: list[str] = Field(default_factory=list)
    local_or_remote: Literal["local", "remote"] | None = None
    rate_limit: str | None = None
