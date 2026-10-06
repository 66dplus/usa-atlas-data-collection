#!/usr/bin/env python3
"""Describe actual coverage, pin source receipts and hash this seed's artifacts."""
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
RAW=ROOT/"raw"
STATES=dict(x.split() for x in "01 AL|02 AK|04 AZ|05 AR|06 CA|08 CO|09 CT|10 DE|11 DC|12 FL|13 GA|15 HI|16 ID|17 IL|18 IN|19 IA|20 KS|21 KY|22 LA|23 ME|24 MD|25 MA|26 MI|27 MN|28 MS|29 MO|30 MT|31 NE|32 NV|33 NH|34 NJ|35 NM|36 NY|37 NC|38 ND|39 OH|40 OK|41 OR|42 PA|44 RI|45 SC|46 SD|47 TN|48 TX|49 UT|50 VT|51 VA|53 WA|54 WV|55 WI|56 WY".split("|"))
with zipfile.ZipFile(RAW/"census-2025-county-gazetteer.zip") as z:
    counties={r["GEOID"]:r for r in csv.DictReader(z.read(z.namelist()[0]).decode().splitlines(),delimiter="|") if r["USPS"] in STATES.values()}
init=json.loads((RAW/"atlas-init.json").read_text())
selected={v["id"]:v for v in init["varvals"] if v.get("vtid")==3 and v.get("geoLevel")==1003 and str(v.get("fips",""))[:2] in STATES}
audit={"created_at":datetime.now(timezone.utc).isoformat(),"reference":"2025 Census Gazetteer","current_target_counties":len(counties),"atlas_selected_county_ids":len(selected),"indicators":[]}
for indicator,kind in [(203,"hiv-diagnoses"),(205,"hiv-diagnosed-prevalence")]:
    returned={};files=[];conflicts=[]
    for file in sorted(RAW.glob("cdc-atlas-"+kind+"-county-2024*.json")):
        obj=json.loads(file.read_text());rows=obj.get("sourcedata",[])
        if rows:files.append(str(file.relative_to(ROOT)))
        for row in rows:
            if row[0]!=indicator or row[1]!=546:continue
            if row[2] in returned and returned[row[2]]!=row:conflicts.append(row[2])
            returned[row[2]]=row
    unreturned=[dict(id=k,name=v["name"],source_geoid=v["fips"]) for k,v in selected.items() if k not in returned]
    source_geos={str(selected[k]["fips"]) for k in returned if k in selected}
    audit["indicators"].append(dict(indicator_id=indicator,metric_family=kind,period="2024",requested_county_ids=len(selected),returned_county_ids=len(returned),unreturned_requested_ids=unreturned,source_suppression_code_counts=dict(Counter(str(r[3]) for r in returned.values())),duplicate_conflicting_geography_ids=sorted(set(conflicts)),unexpected_returned_ids=sorted(set(returned)-set(selected)),returned_current_county_geoids=len(source_geos&set(counties)),returned_source_geoid_not_in_reference=sorted(source_geos-set(counties)),current_counties_without_returned_source_row=sorted(set(counties)-source_geos),source_files=files))
audit["current_counties_absent_from_selected_atlas_metadata"]=sorted(set(counties)-{str(v["fips"]) for v in selected.values()})
(ROOT/"hiv-county-selection-audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n")

obs=json.loads((ROOT/"normalized/observations.json").read_text())["observations"]
rows=[]
for metric in sorted({r["metric_id"] for r in obs}):
    subset=[r for r in obs if r["metric_id"]==metric]
    for fips,abbr in STATES.items():
        state=[r for r in subset if r["geography_level"]=="state" and r["geoid"]==fips]
        county=[r for r in subset if r["geography_level"]=="county" and r["state_code"]==abbr]
        rows.append(dict(metric_id=metric,state_fips=fips,state_code=abbr,periods="|".join(sorted({r["period"] for r in subset})),state_source_rows=len(state),state_numeric_rows=sum(r["value"] is not None for r in state),county_source_rows=len(county),county_numeric_rows=sum(r["value"] is not None for r in county),current_county_numeric_rows=sum(r["value"] is not None and r["geoid"] in counties for r in county),current_census_county_target=sum(g[:2]==fips for g in counties)))
