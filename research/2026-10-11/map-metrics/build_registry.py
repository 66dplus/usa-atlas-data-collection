#!/usr/bin/env python3
"""Rebuild D1/D2/D5 review artifacts exclusively from frozen evidence."""
from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "full"))
from map_metrics import calculate, load_definitions, validate_definitions  # noqa: E402
from build_map_metric_definitions import raw_unit  # noqa: E402

PREFERRED = {
    "01.01": "population", "01.05": "foreign-born-share", "02.01": "median-household-income",
    "02.02": "per-capita-income", "02.03": "median-gross-rent", "02.04": "median-home-value",
    "02.05": "median-selected-monthly-owner-costs", "02.06": "rent-burden-30-plus-share",
    "02.07": "owner-renter-ratio", "02.08": "poverty-share", "02.09": "households-income-200k-plus-share",
    "02.10": "regional-price-parity", "03.01": "bachelors-degree-exact-share", "03.02": "masters-degree-exact-share",
    "03.03": "doctorate-exact-share", "03.04": "high-school-or-higher-share", "03.05": "no-high-school-diploma-share",
    "03.06": "unemployment-rate", "03.09": "worked-from-home-share", "07.01": "agi-county-total",
    "08.05": "electricity-price-all-sectors", "09.04": "fitness-facilities-density",
}
FOCUS = {"02.06", "02.07", "02.08", "02.09", "03.01", "03.02", "03.03", "03.04", "03.05"}
CHOICE = {
    "01.02": "Choose median age or an explicit age band; the current total is population, not age.",
    "01.03": "Choose a sex category or breakdown; the current total is population.",
    "01.04": "Choose an explicit race/origin category; the current total is population. Race and Hispanic origin differ.",
    "01.06": "Choose a country/region and foreign-born denominator; the current value is the total foreign-born population.",
    "01.07": "Choose citizenship status or distribution; the current value is total population.",
    "01.08": "Choose entry period and nativity; the current total includes all persons born outside the US, including native citizens.",
}


def load(name):
    return json.loads((HERE / name).read_text())


def terms(expression):
    return " + ".join(("" if coefficient == 1 else f"{coefficient} × ") + variable for variable, coefficient in expression.items()) or "—"


def formula_text(item):
    f = item["formula"]
    value = terms(f["numerator"])
    if f["denominator"]:
        value = f"({value}) / ({terms(f['denominator'])})"
    if f["scale"] != 1:
        value += f" × {f['scale']}"
    return value


def freeze_inputs(audit_path, http_manifest_path):
    """Explicit local import of already captured read-only evidence, no network."""
    for source, target in [(audit_path, "selected-series-audit.json"), (http_manifest_path, "http-snapshot-manifest.json")]:
        if source is not None:
            payload = Path(source).read_bytes()
            (HERE / target).write_bytes(payload)


