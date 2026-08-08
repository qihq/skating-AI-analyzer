from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.analysis_v2.fact_consumers import consumer_for_analysis


def summarize_provider_metrics(
    vision_structured_items: list[dict[str, Any]] | None,
    cross_validation_items: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    samples = _collect_provider_samples(vision_structured_items, cross_validation_items)
    return _summarize_samples(samples)


def _summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate normalized diagnostic samples shared by legacy and V2 paths."""
    if not samples:
        return {
            "providers": {},
            "summary": {
                "provider_count": 0,
                "sample_count": 0,
                "json_valid_rate": 0.0,
                "avg_effective_weight": 0.0,
                "conflict_rate": 0.0,
                "failure_rate": 0.0,
            },
            "recommendations": [],
        }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[sample["provider"]].append(sample)

    providers: dict[str, Any] = {}
    totals = {
        "sample_count": len(samples),
        "json_valid_ok": 0,
        "effective_weight_sum": 0.0,
        "conflict_count": 0,
        "failure_count": 0,
    }

    for provider, provider_samples in sorted(grouped.items()):
        metrics = _summarize_provider_samples(provider_samples)
        providers[provider] = metrics
        totals["json_valid_ok"] += metrics["json_valid_ok"]
        totals["effective_weight_sum"] += metrics["effective_weight_sum"]
        totals["conflict_count"] += metrics["conflict_count"]
        totals["failure_count"] += metrics["failure_count"]

    sample_count = totals["sample_count"]
    summary = {
        "provider_count": len(providers),
        "sample_count": sample_count,
        "json_valid_rate": round(totals["json_valid_ok"] / sample_count, 4),
        "avg_effective_weight": round(totals["effective_weight_sum"] / sample_count, 4),
        "conflict_rate": round(totals["conflict_count"] / sample_count, 4),
        "failure_rate": round(totals["failure_count"] / sample_count, 4),
    }

    return {
        "providers": providers,
        "summary": summary,
        "recommendations": _build_recommendations(providers, summary),
    }


def summarize_v2_fact_metrics(
    consumers: list[Any] | tuple[Any, ...],
    *,
    provider_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Summarize V2 provider-role evidence without reading compatibility slots.

    V2 analyses persist claim-level source fingerprints, not the raw Path A/B
    payloads.  This diagnostic projection deliberately treats each supported
    source claim as a bounded sample and keeps conflicts/refusals visible.  A
    provider fingerprint is resolved to a human label when the active/provider
    inventory has one; otherwise the role and a short fingerprint are used.
    """

    labels = provider_labels or {}
    samples: list[dict[str, Any]] = []
    for consumer in consumers:
        facts = getattr(consumer, "all_facts", ()) or getattr(consumer, "facts", ())
        for fact in facts:
            sources = tuple(getattr(fact, "sources", ()) or ())
            fingerprints = dict(getattr(fact, "source_fingerprints", {}) or {})
            # Fusion adds its own fingerprint; it is not a provider sample.
            source_names = [source for source in sources if source in {"path_a", "path_b", "deterministic", "deterministic_measurement", "rotation_estimator", "key_moment", "action_classifier"}]
            if not source_names:
                continue
            for source in source_names:
                fingerprint = str(fingerprints.get(source) or "").strip()
                if source in {"path_a", "path_b"}:
                    label = labels.get(fingerprint) or f"{source}:{fingerprint[:12] or 'unknown'}"
                elif source == "deterministic_measurement":
                    label = labels.get(fingerprint) or "deterministic_measurement"
                else:
                    label = labels.get(fingerprint) or source
                status = str(getattr(fact, "status", "unobservable") or "unobservable")
                conflicts = tuple(getattr(fact, "conflicts", ()) or ())
                confidence = getattr(fact, "confidence", None)
                samples.append(
                    {
                        "provider": label,
                        "json_validity_factor": 1.0 if status != "unobservable" else 0.0,
                        "effective_weight": float(confidence) if isinstance(confidence, (int, float)) else 0.0,
                        "conflict": bool(conflicts) or status == "uncertain",
                        "failure": status == "unobservable",
                    }
                )
    return _summarize_samples(samples)


def merge_provider_metric_reports(*reports: dict[str, Any]) -> dict[str, Any]:
    """Merge legacy and V2 diagnostic summaries without mixing source payloads."""

    samples: list[dict[str, Any]] = []
    for report in reports:
        for provider, metrics in (report.get("providers", {}) if isinstance(report, dict) else {}).items():
            if not isinstance(metrics, dict):
                continue
            count = int(metrics.get("sample_count", 0) or 0)
            if count <= 0:
                continue
            # Expand aggregate values only for the diagnostic merge.  This is
            # lossless for the displayed rates and avoids exposing raw inputs.
            for index in range(count):
                samples.append(
                    {
                        "provider": provider,
                        "json_validity_factor": 1.0 if index < int(round(metrics.get("json_valid_rate", 0.0) * count)) else 0.0,
                        "effective_weight": metrics.get("avg_effective_weight", 0.0),
                        "conflict": index < int(round(metrics.get("conflict_rate", 0.0) * count)),
                        "failure": index < int(round(metrics.get("failure_rate", 0.0) * count)),
                    }
                )
    return _summarize_samples(samples)


def summarize_provider_metrics_for_analyses(
    analyses: list[Any] | tuple[Any, ...],
    *,
    provider_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build provider diagnostics from the analysis authority boundary.

    V2 rows are read exclusively through ``AnalysisFactsV2``.  Legacy rows
    retain the characterized compatibility projection so historical provider
    metrics remain available without changing their semantics.
    """

    legacy_vision: list[dict[str, Any] | None] = []
    legacy_cross: list[dict[str, Any] | None] = []
    v2_consumers: list[Any] = []
    for analysis in analyses:
        if str(getattr(analysis, "facts_authority", "") or "").strip().lower() == "v2":
            try:
                v2_consumers.append(consumer_for_analysis(analysis, "family_display"))
            except (TypeError, ValueError):
                # Invalid envelopes are omitted from provider metrics rather
                # than falling back to a different semantic source.
                pass
            continue
        legacy_vision.append(getattr(analysis, "vision_structured", None) if isinstance(getattr(analysis, "vision_structured", None), dict) else None)
        legacy_cross.append(getattr(analysis, "cross_validation", None) if isinstance(getattr(analysis, "cross_validation", None), dict) else None)

    reports: list[dict[str, Any]] = []
    if legacy_vision or legacy_cross:
        reports.append(summarize_provider_metrics(legacy_vision, legacy_cross))
    if v2_consumers:
        reports.append(summarize_v2_fact_metrics(v2_consumers, provider_labels=provider_labels))
    return merge_provider_metric_reports(*reports) if reports else _summarize_samples([])


def _collect_provider_samples(
    vision_structured_items: list[dict[str, Any]] | None,
    cross_validation_items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    paired_cross = cross_validation_items or []

    for index, vision_structured in enumerate(vision_structured_items or []):
        cross_validation = paired_cross[index] if index < len(paired_cross) else None
        samples.extend(_samples_from_record(vision_structured, cross_validation))

    for index in range(len(vision_structured_items or []), len(paired_cross)):
        samples.extend(_samples_from_record(None, paired_cross[index]))

    return samples


def _samples_from_record(
    vision_structured: dict[str, Any] | None,
    cross_validation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    by_provider: dict[str, dict[str, Any]] = {}

    for provider, payload in _provider_payloads(vision_structured, cross_validation):
        if not provider:
            continue
        normalized = _normalize_sample(provider, payload, cross_validation)
        if normalized is None:
            continue
        by_provider[provider] = normalized

    return list(by_provider.values())


def _provider_payloads(
    vision_structured: dict[str, Any] | None,
    cross_validation: dict[str, Any] | None,
) -> list[tuple[str, dict[str, Any]]]:
    payloads: list[tuple[str, dict[str, Any]]] = []

    if isinstance(vision_structured, dict):
        provider = _provider_name(vision_structured)
        if provider:
            payloads.append((provider, vision_structured))

        model_results = vision_structured.get("model_results")
        if isinstance(model_results, list):
            for model_result in model_results:
                if not isinstance(model_result, dict):
                    continue
                provider = _provider_name(model_result)
                if provider:
                    payloads.append((provider, model_result))

        fusion_decisions = vision_structured.get("fusion_decisions")
        if isinstance(fusion_decisions, list):
            for decision in fusion_decisions:
                if not isinstance(decision, dict):
                    continue
                candidates = decision.get("candidates")
                if not isinstance(candidates, list):
                    continue
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    provider = _normalize_provider_key(candidate.get("provider"))
                    if provider:
                        payloads.append((provider, candidate))

    if isinstance(cross_validation, dict):
        diagnostics = cross_validation.get("fusion_diagnostics")
        if isinstance(diagnostics, dict):
            for path_name in ("path_a", "path_b"):
                path_diag = diagnostics.get(path_name)
                if not isinstance(path_diag, dict):
                    continue
                provider = _normalize_provider_key(path_diag.get("provider"))
                if provider:
                    payloads.append((provider, path_diag))

    return payloads


def _normalize_sample(
    provider: str,
    payload: dict[str, Any],
    cross_validation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    json_validity_factor = _extract_float(payload, "json_validity_factor")
    if json_validity_factor is None and isinstance(payload.get("quality"), dict):
        json_validity_factor = _extract_float(payload["quality"], "json_validity_factor")
    if json_validity_factor is None and isinstance(payload.get("factors"), dict):
        json_validity_factor = _extract_float(payload["factors"], "json_validity_factor")

    effective_weight = _extract_float(payload, "effective_weight")
    if effective_weight is None and isinstance(payload.get("base_factors"), dict):
        effective_weight = _effective_weight_from_base_factors(payload["base_factors"])

    if effective_weight is None:
        effective_weight = _extract_float(payload, "weight")

    if json_validity_factor is None and effective_weight is None and not _has_confidence_signal(payload):
        return None

    return {
        "provider": provider,
        "json_validity_factor": json_validity_factor if json_validity_factor is not None else 0.0,
        "effective_weight": effective_weight if effective_weight is not None else 0.0,
        "conflict": _is_conflict(payload, cross_validation),
        "failure": _is_failure(payload, cross_validation),
    }


def _has_confidence_signal(payload: dict[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "json_validity_factor",
            "effective_weight",
            "base_factors",
            "factors",
            "quality",
            "conflict_level",
            "rule_flags",
            "high_confidence_conflicts",
            "error",
        )
    )


def _is_conflict(payload: dict[str, Any], cross_validation: dict[str, Any] | None) -> bool:
    if bool(payload.get("rule_flags")):
        return True
    if bool(payload.get("high_confidence_conflicts")):
        return True
    if payload.get("conflict_level") == "high":
        return True
    if isinstance(cross_validation, dict):
        if cross_validation.get("conflict_level") == "high":
            return True
        diagnostics = cross_validation.get("fusion_diagnostics")
        if isinstance(diagnostics, dict):
            if diagnostics.get("conflict_level") == "high":
                return True
            if diagnostics.get("needs_human_review") is True:
                return True
    return False


def _is_failure(payload: dict[str, Any], cross_validation: dict[str, Any] | None) -> bool:
    if bool(payload.get("error")):
        return True
    flags = payload.get("quality_flags")
    if isinstance(flags, list) and any("fallback" in str(flag) or "failed" in str(flag) for flag in flags):
        return True
    if isinstance(cross_validation, dict):
        diagnostics = cross_validation.get("fusion_diagnostics")
        if isinstance(diagnostics, dict):
            path_b = diagnostics.get("path_b")
            if isinstance(path_b, dict) and path_b.get("available") is False:
                return True
    return False


def _summarize_provider_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(samples)
    json_valid_ok = sum(1 for sample in samples if sample["json_validity_factor"] >= 0.8)
    effective_weight_sum = sum(float(sample["effective_weight"]) for sample in samples)
    conflict_count = sum(1 for sample in samples if sample["conflict"])
    failure_count = sum(1 for sample in samples if sample["failure"])
    return {
        "sample_count": total,
        "json_valid_ok": json_valid_ok,
        "json_valid_rate": round(json_valid_ok / total, 4) if total else 0.0,
        "effective_weight_sum": round(effective_weight_sum, 6),
        "avg_effective_weight": round(effective_weight_sum / total, 4) if total else 0.0,
        "conflict_count": conflict_count,
        "conflict_rate": round(conflict_count / total, 4) if total else 0.0,
        "failure_count": failure_count,
        "failure_rate": round(failure_count / total, 4) if total else 0.0,
    }


def _build_recommendations(providers: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    for provider, metrics in providers.items():
        if metrics["failure_rate"] > 0.25:
            recommendations.append(f"reduce_weight:{provider}")
        elif metrics["avg_effective_weight"] < 0.4 and metrics["json_valid_rate"] >= 0.8:
            recommendations.append(f"increase_weight:{provider}")
        if metrics["conflict_rate"] > 0.35:
            recommendations.append(f"review_conflict_patterns:{provider}")

    if summary["json_valid_rate"] < 0.6:
        recommendations.append("improve_json_validity_guardrails")
    if summary["failure_rate"] > 0.2:
        recommendations.append("prioritize_fallback_resilience")
    return list(dict.fromkeys(recommendations))


def _provider_name(payload: dict[str, Any]) -> str:
    for key in ("provider", "provider_name", "provider_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _normalize_provider_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(float(value), 1.0))


def _effective_weight_from_base_factors(base_factors: dict[str, Any]) -> float | None:
    weight = 1.0
    seen = False
    for key in (
        "provider_base_weight",
        "model_confidence",
        "json_validity_factor",
        "data_quality_factor",
        "specialty_factor",
        "rule_consistency_factor",
    ):
        value = base_factors.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            weight *= max(0.0, min(1.0, float(value)))
            seen = True
    return round(weight, 6) if seen else None