with (ROOT/"state-coverage.csv").open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
(ROOT/"state-coverage.json").write_text(json.dumps({"coverage":rows},ensure_ascii=False,separators=(",",":"))+"\n")

# Enumerate observed identifiers directly from normalized source records. These are
# observed geographies, not targets; absent/suppressed cells are separately listed.
geography_coverage={"as_of":datetime.now(timezone.utc).date().isoformat(),"bundles":{"core":{}}}
for metric in sorted({r["metric_id"] for r in obs}):
    subset=[r for r in obs if r["metric_id"]==metric]
    by_level={}
    for level in ["county","unidentified_county_aggregate","state","national"]:
        selected=[r for r in subset if r["geography_level"]==level]
        if selected:
            layer={
                "source_geoids":sorted({r["source_geoid"] for r in selected}),
                "normalized_geoids":sorted({r["geoid"] for r in selected}),
                "numeric_source_geoids":sorted({r["source_geoid"] for r in selected if r["value"] is not None}),
                "null_source_geoids":sorted({r["source_geoid"] for r in selected if r["value"] is None}),
                "null_reasons":dict(Counter(str(r.get("suppression_reason") or r.get("source_suppression_code") or "source_missing_or_unavailable") for r in selected if r["value"] is None)),
            }
            if level=="county":
                observed={r["source_geoid"] for r in selected}
                normalized={r["geoid"] for r in selected}
                numeric={r["source_geoid"] for r in selected if r["value"] is not None}
                numeric_normalized={r["geoid"] for r in selected if r["value"] is not None}
                layer.update(reference_vintage="2025 Census Gazetteer",
                    observed_2025_reference_geoids=sorted(normalized&set(counties)),
                    numeric_2025_reference_geoids=sorted(numeric_normalized&set(counties)),
                    source_geography_mismatch_geoids=sorted({r["source_geoid"] for r in selected if not str(r.get("geography_compatibility", "")).startswith("matches_2025_census")}),
                    source_territory_county_equivalent_geoids=sorted({r["source_geoid"] for r in selected if r.get("geography_compatibility")=="matches_2025_census_Puerto_Rico_municipio"}),
                    source_to_normalized_geoid_aliases=sorted({(r["source_geoid"],r["geoid"]) for r in selected if r["source_geoid"]!=r["geoid"]}),
                    uncovered_2025_reference_geoids=sorted(set(counties)-normalized))
                if metric=="child_mortality_1_4_derived_county_rate":
                    denominator_geos={r["source_geoid"] for r in selected if r.get("denominator_population") not in (None,"")}
                    layer.update(denominator_source_geography_ids=sorted(denominator_geos),
                        county_death_source_geoids_without_exact_denominator=sorted(observed-denominator_geos),
                        denominator_source_reference="Census PEP Vintage 2025 CC-EST2025-SYASEX; exact source FIPS only",
                        denominator_boundary_vintage="2025-01-01")
            elif level=="unidentified_county_aggregate":
                layer.update(area_type="state_specific_aggregate_not_an_individual_county",
                    source_geography_definition="CDC WONDER FIPS county code 999 within each state",
                    individual_county_assignment_allowed=False)
            elif level=="state":
                observed={r["geoid"] for r in selected}
                numeric={r["geoid"] for r in selected if r["value"] is not None}
                layer.update(reference_jurisdictions="50 states + DC",reference_state_fips=sorted(STATES),
                    observed_reference_state_fips=sorted(observed&set(STATES)),
                    numeric_reference_state_fips=sorted(numeric&set(STATES)),
                    uncovered_reference_state_fips=sorted(set(STATES)-observed),
                    additional_published_source_areas=[{"geoid":geo,"names":sorted({r["geography_name"] for r in selected if r["geoid"]==geo}),
                        "numeric":any(r["geoid"]==geo and r["value"] is not None for r in selected)}
                        for geo in sorted(observed-set(STATES))])
            by_level[level]=layer
        geography_coverage["bundles"]["core"][metric]=by_level
