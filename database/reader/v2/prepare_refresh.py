"""Verify prepared BLS-adjacent EIA, IRS, PEP, and health inputs for a local reader-v2 review load."""
import argparse
import csv
import hashlib
import json
import pathlib
from decimal import Decimal, InvalidOperation

CONTRACT_VERSION = "2.0.0-candidate"
COLLECTOR_VERSION = "data-refresh-preparation-2026.10.26.1"
ANNUAL_KIND = "annual"
SOURCE_META = {
    "eia": ("eia-epa-2-10", "EIA Electric Power Annual 2025"),
    "irs": ("irs-soi-county-2023", "IRS SOI County 2023"),
    "pep_county": ("census-pep-county-totals-v2025", "Census PEP Vintage 2025"),
    "pep_age": ("census-pep-county-single-age-v2025", "Census PEP Vintage 2025"),
    "pep_nation_age": ("census-pep-national-single-age-v2025", "Census PEP Vintage 2025"),
    "cancer": ("retained-prepared-cancer-2023", None),
    "cancer_publisher": ("retained-publisher-cancer-2023", None),
    "hiv": ("retained-prepared-hiv-2024", None),
    "hiv_publisher": ("retained-publisher-hiv-2024", None),
    "child": ("retained-prepared-child-deaths-under18-2024", None),
    "child_publisher": ("retained-publisher-child-deaths-under18-2024", None),
}
NATIVE_PEP_SHA256 = "6436d4f6972d415caf14cb20776807bc031fc9f1bfc9d6ff26055d592a2b0230"


