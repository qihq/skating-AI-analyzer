from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryContextProvider(Protocol):
    async def build_memory_context(self, skater_id: str | None) -> str: ...


class NoopMemoryContext:
    async def build_memory_context(self, skater_id: str | None) -> str:
        return ""