(ROOT/"coverage-geographies.json").write_text(json.dumps(geography_coverage,ensure_ascii=False,separators=(",",":"))+"\n")
core_coverage=json.loads((ROOT/"coverage.json").read_text())
core_coverage["geography_detail_path"]="coverage-geographies.json"
(ROOT/"coverage.json").write_text(json.dumps(core_coverage,ensure_ascii=False,indent=2)+"\n")

register=json.loads((ROOT/"source-register.json").read_text())
latest={}
history={}
for line in (ROOT/"http-receipts.jsonl").read_text().splitlines():
    rec=json.loads(line)
    history.setdefault(rec["name"],[]).append(rec)
    if rec.get("status")=="downloaded":latest[rec["name"]]=rec
register["raw_sources"]=[]
for name,rec in latest.items():
    publisher="NCI/CDC" if name.startswith("nci-") else "US Census Bureau" if name.startswith(("census-","cc-est2025-syasex-")) else "CDC/NCHS" if name.startswith("cdc-wonder-") else "CDC"
    item=dict(source_id=name,publisher=publisher,role="raw_statistical_data_or_primary_metadata",accessed_at=rec["finished_at"],**{k:rec.get(k) for k in ["url","http_status","sha256","bytes","path","method","params","payload","last_modified","etag","content_type","content_disposition"]})
    item["access_attempts"]=[{k:x.get(k) for k in ["started_at","finished_at","url","method","http_status","status","bytes","sha256","error","path"]} for x in history.get(name,[])]
    if name.startswith("nci-") and name.endswith(".csv"):
        data_path=ROOT/rec["path"]
        try:
            content=data_path.read_text(encoding="utf-8-sig").splitlines()
            params=rec.get("params") or {}
            line2=content[2].strip('"') if len(content)>2 else ""
            period=re.search(r"20\d\d\s*[-–]\s*20\d\d",line2)
            table_rows=[]
            for line in content:
                if line.startswith(("County,FIPS","State,FIPS")):
                    start=content.index(line)
                    table_rows=list(csv.reader(content[start+1:]))
                    break
            area= params.get("areatype") or ("state" if "-state." in name else "county")
            observed=sorted({r[1] for r in table_rows if len(r)>1 and re.fullmatch(r"\d{5}",r[1]) and r[1]!="00000" and r[1][:2] in STATES})
            item.update(source_release="live State Cancer Profiles export; retrieved 2026-10-04" if rec["finished_at"].startswith("2026-10-04") else "live State Cancer Profiles export; see accessed_at",
                observation_period=period.group(0).replace(" ","") if period else None,
                population_universe=content[4].strip('"') if len(content)>4 else None,
                source_geography_level=area,source_geographies_observed=len(observed),
                coverage_geographies_artifact="coverage-geographies.json",
                source_measure="mortality" if "mortality" in name else "incidence",
                documentation_urls=["https://statecancerprofiles.cancer.gov/help/about/death_rates.html" if "mortality" in name else "https://statecancerprofiles.cancer.gov/help/about/incidence_rates.html",
                                    "https://www.cdc.gov/united-states-cancer-statistics/technical-notes/index.html"],
                next_collection_step=("Continue CDC/NCHS subnational child-mortality bands ages 1–4 and 5–14; retain mortality release, source age groups and suppression." if "mortality" in name else "Review source-code and pooled-period consistency when extending incidence years."))
        except Exception as exc:
            item["metadata_parse_note"]="Could not parse source table metadata: "+str(exc)
    elif name.startswith("cdc-wonder-linked-infant-mortality-") and name.endswith(".tsv"):
        try:
            data=ROOT/rec["path"]
            table=list(csv.DictReader(data.open(encoding="utf-8-sig"),delimiter="\t"))
            county="-county-" in name
            geoid_field="County Code" if county else "State Code"
            source_ids=sorted({str(r.get(geoid_field) or "") for r in table if r.get(geoid_field)})
            unidentified=sorted(x for x in source_ids if county and x.endswith("999"))
            item.update(source_release="CDC WONDER Linked Birth / Infant Death Records, 2017-2024 Expanded (2024 vintage)",
                observation_period=name.rsplit("-",1)[-1].removesuffix(".tsv"),period_type="period-linked infant deaths by death year",
                population_universe="U.S. resident births and infant deaths by mother's legal residence; 50 states and DC; births to foreign residents excluded",
                source_geography_level="identified_county_plus_state_aggregate" if county else "state",
                source_geographies_observed=len(source_ids),source_geoids=source_ids,
                unidentified_county_aggregate_source_geoids=unidentified,
                coverage_geographies_artifact="coverage-geographies.json",
                definition="Deaths before age one; period-linked numerator by year of death; linked-file live births in the selected year denominator; published rate per 1,000 live births. Death numerator is weighted to compensate for unlinked death records.",
                county_coverage_limit="2017+ county identifiers meet 250,000 population threshold in 2010 Census; smaller counties aggregated under state-specific Unidentified Counties (FIPS 999), not identifiable or distributable.",
                source_suppression="1-9 birth/death cells suppressed; state totals and subtotals can be suppressed; rates with fewer than 20 deaths marked Unreliable.",
                documentation_urls=["https://wonder.cdc.gov/lbd-current-expanded.html","https://wonder.cdc.gov/wonder/help/lbd-expanded.html","https://www.cdc.gov/nchs/nvss/linked-birth.htm","https://www.cdc.gov/nchs/nvss/dvs_data_release.htm","https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Dataset_Documentation/DVS/period-cohort-linked/24PE23CO_linkedUG.pdf"],
                next_collection_step="Retain annual period-linked county outputs and verify source FIPS aliases. Keep unidentified small-county state aggregates separate; compare with the Stats of the States infant series only as a separate source/definition.")
        except Exception as exc:
            item["metadata_parse_note"]="Could not parse linked-infant export metadata: "+str(exc)
    elif name.startswith("cdc-wonder-child-mortality-") and name.endswith(".tsv"):
        item.update(source_release="CDC WONDER Underlying Cause of Death 2018-2024 Single Race (2024 vintage)",
            observation_period="2020-2024 pooled death years",period_type="period of death",
            population_universe="U.S. resident deaths, all causes and age strata selected in query",
            source_geography_level="county" if "county" in name else "state",
            documentation_urls=["https://wonder.cdc.gov/ucd-icd10-expanded.html","https://wonder.cdc.gov/wonder/help/ucd-expanded.html","https://wonder.cdc.gov/whatsnew.html"],
            next_collection_step="Direct county rates are unavailable in the 10-year output. County 1-4 rates are separately derived only where exact FIPS matches the Census PEP Vintage 2025 age denominator; direct state rates and 5-14 derived rates retain their own denominator methods.")
    elif name.startswith("cc-est2025-syasex-") and name.endswith(".csv"):
        try:
            with (ROOT/rec["path"]).open(encoding="utf-8-sig",newline="") as handle:
                data=list(csv.DictReader(handle))
            observed=sorted({str(r.get("STATE", "")).zfill(2)+str(r.get("COUNTY", "")).zfill(3)
                             for r in data if r.get("SUMLEV")=="050" and r.get("AGE") in {"1","2","3","4"}
                             and r.get("YEAR") in {"2","3","4","5","6"}})
            item.update(source_release="U.S. Census Bureau Population Estimates Program County Vintage 2025 CC-EST2025-SYASEX",
                observation_period="2020-2025 annual county resident population estimates; ages 1-4 selected for 2020-2024 denominator",
                population_universe="Total resident population, both sexes, single years of age 1, 2, 3, and 4",
                source_geography_level="county_and_county_equivalent",source_geographies_observed=len(observed),
                source_geoids=observed,boundary_vintage="2025-01-01",
                documentation_urls=["https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-detail.html",
                    "https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2020-2025/CC-EST2025-SYASEX.pdf",
                    "https://wonder.cdc.gov/wonder/help/ucd-expanded.html"],
                next_collection_step="Use these files only for age-specific denominator derivations with exact county FIPS; preserve the January 1, 2025 boundary vintage and do not allocate across changed geographies.")
        except Exception as exc:
            item["metadata_parse_note"]="Could not parse Census PEP geography metadata: "+str(exc)
    elif name.startswith("cdc-wonder-lbd-expanded-"):
        item.update(source_release="CDC WONDER Linked Birth / Infant Death Records, 2017-2024 Expanded request form; 2024 vintage",
            source_type="public request form or landing-page response; not a normalized observation export",
            observation_period="dataset years 2017-2024",
            documentation_urls=["https://wonder.cdc.gov/lbd-current-expanded.html","https://wonder.cdc.gov/wonder/help/lbd-expanded.html"],
            next_collection_step="Use the current published form to fetch annual state and identified-county exports; obey its 2010 Census-based 250,000 county threshold and suppression rules.")
    elif name == "cdc-hiv-estimated-incidence-prevalence-2018-2022.pdf":
        state_excerpt=ROOT/"raw/cdc-hiv-estimated-incidence-2022-state.csv"
        county_excerpt=ROOT/"raw/cdc-hiv-estimated-incidence-2022-ehe-county.csv"
        prevalence_state_excerpt=ROOT/"raw/cdc-hiv-estimated-prevalence-2022-state.csv"
        prevalence_county_excerpt=ROOT/"raw/cdc-hiv-estimated-prevalence-2022-ehe-county.csv"
        state_rows=list(csv.DictReader(state_excerpt.open(encoding="utf-8-sig",newline=""))) if state_excerpt.exists() else []
        county_rows=list(csv.DictReader(county_excerpt.open(encoding="utf-8-sig",newline=""))) if county_excerpt.exists() else []
        prevalence_state_rows=list(csv.DictReader(prevalence_state_excerpt.open(encoding="utf-8-sig",newline=""))) if prevalence_state_excerpt.exists() else []
        prevalence_county_rows=list(csv.DictReader(prevalence_county_excerpt.open(encoding="utf-8-sig",newline=""))) if prevalence_county_excerpt.exists() else []
        item.update(source_release="CDC HIV Surveillance Supplemental Report 2024;29(1), published May 21 2024",
            observation_period="2022 point estimate; report series 2018-2022",
            population_universe="People aged 13 years or older; all sexes/races combined in the selected area tables",
            source_measure="modeled estimated new HIV infections and total estimated HIV prevalence (diagnosed plus undiagnosed), kept distinct from diagnoses and diagnosed prevalence",
            method="CD4-based depletion model; report labels estimates preliminary and based on data reported through December 2023",
            state_source_rows=len(state_rows),state_numeric_estimates=sum(r.get("source_marker")=="numeric" for r in state_rows),
            state_source_geographies=sorted({r.get("source_geoid","") for r in state_rows}),
            county_source_rows=len(county_rows),county_numeric_estimates=sum(r.get("source_marker")=="numeric" for r in county_rows),
            county_source_geographies=sorted({r.get("source_geoid","") for r in county_rows}),
            prevalence_state_source_rows=len(prevalence_state_rows),prevalence_state_numeric_estimates=sum(r.get("source_marker")=="numeric" for r in prevalence_state_rows),
            prevalence_state_source_geographies=sorted({r.get("source_geoid","") for r in prevalence_state_rows}),
            prevalence_county_source_rows=len(prevalence_county_rows),prevalence_county_numeric_estimates=sum(r.get("source_marker")=="numeric" for r in prevalence_county_rows),
            prevalence_county_source_geographies=sorted({r.get("source_geoid","") for r in prevalence_county_rows}),
            county_coverage="selected Ending the HIV Epidemic Phase I counties/municipality only; not national county coverage",
            source_cell_behavior="counts rounded by CDC (nearest 10 when <=1,000, nearest 100 when >1,000); RSE 30%-50% marked with *; estimates with RSE >50% omitted as ellipses and normalized null in incidence tables; the 2022 prevalence table cells collected here are numeric",
            source_geography_boundary_vintage="report does not state a boundary vintage; named source areas preserved and county names crosswalked to 2025 Census Gazetteer FIPS",
            data_extracts=[{"path":"raw/cdc-hiv-estimated-incidence-2022-state.csv","rows":len(state_rows),"numeric_source_estimates":sum(r.get("source_marker")=="numeric" for r in state_rows)},
                           {"path":"raw/cdc-hiv-estimated-incidence-2022-ehe-county.csv","rows":len(county_rows),"numeric_source_estimates":sum(r.get("source_marker")=="numeric" for r in county_rows)},
                           {"path":"raw/cdc-hiv-estimated-prevalence-2022-state.csv","rows":len(prevalence_state_rows),"numeric_source_estimates":sum(r.get("source_marker")=="numeric" for r in prevalence_state_rows)},
                           {"path":"raw/cdc-hiv-estimated-prevalence-2022-ehe-county.csv","rows":len(prevalence_county_rows),"numeric_source_estimates":sum(r.get("source_marker")=="numeric" for r in prevalence_county_rows)}],
            documentation_urls=["https://stacks.cdc.gov/view/cdc/156513/cdc_156513_DS1.pdf",
                "https://www.cdc.gov/hiv-data/nhss/estimated-hiv-incidence-and-prevalence.html",
                "https://www.cdc.gov/hiv-data/nhss/index.html",
                "https://gis.cdc.gov/grasp/nchhstpatlas/tables.html"],
            next_collection_step="The current CDC model-release page still links the 2018-2022 report. AtlasPlus lists the estimated-incidence/prevalence table family, but its static page does not expose a data vintage; verify the live table/API vintage before replacing this release. Keep modeled estimates distinct from diagnoses and diagnosed prevalence.")
    register["raw_sources"].append(item)
