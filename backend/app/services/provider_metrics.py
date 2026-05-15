from __future__ import annotations

from collections import defaultdict
from typing import Any


def summarize_provider_metrics(
    vision_structured_items: list[dict[str, Any]] | None,
    cross_validation_items: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    samples = _collect_provider_samples(vision_structured_items, cross_validation_items)
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