def build():
    errors = validate_definitions()
    if errors:
        raise ValueError("definition_validation_failed: " + "; ".join(errors))
    definitions = load_definitions()["definitions"]
    by_metric = {d["metric_id"]: d for d in definitions}
    by_parent = {d["catalog_field_id"]: [x for x in definitions if x["catalog_field_id"] == d["catalog_field_id"]] for d in definitions}
    official = load("census-variable-metadata.json")["groups"]
    catalog = load("selected-runtime-catalog.json")
    audit = load("selected-series-audit.json")
    http = load("http-snapshot-manifest.json")
    snapshot_by_field = {r["field"]: r for r in http["records"]}
    audited = {r["catalog_field_id"]: r for r in audit["selected_series"]}
    contract = {r["field_id"]: r for r in json.loads((ROOT / "full/field-contract.json").read_text())}
    visibility = (HERE / "runtime-evidence/ux--indicator-visibility.js.txt").read_text()
    visible = set(re.findall(r"'([0-9]{2}\.[0-9]{2})': true", visibility))
    if visible != set(audited) or len(visible) != 35:
        raise ValueError("audit_does_not_cover_fixed35")
    tree = ast.parse((HERE / "runtime-evidence/scripts--atlas_data.py.txt").read_text())
    defaults = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "DEFAULT_SERIES" for t in n.targets))
    rows = []
    for runtime in sorted(catalog["selected_metrics"], key=lambda m: m["catalogId"]):
        parent, selected = runtime["catalogId"], runtime["fieldId"]
        evidence = audited[parent]
        if evidence["selected_field_id"] != selected:
            raise ValueError(f"{parent}: runtime_audit_selection_mismatch")
        # Explicit defaults must match the copied adapter. ACS fallback is the
        # first estimate in its sorted live series inventory, usually total001.
        if parent in defaults and defaults[parent] != selected:
            raise ValueError(f"{parent}: frozen_explicit_default_mismatch")
        snapshot = evidence["snapshot"]
        served = snapshot_by_field[selected]
        if snapshot["period"] != served["period"] or snapshot["source_release"] != served["sourceRelease"]:
            raise ValueError(f"{parent}: HTTP_database_snapshot_mismatch")
        units = sorted({r["unit"] for r in evidence["level_counts"]})
        if units != [served["sourceUnit"]]:
            raise ValueError(f"{parent}: HTTP_database_unit_mismatch")
        candidate = by_metric.get(PREFERRED.get(parent, ""))
        if parent.startswith("04."):
            candidate = by_parent[parent][0]
        if snapshot["source"] == "census_acs":
            variable = selected.split(":", 1)[1]
            group = variable.split("_")[0]
            metadata = official[group]["variables"][variable]
            restored = raw_unit(group)
            meaning = metadata["concept"] + " · " + metadata["label"].replace("Estimate!!", "").replace("!!", " · ")
            universe = metadata["universe"]
            period = "2020–2024 (stored 2024)"
            source_url = official[group]["url"]
        else:
            restored, meaning, universe = candidate["raw_component_unit"], candidate["label"], candidate["universe"]
            period, source_url = snapshot["period"], candidate["source_urls"][0]
        if parent in CHOICE:
            status, next_action = "product_selection_required", CHOICE[parent]
        elif parent.startswith("04."):
            status, next_action = "matched_rate_denominator_required", "Preserve reported counts; per-100k comparison needs annual covered population and participation metadata from the same period."
        elif candidate["formula"]["operation"] != "identity":
            status, next_action = "checked_formula_available", "Current scalar is a source count. Consume the checked formula with all components; retain the count."
        elif parent == "07.01":
            status, next_action = "county_total_state_policy_required", "Display USD by ×1,000; state/US values require separate validated aggregation and disclosure review."
        elif parent == "09.04":
            status, next_action = "checked_unit_county_only", "Display facilities per 1,000 people; county-only and incomplete numeric coverage. State density requires compatible weights."
        elif parent == "02.05":
            status, next_action = "all_owner_costs_scope", "Current median covers all owners. With-mortgage-only B25088_002E is a separate explicit choice."
        else:
            status, next_action = "checked_scalar", "Use exact native observation with restored display unit."
        checked = {"metric_id": candidate["metric_id"], "label": candidate["label"], "unit": candidate["display_unit"],
                   "numerator": candidate["formula"]["numerator"], "denominator": candidate["formula"]["denominator"],
                   "scale": candidate["formula"]["scale"], "formula": formula_text(candidate),
                   "state_calculation": candidate["state_calculation"], "nation_calculation": candidate["nation_calculation"],
                   "limitations": candidate["limitations"]} if candidate else None
        rows.append({"catalog_field_id": parent, "catalog_label": contract[parent]["catalog_label"],
            "runtime_metric_id": runtime["id"], "runtime_label": runtime["name"],
            "selected_field_id": selected, "source": snapshot["source"], "stored_period": snapshot["period"],
            "reference_period": period, "source_release": snapshot["source_release"], "stored_unit": units[0],
            "restored_selected_unit": restored, "selected_value_meaning": meaning, "selected_universe": universe,
            "selected_value_formula": {"operation": "identity", "numerator": {selected: 1}, "denominator": {}, "scale": 1},
            "selected_native_level_counts": evidence["level_counts"], "selected_native_level_presence": evidence["level_presence"],
            "adapter_geography_counts": served["geo_counts"], "adapter_excluded_rows": served["excluded"],
            "adapter_nation_policy": "Native nation rows rejected; BEA 00000 and EIA US state-typed IDs can map to US.",
            "source_url": source_url, "status": status, "next_action": next_action,
            "checked_candidate": checked, "available_checked_definition_ids": [d["metric_id"] for d in by_parent[parent]],
            "raw_examples": evidence["examples"]})
    inputs = ["selected-series-audit.json", "http-snapshot-manifest.json", "selected-runtime-catalog.json",
              "census-variable-metadata.json", "prod-formula-inputs.json", "runtime-evidence/manifest.json"]
    result = {"format": "usa_atlas_map_metric_registry_v1", "runtime_baseline": "20261011-collected35",
        "runtime_base_commit": "2e9280d (modified working tree, preserved source hashes)",
        "prod_audit_at": audit["captured_at"], "http_capture_at": http["captured_at"],
        "scope": "Exact 35 enabled parent fields and their default subseries. Newer medical38 fields excluded. Checked definitions are opt-in; frontend unchanged.",
        "evidence_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in inputs},
        "definitions_sha256": hashlib.sha256((ROOT / "full/map-metric-definitions.json").read_bytes()).hexdigest(),
        "fields": rows}
    (HERE / "metric-registry.json").write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    write_csv(rows)
    calculations = write_examples(definitions)
    write_markdown(result, calculations)
    return result