def sha256(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    with pathlib.Path(path).open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return rows


def number(value, label):
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise ValueError("invalid numeric " + label)
    if not result.is_finite():
        raise ValueError("nonfinite numeric " + label)
    return result


def geo_type(row):
    kind = row["geo_type"]
    if kind == "national":
        return "nation"
    if kind not in ("nation", "state", "county"):
        raise ValueError("unrecognized prepared geography")
    return kind


def validate_medical_rate(row, expected_year, expected_kind, pep_value, native_denominator=True):
    """Return quality/value only after event year, age band, denominator, and formula agree."""
    if int(row["year"]) != expected_year or int(row["denominator_year"]) != expected_year:
        raise ValueError("medical numerator/event year does not match denominator year")
    if row["denominator_kind"] != expected_kind:
        raise ValueError("medical row uses an incorrect age-population denominator")
    numerator = number(row["numerator"], "medical numerator")
    denominator = number(row["denominator"], "medical denominator")
    if denominator != number(pep_value, "matching PEP denominator"):
        raise ValueError("medical denominator does not equal matching PEP input")
    source_status = row["status"]
    value_text = (row.get("value") or "").strip()
    suppressed = "suppress" in source_status.lower() or value_text in ("", "-", "NA", "N/A")
    if suppressed:
        return "suppressed", None, numerator, denominator
    value = number(value_text, "medical rate")
    expected = numerator / denominator * Decimal(100000)
    if abs(value - expected) > Decimal("0.000001"):
        raise ValueError("medical rate is inconsistent with source numerator/denominator")
    if not native_denominator:
        return "missing", None, numerator, denominator
    return "observed", value, numerator, denominator


def native_national_population(path, expected_sha256, year, expected_value=None):
    """Read Census's native US SEX=0/AGE=999 row from its pinned source artifact."""
    if expected_sha256 != NATIVE_PEP_SHA256 or sha256(path) != NATIVE_PEP_SHA256:
        raise ValueError("native national PEP source checksum is not the verified artifact")
    estimate_column = f"POPESTIMATE{year}"
    matches = [row for row in read_csv(path)
               if row.get("SEX") == "0" and row.get("AGE") == "999"]
    if len(matches) != 1 or estimate_column not in matches[0]:
        raise ValueError("native national PEP selector is absent or ambiguous")
    value = int(matches[0][estimate_column])
    if expected_value is not None and value != int(expected_value):
        raise ValueError("native national PEP value differs from expected reviewed control")
    return value


def native_national_age_population(path, expected_sha256, year, population_kind, expected_value=None):
    """Verify national age denominators from the official native single-age file."""
    if expected_sha256 != NATIVE_PEP_SHA256 or sha256(path) != NATIVE_PEP_SHA256:
        raise ValueError("native national PEP source checksum is not the verified artifact")
    year_column = f"POPESTIMATE{year}"
    rows = [row for row in read_csv(path) if row.get("SEX") == "0"]
    total_rows = [row for row in rows if row.get("AGE") == "999"]
    if len(total_rows) != 1 or year_column not in total_rows[0]:
        raise ValueError("native national PEP total selector is absent or ambiguous")
    if population_kind == "age_13_plus":
        age_rows = [row for row in rows if row.get("AGE", "").isdigit() and 0 <= int(row["AGE"]) <= 12]
        if len(age_rows) != 13:
            raise ValueError("native national PEP age 0-12 selector is incomplete")
        value = int(total_rows[0][year_column]) - sum(int(row[year_column]) for row in age_rows)
    elif population_kind == "under_18":
        age_rows = [row for row in rows if row.get("AGE", "").isdigit() and 0 <= int(row["AGE"]) <= 17]
        if len(age_rows) != 18:
            raise ValueError("native national PEP age 0-17 selector is incomplete")
        value = sum(int(row[year_column]) for row in age_rows)
    else:
        raise ValueError("unsupported national PEP age group")
    if expected_value is not None and value != int(expected_value):
        raise ValueError("native national PEP age-group value differs from expected prepared value")
    return value


def main_prepare(prepared_dir, results_path, trusted_results_sha256, output_dir):
    prepared_dir = pathlib.Path(prepared_dir).resolve()
    results_path = pathlib.Path(results_path).resolve()
    output_dir = pathlib.Path(output_dir).resolve()
    if sha256(results_path) != trusted_results_sha256:
        raise ValueError("refresh results inventory hash mismatch")
    results = json.loads(results_path.read_text())
    if results.get("admissionStatus") == "admitted" or results.get("ready") is True:
        raise ValueError("refresh inputs cannot claim admission/readiness")
    artifact_by_id = {row.get("sourceId"): row for row in results.get("sourceArtifacts", [])}
    verified_sources = {}
    for key, (source_id, expected_release) in SOURCE_META.items():
        item = artifact_by_id.get(source_id)
        if not item or item.get("status") not in ("downloaded", "copied_verified_prepared_receipt", "copied_verified_original_publisher_receipt"):
            raise ValueError("required source receipt is absent: " + source_id)
        source_path = pathlib.Path(item["path"])
        if not source_path.is_file() or sha256(source_path) != item.get("sha256"):
            raise ValueError("required source receipt hash mismatch: " + source_id)
        if expected_release and item.get("sha256") is None:
            raise ValueError("official source hash is missing: " + source_id)
        verified_sources[key] = {**item, "path": str(source_path)}

    filenames = {
        "eia": "eia-electricity-price-2025-all-sectors.csv",
        "irs_per_resident": "irs-agi-per-resident-2023.csv",
        "irs_total": "irs-agi-2023-usd.csv",
        "pep": "population-2023-2024.csv",
        "cancer": "cancer-2023-rates.csv",
        "hiv": "hiv-2024-rates.csv",
        "child": "child-deaths-under18-2024-rates.csv",
    }
    paths = {key: prepared_dir / filename for key, filename in filenames.items()}
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("one or more required prepared refresh inputs are absent")
    inputs = {key: {"path": str(path), "sha256": sha256(path), "rows": len(read_csv(path))}
              for key, path in paths.items()}

    pep_rows = read_csv(paths["pep"])
    pep_index = {(geo_type(r), r["geo_id"], int(r["year"]), r["population_kind"]): r for r in pep_rows}
    if len(pep_index) != len(pep_rows):
        raise ValueError("duplicate PEP geography/year/population-kind input")
    observations = []

    def emit(dataset, field, catalog, geo, year, value, unit, quality, source_status,
             source, release, url, raw_hash, note, raw_estimate=None,
             raw_denominator=None, denominator_value=None, source_period=None,
             retrieved_at=None):
        kind = geo["geo_type"]
        gid = geo["geo_id"]
        observation = {
            "dataset_id": dataset, "field_id": field, "catalog_field_id": catalog,
            "geo_id": gid, "geo_type": kind,
            "state_fips": (gid[:2] if kind in ("state", "county") else None),
            "district_code": None, "boundary_vintage": None, "congress_session": None,
            "is_at_large": False, "period_kind": ANNUAL_KIND, "period_year": year,
            "period_month": None, "period_start_year": year, "period_end_year": year,
            "source_period_code": str(source_period or year), "value": str(value) if value is not None else None,
            "unit": unit, "quality_status": quality, "source_value_status": source_status,
            "geography_mapping_status": "mapped", "raw_estimate": str(raw_estimate) if raw_estimate is not None else None,
            "raw_estimate_moe": None, "raw_denominator": str(raw_denominator) if raw_denominator is not None else None,
            "raw_denominator_moe": None, "denominator_value": str(denominator_value) if denominator_value is not None else None,
            "source": source, "source_release": release, "source_url": url,
            "source_version": release, "source_sha256": raw_hash, "methodology_note": note,
            "candidate_status": "local_review",
        }
        if retrieved_at:
            observation["retrieved_at"] = retrieved_at
        identity = "|".join((dataset, field, kind, gid, str(year), release))
        observation["observation_id"] = "refresh-" + hashlib.sha256(identity.encode()).hexdigest()
        observations.append(observation)

    # The prepared US total is independently checked against Census's native
    # SEX=0, AGE=999 row before it is exposed as an observation.
    native_pep = verified_sources["pep_nation_age"]
    if native_pep["sha256"] != NATIVE_PEP_SHA256:
        raise ValueError("native national PEP inventory hash differs from the reviewed control")
    for row in pep_rows:
        year = int(row["year"])
        pop_kind = row["population_kind"]
        if year not in (2023, 2024) or pop_kind not in ("total", "age_13_plus", "under_18"):
            raise ValueError("unexpected PEP year or population kind")
        kind = geo_type(row)
        geo = {"geo_type": kind, "geo_id": row["geo_id"]}
        field = {"total":"01.01:pep_population_total", "age_13_plus":"01.01:pep_population_age_13_plus",
                 "under_18":"01.01:pep_population_under_18"}[pop_kind]
        source_item = native_pep if kind == "nation" else (
            verified_sources["pep_county"] if pop_kind == "total" else verified_sources["pep_age"])
        source_url = source_item.get("url", "https://www.census.gov/programs-surveys/popest.html")
        value = number(row["value"], "PEP value")
        quality, source_value_status, usable_value = "observed", "observed", value
        note = row.get("aggregation", "")
        if kind == "nation" and pop_kind == "total":
            native_value = native_national_population(native_pep["path"], native_pep["sha256"], year, value)
            if int(value) != native_value:
                raise ValueError("prepared native national PEP value differs from pinned Census row")
            note += "; verified native Census SEX=0 AGE=999 national estimate"
        elif kind == "nation":
            native_value = native_national_age_population(native_pep["path"], native_pep["sha256"], year, pop_kind, value)
            if int(value) != native_value:
                raise ValueError("prepared national PEP age-group value differs from pinned native Census age rows")
            note += "; verified from native national Census single-age rows"
        emit("pep_population", field, "01.01", geo, year, usable_value, "persons", quality,
             source_value_status, "census_pep", "Census PEP Vintage 2025", source_url,
             source_item["sha256"], "Census PEP Vintage 2025; population_kind=" + pop_kind +
             "; aggregation=" + note, raw_estimate=value, source_period=str(year),
             retrieved_at=source_item.get("retrievedAt"))

    # EIA 2025 all-sectors state prices.
    eia_item = verified_sources["eia"]
    for row in read_csv(paths["eia"]):
        if row["year"] != "2025" or row["sector"] != "ALL":
            continue
        geo = {"geo_type": geo_type(row), "geo_id": row["geo_id"]}
        quality = "observed" if row["status"] == "observed" and row["value"] else "missing"
        value = number(row["value"], "EIA price") if quality == "observed" else None
        emit("electricity_price", "08.05:sector_ALL", "08.05", geo, 2025, value,
             "cents/kWh", quality, "observed" if quality == "observed" else "missing",
             "eia", "EIA Electric Power Annual 2025", row["source_url"], eia_item["sha256"],
             "EIA 2025 annual retail electricity price; sector ALL; source_status=" + row["status"],
             raw_estimate=row.get("value"), source_period="2025", retrieved_at=eia_item.get("retrievedAt"))

    # IRS SOI total A00100 and derived per-resident values; exact 2023 PEP
    # denominator checks are mandatory for every state/county/nation row.
    irs_item = verified_sources["irs"]
    irs_release = "irs-soi-2023-pep-vintage-2025"
    total_rows = [r for r in read_csv(paths["irs_total"]) if r["year"] == "2023" and r["field"] == "A00100"]
    per_rows = [r for r in read_csv(paths["irs_per_resident"]) if r["year"] == "2023"]
    totals = {(geo_type(r), r["geo_id"]): r for r in total_rows}
    per = {(geo_type(r), r["geo_id"]): r for r in per_rows}
    if set(totals) != set(per):
        raise ValueError("IRS total and per-resident geography sets differ")
    for identity, row in totals.items():
        kind, gid = identity
        geo = {"geo_type": kind, "geo_id": gid}
        per_row = per[identity]
        if Decimal(row["value_usd"]) != Decimal(per_row["income_usd"]):
            raise ValueError("IRS total and per-resident numerator do not match")
        pep = pep_index.get((kind, gid, 2023, "total"))
        if pep is None:
            raise ValueError("matching 2023 PEP total is missing for IRS geography")
        pop = number(pep["value"], "PEP denominator")
        if Decimal(per_row["population"]) != pop:
            raise ValueError("IRS denominator differs from same-year PEP population")
        income = number(row["value_usd"], "IRS income")
        expected = income / pop
        if abs(expected - Decimal(per_row["value"])) > Decimal("0.00000001"):
            raise ValueError("IRS per-resident value does not match numerator/PEP")
        derived_hash = hashlib.sha256((irs_item["sha256"] + ":" + verified_sources["pep_county"]["sha256"]).encode()).hexdigest()
        emit("irs_agi", "07.01:agi_total", "07.01", geo, 2023, income, "USD", "observed", "observed",
             "irs_soi", irs_release, "https://www.irs.gov/statistics/soi-tax-stats-county-data-2023",
             derived_hash, "IRS SOI tax year 2023 A00100 total; value converted from thousand USD to USD; source_release=" + row["source_release"],
             raw_estimate=row["source_value_thousand_usd"], source_period="2023", retrieved_at=irs_item.get("retrievedAt"))
        emit("irs_agi", "07.01:derived:per-resident", "07.01", geo, 2023,
             expected, "USD/person", "observed",
             "observed", "irs_soi", irs_release, "https://www.irs.gov/statistics/soi-tax-stats-county-data-2023",
             derived_hash, "IRS SOI A00100 USD / exact 2023 PEP total population; native US denominator checked against Census SEX=0 AGE=999; source A00100=" + row["value_usd"] + "; PEP=" + pep["value"],
             raw_estimate=row["source_value_thousand_usd"], raw_denominator=pep["value"],
             denominator_value=pop if quality == "observed" else None, source_period="2023",
             retrieved_at=irs_item.get("retrievedAt"))

    # Medical crude rates must use the matching event-year PEP population and
    # the correct population-age denominator. Suppression stays null.
    medical_specs = [
        ("cancer", "cancer", "11.01", 2023, "total", "USCS all-sites 2023 cases"),
        ("hiv", "hiv", "11.02", 2024, "age_13_plus", "provisional HIV diagnoses age 13+"),
        ("child", "child_deaths_under18", "11.03", 2024, "under_18", "resident deaths under age 18"),
    ]
    source_input_hashes = {"cancer":"cancer", "hiv":"hiv", "child":"child"}
    for key, dataset, field, year, pop_kind, numerator_label in medical_specs:
        rows = read_csv(paths[key])
        source_item = verified_sources[key]
        seen_nation = False
        for row in rows:
            if int(row["year"]) != year or row["field_id"] != field:
                raise ValueError("medical event year/field mismatch")
            kind = geo_type(row)
            gid = "US" if kind == "nation" else row["geo_id"]
            geo = {"geo_type":kind,"geo_id":gid}
            source_status = row["status"]
            pep = pep_index.get((kind, gid, year, pop_kind))
            if pep is None:
                raise ValueError("matching same-year PEP population is missing for medical row")
            # National rate readiness is derived from the pinned official row,
            # never inferred from free-text notes in prepared files.
            native_nation_total = True
            if kind == "nation" and pop_kind == "total":
                native_value = native_national_population(native_pep["path"], native_pep["sha256"], year, pep["value"])
                if int(Decimal(pep["value"])) != native_value:
                    raise ValueError("medical PEP denominator differs from native Census national row")
            quality, value, numerator, denominator = validate_medical_rate(
                row, year, pop_kind, pep["value"], native_nation_total)
            suppressed = quality == "suppressed"
            if kind == "nation":
                seen_nation = True
                # Retain a genuine USCS count, but do not expose a rate from a nonnative PEP denominator.
            emit(dataset, field, field, geo, year, value, "per 100,000", quality,
                 "suppressed" if suppressed else "observed", "cdc_uscs" if key == "cancer" else "cdc_atlasplus" if key == "hiv" else "cdc_wonder",
                 row["source_release"], row["source_url"], row["source_input_sha256"],
                 "Crude rate; " + numerator_label + " / matching " + pop_kind + " PEP denominator * 100,000; denominator_year=" + row["denominator_year"] + "; source_adjustment=" + row["source_adjustment"] + "; source_status=" + source_status +
                 ("; native Census SEX=0 AGE=999 denominator verified from pinned source hash" if kind == "nation" and key == "cancer" else ""),
                 raw_estimate=row["numerator"], raw_denominator=row["denominator"],
                 denominator_value=denominator if quality == "observed" else None,
                 source_period=row["source_period"],
                 retrieved_at=row.get("source_retrieved_at") or source_item.get("retrievedAt"))
        if key in ("hiv", "child") and not seen_nation:
            pep = pep_index.get(("nation", "US", year, pop_kind))
            emit(dataset, field, field, {"geo_type":"nation","geo_id":"US"}, year, None,
                 "per 100,000", "missing", "missing", "cdc_atlasplus" if key == "hiv" else "cdc_wonder",
                 rows[0]["source_release"], rows[0]["source_url"], inputs[key]["sha256"],
                 "Prepared source contains state observations only; no national numerator is present. No state sum was substituted.",
                 source_period=str(year), retrieved_at=source_item.get("retrievedAt"))

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "refresh_observations.jsonl"
    seen = set()
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for observation in observations:
            identity = (observation["dataset_id"], observation["field_id"], observation["geo_type"], observation["geo_id"],
                        observation["period_kind"], observation["period_year"], observation["source_release"])
            if identity in seen:
                raise ValueError("duplicate prepared observation grain")
            seen.add(identity)
            stream.write(json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    source_releases = sorted({row["source_release"] for row in observations})
    manifest = {
        "candidate_status":"local_review_not_admitted", "contract_version":CONTRACT_VERSION,
        "collector_version":COLLECTOR_VERSION, "source_release_versions":source_releases,
        "input_results_sha256":trusted_results_sha256, "inputs":inputs,
        "verified_raw_sources":{key:{"sourceId":item["sourceId"],"path":item["path"],"sha256":item["sha256"],"url":item.get("url"),"retrievedAt":item.get("retrievedAt"),"license":item.get("license"),"status":item.get("status")} for key,item in verified_sources.items()},
        "output":{"path":str(output),"sha256":sha256(output),"rows":len(observations)},
        "quality_controls":{"same_event_and_denominator_year":True,"denominator_kind_checked":True,
            "national_cancer_rate":"observed only when same-year prepared denominator matches pinned Census native SEX=0 AGE=999 row",
            "national_irs_per_resident":"observed only when 2023 prepared denominator matches pinned Census native SEX=0 AGE=999 row",
            "national_hiv_and_child":"missing; prepared source rows are state only; no sums substituted",
            "PEP_national_total":"prepared value independently checked against pinned native Census SEX=0 AGE=999 row",
            "native_national_pep":{"sourceId":"census-pep-national-single-age-v2025","sha256":NATIVE_PEP_SHA256,"selector":{"SEX":"0","AGE":"999"},"POPESTIMATE2023":336755052,"POPESTIMATE2024":340003797}},
        "candidate_status_note":"local review preparation only; not admitted or released"
    }
    manifest_path = output_dir / "refresh-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"manifest":str(manifest_path),"rows":len(observations),"source_releases":source_releases},indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-dir", required=True, type=pathlib.Path)
    parser.add_argument("--results-manifest", required=True, type=pathlib.Path)
    parser.add_argument("--trusted-results-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()
    main_prepare(args.prepared_dir, args.results_manifest, args.trusted_results_sha256, args.output_dir)


if __name__ == "__main__":
    main()
