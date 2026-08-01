from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, Authority


FactUse = Literal[
    "family_display",
    "coaching",
    "aggregation",
    "comparison",
    "correction",
    "automation",
    "share",
    "export",
]


@dataclass(frozen=True)
class AnalysisFactConsumer:
    """Bounded same-authority input for migrated semantic consumers."""

    analysis_id: str
    authority: Authority
    use: FactUse
    source_fact_hash: str
    facts: tuple[AnalysisFactV2, ...]


def build_fact_consumer(facts: AnalysisFactsV2, use: FactUse) -> AnalysisFactConsumer:
    return AnalysisFactConsumer(
        analysis_id=facts.analysis_id,
        authority=facts.authority,
        use=use,
        source_fact_hash=facts.source_fact_hash,
        facts=facts.eligible(use),
    )