def write_csv(rows):
    names = ["catalog_field_id", "catalog_label", "runtime_label", "selected_field_id", "source", "reference_period", "source_release",
             "stored_unit", "restored_selected_unit", "selected_value_meaning", "selected_universe", "native_levels_present", "native_levels_unknown",
             "candidate_metric_id", "candidate_unit", "numerator", "denominator", "formula", "state_calculation", "nation_calculation", "status", "next_action", "limitations", "source_url"]
    with (HERE / "metric-registry.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, names, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            result = {key: row[key] for key in names if key in row}
            presence = row["selected_native_level_presence"]
            result.update(native_levels_present=";".join(p["geo_type"] for p in presence if p["present"] is True),
                          native_levels_unknown=";".join(p["geo_type"] for p in presence if p["present"] is None))
            candidate = row["checked_candidate"]
            result.update(candidate_metric_id=candidate["metric_id"] if candidate else "",
                          candidate_unit=candidate["unit"] if candidate else "")
            if candidate:
                result.update({key: candidate[key] for key in ["formula", "state_calculation", "nation_calculation"]})
                result.update(numerator=terms(candidate["numerator"]), denominator=terms(candidate["denominator"]), limitations="; ".join(candidate["limitations"]))
            writer.writerow(result)


def write_examples(definitions):
    inputs = load("prod-formula-inputs.json")
    outputs = []
    for item in definitions:
        if item["catalog_field_id"] not in FOCUS or item["metric_id"] == "poverty-share-b17021":
            continue
        for geo in ["41", "US"]:
            rows = [r for r in inputs["rows"] if r["catalog_field_id"] == item["catalog_field_id"] and r["geo_id"] == geo]
            result = calculate(item, rows)
            if result["status"] != "observed":
                raise ValueError(f"{item['metric_id']}:{geo}: {result['status']}")
            outputs.append(result)
    (HERE / "formula-examples.json").write_text(json.dumps({"format": "usa_atlas_checked_map_formula_examples_v1",
        "input_read_at": inputs["read_at"], "input_sha256": hashlib.sha256((HERE / "prod-formula-inputs.json").read_bytes()).hexdigest(),
        "examples": outputs}, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return outputs


def escape(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_markdown(result, calculations):
    text = ["# Реестр 35 полей карты — D1, D2 и D5", "",
        f"Проверен исходный runtime `20261011-collected35` с базой `2e9280d` и сохранёнными хешами незакоммиченных файлов. PROD прочитан READ ONLY {result['prod_audit_at']}; HTTP-снимок — {result['http_capture_at']}. Более поздние три медицинских поля исключены фиксированным списком видимости.", "",
        "Готовы отдельный реестр и проверенные вычисления; интерфейс и исходные наблюдения не изменены. [CSV](metric-registry.csv), [JSON](metric-registry.json), [машинные определения](../../../full/map-metric-definitions.json), [примеры формул](formula-examples.json).", "",
        "`2024` для ACS означает оценку за **2020–2024**, не годовую статистику. `source_defined` восстановлен по конкретной переменной, поэтому исходный count в таблице ниже не становится процентом без числителя и знаменателя.", "",
        "| ID | Поле каталога | Выбранная подсерия | Источник / период | Выпуск | Восстановленная исходная единица |", "|---|---|---|---|---|---|"]
    for row in result["fields"]:
        text.append("| " + " | ".join(escape(row[key]) for key in ["catalog_field_id", "catalog_label", "selected_field_id"]) + f" | {escape(row['source'])} / {escape(row['reference_period'])} | {escape(row['source_release'])} | {escape(row['restored_selected_unit'])} |")
    text.extend(["", "Уровни ниже относятся **к выбранной подсерии, периоду и выпуску**, а не ко всем подсериям родительского поля. Для nation/state/county есть точные counts в JSON. На остальных уровнях присутствие подтверждается совпавшей записью в ограниченной индексной выборке; `?` означает, что полное отсутствие не доказано. Counts state могут включать PR, США или региональные коды; это не количество штатов США.", "",
                 "| ID | Native уровни | Проверенное значение / требуемый выбор | Единица результата |", "|---|---|---|---|"])
    for row in result["fields"]:
        presence = row["selected_native_level_presence"]
        levels = ", ".join(p["geo_type"] + ("?" if p["present"] is None else "") for p in presence if p["present"] is not False)
        candidate = row["checked_candidate"]
        action = candidate["formula"] if candidate else row["next_action"]
        if row["status"] in {"matched_rate_denominator_required", "county_total_state_policy_required", "checked_unit_county_only", "all_owner_costs_scope"}:
            action += "; " + row["next_action"]
        text.append(f"| {row['catalog_field_id']} | {escape(levels)} | {escape(action)} | {escape(candidate['unit'] if candidate else 'Требуется выбор')} |")
    text.extend(["", "Образование: Bachelor’s, Master’s и Doctorate — **наивысший завершённый уровень**, не накопительная степень «или выше». High school включает GED и все более высокие уровни; no diploma — 002–016. Варианты owner/renter ratio и owner/renter share имеют разные знаменатели и отдельные ID. Rent burden исключает `Not computed`, не включает весь count арендаторов.", "",
        "Для широких age/sex/race/birthplace/citizenship/entry-полей сохранены явные варианты. Автоматически назначать одну категорию фронтенду нельзя: продуктовый выбор остаётся открытым. Текущий total — численность соответствующей universe, а не выбранная категория.", "",
        "Для crime сохранены исходные reported counts и помечен пробел: корректный rate на 100 000 требует годового знаменателя и покрывающей его reporting population. ACS 2020–2024 не используется молча как население 2023 года. Поэтому D5 содержит готовые единицы и контракт, но event rates пока требуют совместимого источника.", "",
        "USDA fitness — facilities на **1 000** жителей за 2020, выпуск 2025. У выбранной серии только 1 294 county-наблюдения; state плотность нельзя получить суммой округов. AGI хранится в тысячах USD, отображение USD — ×1 000; per-return знаменатель не выбран.", "",
        "Для штата и США ACS-формулы вычисляются из их **native** компонентов того же выпуска. Медианы округов не усредняются. Национальная BLS-оценка и derived state-sum aggregate имеют разное происхождение; seasonal adjustment state/county различается. BEA сохраняет базу US = 100, EIA all sectors не заменяется residential ценой.", "",
        "## Исходные и ожидаемые значения: Oregon и США", "",
        "Данные из bounded PROD-запросов; это значения ACS **2020–2024**. Числители и знаменатели сохранены без округления; округление ниже используется только для чтения. MOE — 90%, вычисляемые интервалы приблизительны, неизвестный MOE не заменяется нулём.", "",
        "| Формула | Oregon: числитель / знаменатель | Oregon: результат | США: результат |", "|---|---|---|---|"])
    for oregon in [c for c in calculations if c["geo_id"] == "41"]:
        nation = next(c for c in calculations if c["metric_id"] == oregon["metric_id"] and c["geo_id"] == "US")
        num = f"{oregon['numerator']:,.0f} / {oregon['denominator']:,.0f}"
        unit = oregon["unit"]
        text.append(f"| {oregon['metric_id']} | {num} | {oregon['value']:.6f} {unit} | {nation['value']:.6f} {unit} |")
    text.extend(["", "## Проверка и использование", "", "Из корня репозитория:", "", "```bash", "python3 full/build_map_metric_definitions.py", "python3 research/2026-10-11/map-metrics/build_registry.py", "python3 -m unittest discover -s full -p test_map_metrics.py", "```", "",
        "`full.map_metrics.calculate(metric_id, admission_rows)` принимает неизменённые source records, проверяет period/release/source/geography/unit и возвращает отдельный derived результат. `comparison_record(result, geo_vintage=..., adjustment=...)` связывает его с `database.map_quality.MetricObservation(**record)`; geography vintage и сезонность задаются явно. JSON содержит реальные input field IDs, исходные значения, source URL и метод неопределённости.", "",
        "Источники: [ACS five-year guidance](https://www.census.gov/programs-surveys/acs/guidance/estimates.html), [ACS handbook and derived MOE](https://www.census.gov/programs-surveys/acs/library/handbooks/general.html), [BLS seasonal adjustment](https://www.bls.gov/lau/lauseas.htm), [BEA RPP](https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area), [IRS county data](https://www.irs.gov/statistics/soi-tax-stats-county-data), [EIA price data](https://www.eia.gov/electricity/sales_revenue_price/), [USDA definitions](https://www.ers.usda.gov/data-products/food-environment-atlas/documentation/). Конкретные Census variable labels/universes и payload hashes сохранены в [metadata](census-variable-metadata.json).", ""])
    (HERE / "README.md").write_text("\n".join(text))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-audit", type=Path)
    parser.add_argument("--freeze-http-manifest", type=Path)
    args = parser.parse_args()
    freeze_inputs(args.freeze_audit, args.freeze_http_manifest)
    result = build()
    print(f"Checked {len(result['fields'])} fixed runtime fields; no database writes.")