successful_datasets={(x.get("url"),(x.get("params") or {}).get("dataset_code")) for x in latest.values()}
successful_urls={x.get("url") or x.get("requested_url") for x in latest.values()}
register["http_error_attempts"]=[]
for line in (ROOT/"http-receipts.jsonl").read_text().splitlines():
    attempt=json.loads(line)
    if attempt.get("status")!="error" and (attempt.get("http_status") or 0)<400:continue
    params=attempt.get("params") or {}
    attempted_url=attempt.get("url") or attempt.get("requested_url")
    recovered=((attempted_url,params.get("dataset_code")) in successful_datasets
               or attempted_url in successful_urls)
    register["http_error_attempts"].append(dict(receipt_name=attempt.get("name"),
        requested_url=attempt.get("requested_url"),method=attempt.get("method"),
        http_status=attempt.get("http_status"),response_bytes=attempt.get("bytes"),
        response_sha256=attempt.get("sha256"),error=attempt.get("error"),
        receipt_detail_file="http-receipts.jsonl",route_recovered_by_later_download=recovered,
        continuation=("This request route subsequently returned successful official exports; retain this failed attempt as resolved request history." if recovered else "Review the exact public route and query payload before another attempt; no data were inferred from this response.")))
register["methodology_sources"].extend([
    {"url":"https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-detail.html","title":"Census County Population by Characteristics 2020-2025; Vintage 2025 single-year age and sex downloads","publisher":"U.S. Census Bureau","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"public_data_route_and_release_documentation"},
    {"url":"https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2020-2025/CC-EST2025-SYASEX.pdf","title":"Census CC-EST2025-SYASEX layout, years/ages, July 1 estimates, PEP methodology, and January 1, 2025 boundary vintage","publisher":"U.S. Census Bureau","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"data_dictionary_and_release_documentation"},
    {"url":"https://wonder.cdc.gov/wonder/help/ucd-expanded.html","title":"CDC WONDER UCD population denominator vintages and unreliable-rate/suppression definitions","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"data_dictionary_and_methodology"},
    {"url":"https://statecancerprofiles.cancer.gov/help/about/death_rates.html","title":"NCI State Cancer Profiles death table: purpose, NVSS source, NCI-modified Census denominators, SEER*Stat rates","publisher":"NCI","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"primary_methodology"},
    {"url":"https://statecancerprofiles.cancer.gov/deathrates/index.php","title":"NCI State Cancer Profiles public death-rate table and export route","publisher":"NCI","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"public_download_route"},
    {"url":"https://seer.cancer.gov/codrecode/icdo3_d2023expanded/index.html","title":"SEER cause-of-death ICD-10 to cancer-site recode dictionary","publisher":"NCI SEER","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"data_dictionary"},
    {"url":"https://seer.cancer.gov/stdpopulations/","title":"SEER standard populations for age adjustment","publisher":"NCI SEER","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"methodology"},
    {"url":"https://seer.cancer.gov/data-software/documentation/seerstat/","title":"SEER*Stat database documentation and variable dictionaries","publisher":"NCI SEER","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"data_dictionary_and_release_documentation"},
    {"url":"https://www.cdc.gov/united-states-cancer-statistics/technical-notes/index.html","title":"CDC USCS current release technical notes and incidence/mortality methods","publisher":"CDC","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"release_documentation"},
    {"url":"https://www.cdc.gov/united-states-cancer-statistics/public-use/about.html","title":"CDC USCS public-use database 2025 submission; diagnosis through 2023; population coverage and 2000 U.S. standard age adjustment","publisher":"CDC","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"release_documentation_and_population_coverage"},
    {"url":"https://www.cdc.gov/united-states-cancer-statistics/public-use/documentation.html","title":"CDC current 2001-2023 U.S. Cancer Statistics data dictionary index; September 2026 page update","publisher":"CDC / NCI","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"data_dictionary_index","access_outcome":"opened_live_official_documentation"},
    {"url":"https://www.cdc.gov/united-states-cancer-statistics/public-use/pdf/uscs-public-use-database-technical-documentation-2001-2023-final-508.pdf","title":"CDC/NCI 2025 submission public-use data dictionary: 2001-2023 diagnosis years, ICD-O-3 variables, population coverage, and fewer-than-16 suppression","publisher":"CDC / NCI","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"data_dictionary_and_release_documentation","access_outcome":"opened_live_official_pdf"},
    {"url":"https://www.cdc.gov/united-states-cancer-statistics/technical-notes/suppression.html","title":"CDC USCS suppression thresholds and Connecticut county-equivalent limitations","publisher":"CDC","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"suppression_and_coverage_methodology"},
    {"url":"https://wonder.cdc.gov/lbd-current-expanded.html","title":"CDC WONDER current Linked Birth / Infant Death Records 2017-2024 Expanded query and public export","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"public_data_request_and_download_route"},
    {"url":"https://wonder.cdc.gov/wonder/help/lbd-expanded.html","title":"CDC WONDER linked-infant release dictionary and methodology: event timing, FIPS, county identification, weights, suppression and reliability","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"data_dictionary_release_documentation_and_suppression_methodology"},
    {"url":"https://www.cdc.gov/nchs/nvss/linked-birth.htm","title":"NCHS linked birth and infant death data: period-linked versus birth-cohort definitions and file availability","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"methodology_and_release_documentation"},
    {"url":"https://www.cdc.gov/nchs/nvss/dvs_data_release.htm","title":"NCHS Vital Statistics data release policy and geographic detail restrictions for linked infant files","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"release_policy_and_geography_availability"},
    {"url":"https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Dataset_Documentation/DVS/period-cohort-linked/24PE23CO_linkedUG.pdf","title":"2024 period / 2023 cohort Linked Birth/Infant Death public-use file user guide","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"release_user_guide_and_dictionary"},
    {"url":"https://wonder.cdc.gov/ucd-icd10-expanded.html","title":"CDC WONDER Underlying Cause of Death, 2018-2024 Single Race query and download route","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"public_data_request_and_download_route"},
    {"url":"https://wonder.cdc.gov/wonder/help/ucd-expanded.html","title":"CDC WONDER UCD data dictionary, populations, suppression and rate reliability methodology","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"data_dictionary_and_methodology"},
    {"url":"https://wonder.cdc.gov/whatsnew.html","title":"CDC WONDER release and dataset update history","publisher":"CDC/NCHS","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"release_documentation"},
    {"url":"https://stacks.cdc.gov/view/cdc/156513/cdc_156513_DS1.pdf","title":"CDC HIV Surveillance Supplemental Report 2024;29(1): modeled incidence and estimated prevalence tables, confidence intervals, RSE and CD4 model notes","publisher":"CDC Division of HIV Prevention","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"primary_data_release_and_methodology"},
    {"url":"https://www.cdc.gov/hiv-data/nhss/estimated-hiv-incidence-and-prevalence.html","title":"CDC current modeled HIV incidence and prevalence release; current report vintage and age universe","publisher":"CDC Division of HIV Prevention","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"current_estimate_release_and_definition"},
    {"url":"https://www.cdc.gov/hiv-data/nhss/index.html","title":"CDC NHSS definitions for diagnoses, diagnosed prevalence, estimated incidence, total estimated prevalence and rate denominators","publisher":"CDC Division of HIV Prevention","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"measure_definitions_and_denominator_methodology"},
    {"url":"https://gis.cdc.gov/grasp/nchhstpatlas/tables.html","title":"CDC AtlasPlus live table route; static page lists estimated HIV incidence/prevalence but does not expose its data vintage; preliminary 2025-2026 diagnosis caveat","publisher":"CDC NCHHSTP","accessed_at":datetime.now(timezone.utc).date().isoformat(),"role":"current_public_route_and_availability_status","access_outcome":"opened_live_official_documentation"},
])
# Repeated audit runs refresh receipts without duplicating documentation rows.
dedup={}
for source in register["methodology_sources"]:
    dedup[(source.get("url"),source.get("role"))]=source
register["methodology_sources"]=list(dedup.values())
register["refreshed_at"]=datetime.now(timezone.utc).isoformat()
(ROOT/"source-register.json").write_text(json.dumps(register,ensure_ascii=False,indent=2)+"\n")

# The separate child-county helper owns its files and manifest. Avoid hashing its active writes.
entries=[]
for path in sorted(ROOT.rglob("*")):
    rel=path.relative_to(ROOT)
    if not path.is_file() or "__pycache__" in rel.parts or "child-county" in rel.parts or path.name=="artifact-manifest.json":continue
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    entries.append(dict(path=str(rel),bytes=path.stat().st_size,sha256=h.hexdigest()))
(ROOT/"artifact-manifest.json").write_text(json.dumps(dict(created_at=datetime.now(timezone.utc).isoformat(),scope="this medical seed; separate child-county support excluded",files=entries),indent=2)+"\n")
print(json.dumps(dict(hiv_audit=[{k:v for k,v in r.items() if k in ["metric_family","requested_county_ids","returned_county_ids","returned_current_county_geoids","current_counties_without_returned_source_row","unreturned_requested_ids"]} for r in audit["indicators"]],raw_sources=len(latest),state_coverage_rows=len(rows),artifact_files=len(entries))))
