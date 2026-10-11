#!/usr/bin/env python3
"""Checked, read-only map metric calculations over preserved source observations.

This module is an opt-in consumer contract, not an ingestion adapter. It never
connects to a database or rewrites source records. Expressions are linear terms,
not executable strings. Frozen Census metadata validates their meaning.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = ROOT / "full/map-metric-definitions.json"
METADATA = ROOT / "research/2026-10-11/map-metrics/census-variable-metadata.json"
IDENTITY_KEYS = ("source", "source_release", "period", "geo_type", "geo_id")


def load_definitions(path=DEFINITIONS):
    return json.loads(Path(path).read_text())


def definition(metric_id, document=None):
    definitions = (document or load_definitions())["definitions"]
    return next(item for item in definitions if item["metric_id"] == metric_id)


def validate_definitions(document=None, metadata=None):
    """Check formulas against exact frozen official variable labels/universes."""
    document = document or load_definitions()
    metadata = metadata or json.loads(METADATA.read_text())
    errors, identifiers = [], set()
    for item in document["definitions"]:
        metric_id = item["metric_id"]
        if metric_id in identifiers:
            errors.append(f"{metric_id}: duplicate metric identity")
        identifiers.add(metric_id)
        formula = item["formula"]
        if formula["operation"] not in {"identity", "share", "ratio"}:
            errors.append(f"{metric_id}: unsupported operation")
        if formula["operation"] != "identity" and not formula["denominator"]:
            errors.append(f"{metric_id}: missing denominator")
        if item["source"] != "census_acs":
            continue
        variables = set(formula["numerator"]) | set(formula["denominator"])
        for variable in variables:
            source = metadata["groups"].get(variable.split("_")[0], {}).get("variables", {}).get(variable)
            if source is None or not variable.endswith("E"):
                errors.append(f"{metric_id}: unknown estimate {variable}")
                continue
            if source["universe"] != item["universe"]:
                errors.append(f"{metric_id}: wrong universe for {variable}")
            expected = item.get("label_assertions", {}).get(variable)
            if expected and expected not in source["label"]:
                errors.append(f"{metric_id}: label mismatch for {variable}")
    return errors


def _numeric(value, *, allow_negative=False):
    # A JSON boolean is not an observed number, and negative ACS sentinels are
    # never percentages, valid counts or an input to a derived estimate.
    if isinstance(value, bool):
        raise ValueError("invalid_value")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("invalid_value") from error
    if not math.isfinite(result) or result < 0 and not allow_negative:
        raise ValueError("invalid_or_sentinel_value")
    return result


def calculate(metric, rows):
    """Calculate one metric for one exact geography, period and source release.

    Each row supplies the existing admission keys (``year`` or ``period``) and
    ``field_id``. ACS field IDs retain their real variable suffix. Non-ACS IDs
    are exact, including any AGI stub, sector or methodology suffix. Qualitative
    records may be passed with ``quality_status``; they never become zero.
    Missing MOEs leave an otherwise valid estimate with unknown uncertainty.
    """
    item = definition(metric) if isinstance(metric, str) else metric
    formula = item["formula"]
    wanted = set(formula["numerator"]) | set(formula["denominator"])
    index = {}
    for row in rows:
        raw_id = row.get("field_id", "")
        if row.get("catalog_field_id", raw_id.split(":", 1)[0]) != item["catalog_field_id"]:
            continue
        key = raw_id.split(":", 1)[-1] if item["source"] == "census_acs" else raw_id
        if key not in wanted and key not in {v[:-1] + "M" for v in wanted if v.endswith("E")}:
            continue
        if key in index:
            raise ValueError(f"duplicate_component:{key}")
        index[key] = row
    missing = sorted(wanted - index.keys())
    base = {"metric_id": item["metric_id"], "definition_version": item["version"],
            "unit": item["display_unit"], "universe": item["universe"]}
    partial_identities = {tuple(_period(row) if name == "period" else row.get(name)
                                for name in IDENTITY_KEYS) for key, row in index.items() if key in wanted}
    if len(partial_identities) == 1 and all(v is not None for v in next(iter(partial_identities))):
        base.update(zip(IDENTITY_KEYS, next(iter(partial_identities))))
    if missing:
        return {**base, "status": "missing_component", "value": None, "missing_components": missing}
    chosen = [index[key] for key in sorted(wanted)]
    identities = {tuple(_period(row) if key == "period" else row.get(key)
                        for key in IDENTITY_KEYS) for row in chosen}
    if len(identities) != 1 or any(value is None for value in next(iter(identities))):
        raise ValueError("incompatible_component_metadata")
    source, release, period, geography, geo_id = next(iter(identities))
    if source != item["source"] or release not in item["source_releases"]:
        raise ValueError("wrong_source_or_release")
    if geography not in item["native_geographies"]:
        raise ValueError("unsupported_geography")
    if item.get("period") and period != item["period"]:
        raise ValueError("wrong_period")
    for row in chosen:
        if row.get("quality_status", "observed") != "observed":
            return {**base, "status": row["quality_status"], "value": None,
                    "raw_component": {"field_id": row["field_id"], "raw_value": row.get("raw_value")}}
        if row.get("unit") not in item["accepted_input_units"]:
            raise ValueError("wrong_component_unit")
    signed_amount = source == "irs_soi" and item["raw_component_unit"] == "thousand_USD"
    values = {key: _numeric(index[key].get("value"), allow_negative=signed_amount) for key in wanted}
    total = lambda terms: math.fsum(values[key] * coefficient for key, coefficient in terms.items())
    numerator = total(formula["numerator"])
    denominator = total(formula["denominator"]) if formula["denominator"] else None
    if numerator < 0 and not signed_amount or denominator is not None and denominator < 0:
        raise ValueError("negative_derived_count")
    if denominator == 0:
        return {**base, "status": "zero_denominator", "value": None,
                "numerator": numerator, "denominator": denominator}
    if formula["operation"] == "share" and numerator > denominator:
        raise ValueError("numerator_exceeds_universe")
    result = numerator if formula["operation"] == "identity" else numerator / denominator
    factor = formula["scale"]
    moe = None
    uncertainty = "not_supplied"
    if source == "census_acs":
        moes = {}
        for key in wanted:
            row = index.get(key[:-1] + "M")
            if row is None or row.get("quality_status", "observed") != "observed":
                break
            row_identity = tuple(_period(row) if name == "period" else row.get(name)
                                 for name in IDENTITY_KEYS)
            if row_identity not in identities or row.get("unit") not in item["accepted_input_units"]:
                raise ValueError("incompatible_moe_metadata")
            try:
                moes[key] = _numeric(row.get("value"))
            except ValueError:
                break
        if len(moes) == len(wanted):
            rss = lambda terms: math.sqrt(math.fsum((coefficient * moes[key]) ** 2
                                                    for key, coefficient in terms.items()))
            numerator_moe = rss(formula["numerator"])
            if denominator is None:
                moe, uncertainty = numerator_moe * factor, "published_90pct_moe" if len(wanted) == 1 else "approximate_90pct_sum_rss"
            else:
                denominator_moe = rss(formula["denominator"])
                radicand = numerator_moe ** 2 - result ** 2 * denominator_moe ** 2
                if formula["operation"] == "share" and radicand >= 0:
                    uncertainty = "approximate_90pct_subset_proportion"
                else:
                    radicand = numerator_moe ** 2 + result ** 2 * denominator_moe ** 2
                    uncertainty = "approximate_90pct_ratio" if formula["operation"] == "ratio" else "approximate_90pct_ratio_fallback"
                moe = math.sqrt(radicand) / denominator * factor
    identity = formula["operation"] == "identity"
    field_id = (item["catalog_field_id"] + ":" + next(iter(wanted)) if source == "census_acs" else next(iter(wanted))) if identity else f"derived:{item['catalog_field_id']}:{item['metric_id']}:v{item['version']}"
    return {**base, "status": "observed", "value": result * factor, "numerator": numerator,
            "denominator": denominator, "margin_of_error": moe,
            "definition_id": f"map:{item['metric_id']}:v{item['version']}", "field_id": field_id,
            "statistic": item["statistic"],
            "provenance_kind": item.get("provenance_kind", "official" if identity else "derived"),
            "uncertainty_method": uncertainty, "confidence_level": .9 if moe is not None else None,
            "source": source, "source_release": release, "period": period,
            "geo_type": geography, "geo_id": geo_id,
            "raw_components": {key: index[key]["value"] for key in sorted(wanted)},
            "input_field_ids": sorted(row["field_id"] for row in chosen),
            "source_urls": sorted({row["source_url"] for row in chosen if row.get("source_url")}),
            "limitations": item["limitations"]}


def _period(row):
    value = row.get("period", row.get("year"))
    return str(value) if value is not None else None


def comparison_record(calculation, *, geo_vintage, adjustment="not_applicable"):
    """Explicit bridge to ``database.map_quality.MetricObservation(**record)``.

    Geographic vintage and seasonal adjustment must come from the caller's
    verified source metadata. The formula contract restores units from exact
    source variables; this bridge does not guess them from stored numeric values.
    Raw inputs and MOEs remain in the calculation artifact, outside this scalar
    comparison record.
    """
    if calculation["status"] != "observed":
        raise ValueError("comparison_requires_observed_calculation")
    if not geo_vintage or not adjustment:
        raise ValueError("comparison_metadata_unresolved")
    record = {key: calculation[key] for key in ("metric_id", "definition_id", "field_id", "geo_type", "geo_id", "period",
                                               "source", "source_release", "unit", "universe", "value", "statistic", "provenance_kind")}
    return {**record, "quality": "observed", "geo_vintage": geo_vintage, "adjustment": adjustment,
            "source_url": calculation["source_urls"][0] if calculation["source_urls"] else "",
            "methodology_note": "Checked formula " + calculation["definition_id"] + "; inputs: " + ", ".join(calculation["input_field_ids"])}
