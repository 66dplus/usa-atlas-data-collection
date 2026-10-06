#!/usr/bin/env python3
"""Normalize downloaded statistical cells without reconstructing suppressed values."""
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parent
RAW=ROOT/"raw";OUT=ROOT/"normalized";OUT.mkdir(exist_ok=True)
receipts={}
for line in (ROOT/"http-receipts.jsonl").read_text().splitlines():
    r=json.loads(line)
    if r.get("status")=="downloaded":receipts[r["name"]]=r

state_pairs="01 AL|02 AK|04 AZ|05 AR|06 CA|08 CO|09 CT|10 DE|11 DC|12 FL|13 GA|15 HI|16 ID|17 IL|18 IN|19 IA|20 KS|21 KY|22 LA|23 ME|24 MD|25 MA|26 MI|27 MN|28 MS|29 MO|30 MT|31 NE|32 NV|33 NH|34 NJ|35 NM|36 NY|37 NC|38 ND|39 OH|40 OK|41 OR|42 PA|44 RI|45 SC|46 SD|47 TN|48 TX|49 UT|50 VT|51 VA|53 WA|54 WV|55 WI|56 WY"
STATES=dict(x.split() for x in state_pairs.split("|"));USPS={v:k for k,v in STATES.items()}
with zipfile.ZipFile(RAW/"census-2025-county-gazetteer.zip") as z:
    gaz=list(csv.DictReader(z.read(z.namelist()[0]).decode().splitlines(),delimiter="|"))
COUNTIES={r["GEOID"]:r for r in gaz if r["USPS"] in USPS}
ALL_GAZETTEER_GEOS={r["GEOID"]:r for r in gaz}
observations=[];unmatched={};inventory=[]

def number(x):
    if x is None:return None
    s=str(x).strip().replace(",","")
    return float(s) if re.fullmatch(r"-?\d+(?:\.\d+)?",s) else None

def tsv_rows(filename):
    with (RAW/filename).open(encoding="utf-8-sig",newline="") as handle:
        return list(csv.DictReader(handle,delimiter="\t"))

def emit(metric,geo,name,level,period,value,unit,source,**extra):
    r=receipts.get(source,{})
    d=dict(metric_id=metric,geoid=geo,source_geoid=extra.pop("source_geoid",geo),
        geography_name=name,geography_level=level,state_code=STATES.get(geo[:2]) if geo!="US" else None,
        period=period,value=value,unit=unit,value_status="numeric" if value is not None else "missing_or_suppressed",
        source_file="raw/"+source,source_url=r.get("url"),source_sha256=r.get("sha256"),
        accessed_at=(r.get("finished_at", "2026-10-03").split("T")[0]),production_ready=False)
    d.update(extra);observations.append(d)

def geography_status(fips):
    if fips in COUNTIES:return "matches_2025_census_county"
    unmatched[fips]=unmatched.get(fips,0)+1
    if fips.startswith("09"):return "legacy_connecticut_county_not_2025_planning_region"
    return "source_county_or_aggregate_not_matched_to_2025_census"

for file in sorted(RAW.glob("nci-*-*.csv")):
    text=file.read_text(encoding="utf-8-sig");lines=text.splitlines()
    idx=next(i for i,l in enumerate(lines) if l.startswith(("County,FIPS","State,FIPS")))
    reader=csv.reader(lines[idx:]);header=next(reader)
    mortality="mortality" in file.name;level="state" if "-state" in file.name else "county"
    kind=file.name.replace("nci-incidence-","").replace("nci-mortality-","").rsplit("-",1)[0]
    rate_index=next(i for i,h in enumerate(header) if h.startswith("Age-Adjusted"))
    count_index=header.index("Average Annual Count")
    period=re.search(r"(20\d\d)-(20\d\d)",lines[2]).group(0)
    group=lines[4].strip('"')
    receipt=receipts.get(file.name,{})
    source_params=receipt.get("params") or {}
    sex_code=source_params.get("sex")
    sex_label={"0":"Both Sexes","1":"Male","2":"Female"}.get(str(sex_code),group)
    rate_column=header[rate_index]
    for row in reader:
        if len(row)<len(header) or not re.fullmatch(r"\d{5}",row[1]):continue
        raw_fips=row[1]
        if raw_fips!="00000" and raw_fips[:2] not in STATES:continue # PR outside target universe
        name=re.sub(r"\(\d+\)$","",row[0]);geo="US" if raw_fips=="00000" else raw_fips[:2] if level=="state" else raw_fips
        geo_level="national" if geo=="US" else level
        compatible=geography_status(geo) if geo_level=="county" else "state_or_national"
        base="cancer_"+("mortality_" if mortality else "incidence_")+kind
        rate_text=row[rate_index].strip();count_text=row[count_index].strip()
        value=number(rate_text);suppressed=value is None and "*" in rate_text
        bounded_count="fewer" in count_text.lower()
        site_code=source_params.get("cancer")
        selector_names={"001":"all_sites","047":"lung_bronchus","055":"breast_female",
                        "020":"colorectal","066":"prostate_male","053":"melanoma",
                        "040":"pancreas","035":"liver_intrahepatic_bile_duct"}
        mortality_icd10={"lung":"C340-C343; C348-C349",
                         "breast_female":"C500-C506; C508-C509",
                         "colorectal":"C180; C182-C189; C19; C20",
                         "prostate_male":"C61",
                         "melanoma":"C430-C439"}
        metadata=dict(source_geoid=raw_fips,universe=group,
            age_adjustment="2000_US_standard_population",geography_compatibility=compatible,
            lower_95_ci=number(row[rate_index+1]),upper_95_ci=number(row[rate_index+2]),
            suppression_reason="fewer_than_16_records_or_source_withheld" if suppressed else None,
            source_value_text=rate_text,source_rate_column=rate_column,
            source_cancer_selector_code=site_code,cancer_site=selector_names.get(str(site_code),kind),
            source_sex_selector_code=sex_code,population_sex=sex_label,
            age_universe="All Ages",race_ethnicity="All Races (includes Hispanic)",
            period_method="pooled_five_year_average_annual_rate",
            denominator="NCI_modified_Census_population; sex-specific where selected",
            source_suppression_flag="*" if suppressed else None,
            source_rate_status="suppressed" if suppressed else "numeric" if value is not None else "source_blank_or_unavailable")
        if mortality and kind in mortality_icd10:
            metadata["mortality_icd10_underlying_cause_codes"]=mortality_icd10[kind]
        emit(base+"_rate",geo,name,geo_level,period,value,"age_adjusted_"+("deaths" if mortality else "new_cases")+"_per_100000_per_year",file.name,**metadata)
        count=number(row[count_index])
        emit(base+"_average_annual_count",geo,name,geo_level,period,count,"average_annual_"+("deaths" if mortality else "new_cases"),file.name,
            source_geoid=raw_fips,universe=group,age_adjustment="not_applied_to_count",geography_compatibility=compatible,
            suppression_reason="fewer_than_16_records_bounded_as_3_or_fewer" if bounded_count else "source_count_withheld" if count is None else None,
            source_value_text=count_text,source_suppression_flag="3_or_fewer" if bounded_count else None,
            source_count_status="bounded_suppressed" if bounded_count else "numeric" if count is not None else "source_blank_or_unavailable",
            source_cancer_selector_code=site_code,cancer_site=selector_names.get(str(site_code),kind),
            source_sex_selector_code=sex_code,population_sex=sex_label,age_universe="All Ages",
            race_ethnicity="All Races (includes Hispanic)",period_method="pooled_five_year_average_annual_count",
            rounding="publisher_rounded_average; do_not_multiply_by_5_for_exact_cases")

init=json.loads((RAW/"atlas-init.json").read_text());values={v["id"]:v for v in init["varvals"]}
atlas_codes={203:"hiv_diagnoses",205:"hiv_diagnosed_prevalence",210:"hepatitis_a_reported_cases",211:"hepatitis_b_acute_reported_cases",212:"hepatitis_c_acute_reported_cases"}
for file in sorted(RAW.glob("cdc-atlas-*.json")):
    j=json.loads(file.read_text())
    if not isinstance(j,dict) or "sourcedata" not in j:continue
    for row in j["sourcedata"]:
        if row[0] not in atlas_codes:continue
        v=values[row[2]];source_geo=str(v.get("fips",""))
        if source_geo[:2] not in STATES:continue
        level="county" if v.get("geoLevel")==1003 else "state"
        geo=source_geo if level=="county" else source_geo[:2]
        status=int(row[3]);period=values[row[1]]["name"]
        compatible=geography_status(geo) if level=="county" else "state"
        common=dict(source_geoid=source_geo,geography_compatibility=compatible,source_suppression_code=status,
            age_group=values[row[6]]["name"],sex=values[row[5]]["name"],race_ethnicity=values[row[4]]["name"],
            transmission_category=values[row[7]]["name"],denominator_population=number(row[10]),
            age_adjustment="crude_age_group_specific_not_age_adjusted",preliminary=period in ["2025","2026"] or (row[0]==205 and period=="2024"),
            universe="persons_13_plus_with_diagnosed_HIV" if row[0] in [203,205] else "reported_surveillance_cases_all_ages")
        for index,suffix,unit in [(9,"count","persons_diagnosed" if row[0] in [203,205] else "reported_cases"),(8,"rate","per_100000_population")]:
            suppressed=status in ({401,405,406,412} if index==9 else {403,405,407,412})
            unavailable=status in ({402,407,408,413} if index==9 else {404,406,408,413})
            value=None if suppressed or unavailable else number(row[index])
            if status==414 and index==9:value=0.0 # public source explicitly says No reported cases
            emit(atlas_codes[row[0]]+"_"+suffix,geo,v["name"],level,period,value,unit,file.name,**common,
                suppression_reason="source_confidentiality_suppression" if suppressed else "source_not_available" if unavailable else None,
                source_value_text=str(row[index]),source_reporting_note="2024 diagnosed prevalence uses preliminary death data received through December2025; diagnoses are not estimated infection incidence; residence for prevalence is latest known address" if row[0] in [203,205] else "Registered surveillance cases; hepatitisB/C are acute, not chronic infection prevalence; AtlasPlus selected release2023")

infant=json.loads((RAW/"infant-visualization-config.json").read_text())
for row in infant["data"]:
    if str(row.get("YEAR"))!="2024":continue
    abbr="DC" if row["STATE"]=="District of Columbia" else row["STATE"]
    if abbr not in USPS:continue
    geo=USPS[abbr]
    for field,metric,unit in [("DEATHS","infant_mortality_under1_deaths","deaths_under_age_1"),("RATE","infant_mortality_under1_rate","deaths_under_age_1_per_1000_live_births")]:
        emit(metric,geo,abbr,"state","2024",number(row[field]),unit,"infant-visualization-config.json",
            age_group="under_1_year",age_adjustment="not_age_adjusted_infant_livebirth_rate",denominator="live_births; exact birth count not supplied in this extract",
            universe="NVSS resident infant deaths; Stats of States mortality series, not assumed linked-file series",
            source_reporting_note="generic age-adjustment boilerplate on page does not override the infant-specific per1000-livebirth definition")

# Period-linked CDC WONDER exports retain a different event-time definition from
# the Stats of the States 2024 visualization above. State/year files contain all
# states and DC. Identified county rows use the 250k/2010-census public boundary;
# composite *999 rows are state aggregates for unidentified counties.
def infant_cell(raw,rate=False):
    text="" if raw is None else str(raw).strip()
    unreliable=bool(rate and "unreliable" in text.lower())
    if text.lower()=="suppressed":return None,"source_suppressed",False
    match=re.fullmatch(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:\(Unreliable\))?",text,re.I)
    if match:
        value=number(match.group(1))
        return value,"source_unreliable_rate" if unreliable else "published_zero" if value==0 else "numeric",unreliable
    if text.lower()=="not available":return None,"source_not_available",False
    if text.lower()=="not applicable":return None,"source_not_applicable",False
    return None,"source_blank" if not text else "source_nonnumeric_marker",False

for year in range(2020,2025):
    for level in ("state","county"):
        filename=f"cdc-wonder-linked-infant-mortality-{level}-{year}.tsv"
        for row in tsv_rows(filename):
            idfield="State Code" if level=="state" else "County Code"
            source_geo=str(row.get(idfield) or "").strip()
            if level=="state":
                if source_geo not in STATES:continue
                geo=source_geo;geo_level="state";name=str(row.get("State") or STATES[geo])
                compatibility="state_or_national"
            else:
                if not re.fullmatch(r"\d{5}",source_geo) or source_geo[:2] not in STATES:continue
                name=str(row.get("County") or "")
                if source_geo[2:]=="999":
                    geo=source_geo;geo_level="unidentified_county_aggregate"
                    compatibility="state_aggregate_unidentified_counties_not_a_county"
                elif source_geo=="12025":
                    geo="12086";geo_level="county";name="Miami-Dade County, FL"
                    compatibility="documented_same_area_alias_Dade_12025_to_Miami-Dade_12086"
                else:
                    geo=source_geo;geo_level="county";compatibility=geography_status(geo)
            common=dict(source_geoid=source_geo,source_release="Linked Birth / Infant Death Records, 2017-2024 Expanded",
                observation_year=str(year),period_kind="period_linked_death_year",age_group="under_1_year",
                age_min=0,age_max_exclusive=1,sex="all",race_ethnicity="all",
                source_population="U.S. resident live births and infant deaths; maternal legal residence; 50 States and DC",
                birth_geography="mother_legal_residence_at_birth",death_geography="mother_legal_residence_linked_birth_record",
                geography_compatibility=compatibility,county_identification_threshold=250000,
                county_identification_population_vintage="2010 Census for 2017+ data years",
                no_county_identification_status="counties_below_threshold_aggregated_as_Unidentified_Counties_per_state",
                source_reporting_note="Period-linked file: numerator includes infant deaths occurring in the selected death year linked to birth certificates, whether birth occurred in that year or prior year; denominator is all linked-file births in the selected year. Death counts are weighted to compensate for unlinked infant deaths and may not exactly sum because of rounding. Counties below the source's 250,000-population threshold in the 2010 Census are combined in state-specific Unidentified Counties; they are not assignable to individual counties. Events to foreign residents are excluded.")
            for rawfield,metric_suffix,unit,is_rate in (
                ("Deaths","deaths","deaths_under_age_1",False),
                ("Births","live_births","live_births",False),
                ("Death Rate","rate","deaths_under_age_1_per_1000_live_births",True)):
                value,status,unreliable=infant_cell(row.get(rawfield),rate=is_rate)
                metric=f"infant_mortality_under1_period_linked_{metric_suffix}"
                extra=dict(source_value_text=row.get(rawfield),source_value_status=status,
                    suppression_reason="CDC WONDER source cell suppressed; 1-9 births or deaths are not published" if status=="source_suppressed" else None,
                    source_suppression_flag="Suppressed" if status=="source_suppressed" else None,
                    source_rate_status=status if is_rate else None,
                    rate_unreliable=unreliable if is_rate else None,
                    unreliability_reason="CDC marks infant rate unreliable when fewer than 20 deaths contribute" if unreliable else None,
                    source_denominator="linked-file live births in selected year; source Births field" if is_rate else None,
                    denominator_count=infant_cell(row.get("Births"))[0] if is_rate else None,
                    rate_denominator_unit="live_births" if is_rate else None,
                    rate_scale=1000 if is_rate else None,
                    confidence_interval="not supplied in selected official tabulation" if is_rate else None,
                    source_zero_flag=(value==0) if value is not None else False)
                emit(metric,geo,name,geo_level,str(year),value,unit,filename,**common,**extra)

class TextParser(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,d):self.parts.append(d)
t=TextParser();t.feed((RAW/"cdc-child-health-final-2024.html").read_text());text=" ".join(t.parts)
for lo,hi in [(1,4),(5,14)]:
    m=re.search(r"Children ages "+str(lo)+r"[–-]"+str(hi)+r" years\s+Number of deaths:\s*([\d,]+)\s+Deaths per 100,000 population:\s*([\d.]+)",text)
    if m:
        for value,suffix,unit in [(number(m[1]),"count","deaths"),(number(m[2]),"rate","deaths_per_100000_age_group_population")]:
            emit("child_mortality_"+str(lo)+"_"+str(hi)+"_"+suffix,"US","United States","national","2024",value,unit,"cdc-child-health-final-2024.html",
                 age_group=str(lo)+"-"+str(hi),age_adjustment="age_group_specific_crude",universe="NVSS resident all-cause deaths",denominator="same_age_group_population")

# CDC's currently linked modeled-incidence release is a statistical report,
# separate from diagnosis surveillance.  The public PDF is retained as raw
# evidence; these compact source-cell extracts preserve its reported text and
# are transcribed from Table 6 (state/jurisdiction) and Table A1 (selected EHE
# counties), 2022. Ellipses are unavailable high-RSE estimates, never zero.
hiv_estimate_specs = [
    ("cdc-hiv-estimated-incidence-2022-state.csv", "Table 6"),
    ("cdc-hiv-estimated-incidence-2022-ehe-county.csv", "Table A1"),
    ("cdc-hiv-estimated-prevalence-2022-state.csv", "Table 13"),
    ("cdc-hiv-estimated-prevalence-2022-ehe-county.csv", "Table A2"),
]
hiv_estimate_pdf = "cdc-hiv-estimated-incidence-prevalence-2018-2022.pdf"
hiv_estimate_receipt = receipts.get(hiv_estimate_pdf, {})
hiv_estimate_pdf_sha = hiv_estimate_receipt.get("sha256")
hiv_estimate_url = hiv_estimate_receipt.get("url") or "https://stacks.cdc.gov/view/cdc/156513/cdc_156513_DS1.pdf"
for excerpt_name, expected_table in hiv_estimate_specs:
    excerpt_path = RAW / excerpt_name
    if not excerpt_path.exists():
        continue
    excerpt_sha = hashlib.sha256(excerpt_path.read_bytes()).hexdigest()
    with excerpt_path.open(encoding="utf-8-sig", newline="") as source_handle:
        for row in csv.DictReader(source_handle):
            if row.get("table") != expected_table or row.get("observation_year") != "2022":
                continue
            geo = row["source_geoid"].zfill(5 if row["geography_level"] == "county" else 2)
            level = row["geography_level"]
            status = row.get("source_marker") or "source_blank"
            estimate = number(row.get("estimate_text"))
            count_ci = (number(row.get("count_ci_lower_text")), number(row.get("count_ci_upper_text")))
            rate_ci = (number(row.get("rate_ci_lower_text")), number(row.get("rate_ci_upper_text")))
            raw_rse = (row.get("rse_text") or "").strip()
            starred = raw_rse.startswith("*")
            rse = number(raw_rse.lstrip("*"))
            compatibility = ("matches_2025_census_county" if geo in COUNTIES else
                             "matches_2025_census_Puerto_Rico_municipio" if geo in ALL_GAZETTEER_GEOS and row["state_code"] == "PR" else
                             "source_FIPS_not_in_2025_Census_Gazetteer") if level == "county" else "source_state_or_territory_FIPS"
            is_prevalence = expected_table in ("Table 13", "Table A2")
            metric_root = "hiv_prevalence_estimated_" if is_prevalence else "hiv_incidence_estimated_"
            if status == "numeric" and estimate is None:
                raise ValueError(f"Expected published numeric estimate in {excerpt_name}: {row}")
            shared = dict(
                source_area_name=row["geography_name"],
                source_table=expected_table, source_report_page=row["report_page"],
                source_release="CDC HIV Surveillance Supplemental Report 2024;29(1)",
                source_pdf_file="raw/" + hiv_estimate_pdf,
                source_pdf_sha256=hiv_estimate_pdf_sha,
                source_excerpt_file="raw/" + excerpt_name,
                source_excerpt_sha256=excerpt_sha,
                source_observation_marker=status,
                source_value_status="numeric" if status == "numeric" else "source_not_displayed_high_rse",
                source_withholding_reason="CDC does not display estimates with RSE >50%; ellipsis is not a zero" if estimate is None else None,
                source_suppression_flag=None, rate_unreliable=None,
                age_group="13_plus", age_min=13, age_max=None,
                sex="all_sexes_not_stratified_in_this_table",
                race_ethnicity="all_races_ethnicities_not_stratified_in_this_table",
                source_population="Persons aged 13 years or older; HIV surveillance reports to CDC",
                residence_definition=("most recent known address at end of the specified year" if is_prevalence else
                                      "area of residence at diagnosis"),
                estimation_status="modeled_estimate",
                estimation_method="CD4-based depletion model using HIV surveillance data",
                preliminary=is_prevalence,
                reporting_cutoff="CDC reported data through December 2023; report labels estimates preliminary",
                covid_adjustment_caution="2022 estimate adjusted for COVID-19-related diagnosis delay; CDC says interpret with caution",
                jurisdiction_reporting_caution=(
                    "incomplete laboratory reporting in Puerto Rico" if row["state_code"] == "PR" else
                    "jurisdiction lacks law requiring complete laboratory reporting" if row["state_code"] == "ID" else
                    "incomplete laboratory reporting" if row["state_code"] == "NJ" else
                    "incomplete ascertainment of deaths reported for 2022" if is_prevalence and row["state_code"] in ("MS", "SC", "UT") else None),
                rse_percent=rse,
                rse_caution_flag="RSE_30_to_50_percent" if starred else None,
                source_rse_text=raw_rse or None,
                age_adjustment="not_age_adjusted; age_universe_13_plus",
                denominator_population=None,
                denominator_source="U.S. Census Bureau Vintage 2022 postcensal population estimates file (CDC HIV Surveillance Supplemental Report Technical Notes B3)",
                denominator_definition="CDC rate denominator: population aged 13 years or older in the specified area/year; exact denominator count is not published in these table cells",
                rate_denominator_unit="population_age_13_plus",
                denominator_year="2022", rate_scale=100000,
                geography_compatibility=compatibility,
                source_boundary_vintage="not stated in the report; source area name and FIPS retained",
                crosswalk_reference_boundary_vintage="2025 Census Gazetteer",
                fips_crosswalk="Official FIPS crosswalked from source area name and state to 2025 Census Gazetteer; source table itself publishes names",
                county_coverage_note=("Table A2 covers selected Ending the HIV Epidemic Phase I jurisdictions only; not a complete county series" if is_prevalence and level == "county" else
                                      "Table A1 covers selected Ending the HIV Epidemic Phase I jurisdictions only; not a complete county series" if level == "county" else
                                      "Table 13 publishes state/DC and Puerto Rico; other territories and freely associated states are not included" if is_prevalence else
                                      "Table 6 publishes state/DC and Puerto Rico; other territories and freely associated states are not included"),
                comparability_note=("Modeled estimated total HIV prevalence (diagnosed plus undiagnosed), with rounded counts; rates use age-13-plus area population and must remain distinct from reported diagnosed prevalence" if is_prevalence else
                                    "Modeled estimates with rounded counts; rates use age-13-plus area population and are not directly comparable to diagnosed HIV counts or diagnosed prevalence"),
                source_count_rounding="Nearest 10 for estimates <=1,000; nearest 100 for estimates >1,000",
            )
            for suffix, value, unit, ci, raw_text in (
                ("count", estimate,
                 "estimated_persons_living_with_diagnosed_or_undiagnosed_hiv" if is_prevalence else "estimated_new_infections",
                 count_ci, row.get("estimate_text")),
                ("rate", number(row.get("rate_text")),
                 "estimated_persons_living_with_diagnosed_or_undiagnosed_hiv_per_100000_population_age_13_plus" if is_prevalence else "estimated_new_infections_per_100000_population_age_13_plus",
                 rate_ci, row.get("rate_text")),
            ):
                metric = metric_root + suffix
                obs = dict(
                    metric_id=metric, geoid=geo, source_geoid=geo,
                    geography_name=row["geography_name"], geography_level=level,
                    state_code=row["state_code"], period="2022", value=value, unit=unit,
                    value_status="numeric" if value is not None else "missing_or_suppressed",
                    source_file="raw/" + excerpt_name, source_url=hiv_estimate_url,
                    source_sha256=hiv_estimate_pdf_sha,
                    accessed_at=hiv_estimate_receipt.get("finished_at", "2026-10-04").split("T")[0],
                    production_ready=False,
                    source_value_text=raw_text,
                    lower_95_ci=ci[0], upper_95_ci=ci[1],
                    **shared,
                )
                observations.append(obs)

# CDC WONDER final underlying-cause-of-death export. Keep the directly published
# age-band counts, state rates, county rate limitations, and any derived county
# 5-14 rates as separate measures.
def cell_value(raw):
    value=number(raw)
    if value is not None:return value,"numeric"
    text="" if raw is None else str(raw).strip()
    if text.lower()=="suppressed":return None,"source_suppressed"
    if text.lower()=="unreliable":return None,"source_unreliable_rate"
    if text.lower()=="not applicable":return None,"source_not_applicable"
    if text.lower()=="not available":return None,"source_not_available"
    if not text:return None,"source_blank"
    return None,"source_nonnumeric_marker"

def source_meta(filename):
    return receipts.get(filename,{})

def wonder_common(source,geo,name,level,age,**extra):
    compatibility=geography_status(geo) if level=="county" else "state"
    return dict(source_geoid=geo,age_group=age,age_min="1" if age=="1-4" else "5",
        age_max="4" if age=="1-4" else "14",sex="both",race_ethnicity="all",
        age_adjustment="age_specific_crude_not_age_adjusted",
        universe="Observed all-cause registered deaths among U.S. residents; county of residence",
        geography_compatibility=compatibility,period_kind="pooled_years_of_death",
        period_method="2020-2024 death-year total; denominator sums annual age-specific resident population across the five years",
        **extra)

state_wonder="cdc-wonder-child-mortality-state-2020-2024.tsv"
county_wonder="cdc-wonder-child-mortality-county-2020-2024.tsv"
county_5y_wonder="cdc-wonder-child-mortality-county-5year-2020-2024.tsv"
state_by_age={}
for row in tsv_rows(state_wonder):
    fips=str(row.get("State Code") or "")
    age=str(row.get("Ten-Year Age Groups Code") or "")
    if fips not in STATES or age not in ("1-4","5-14"):continue
    state_by_age[(fips,age)]=row
    for source_field,metric_suffix,unit in [("Deaths","count","deaths_in_period"),("Crude Rate","rate","deaths_per_100000_age_group_population_per_year")]:
        value,status=cell_value(row.get(source_field))
        metric="child_mortality_"+age.replace("-","_")+"_"+metric_suffix
        emit(metric,fips,STATES[fips],"state","2020-2024",value,unit,state_wonder,
            **wonder_common(state_wonder,fips,STATES[fips],"state",age,
                denominator_population=number(row.get("Population")),denominator_unit="summed_age_group_population_person_years",
                lower_95_ci=number(row.get("Crude Rate Lower 95% Confidence Interval")) if metric_suffix=="rate" else None,
                upper_95_ci=number(row.get("Crude Rate Upper 95% Confidence Interval")) if metric_suffix=="rate" else None,
                source_value_text=row.get(source_field),source_value_status=status,
                suppression_reason="CDC WONDER source cell suppressed or unavailable" if value is None else None,
                source_reporting_note="Underlying cause of death; state of decedent residence; observed final NVSS deaths; 2024 final D158 export; age-specific crude rates per 100,000 person-years."))

county_by_age={}
for row in tsv_rows(county_wonder):
    fips=str(row.get("County Code") or "")
    age=str(row.get("Ten-Year Age Groups Code") or "")
    if not re.fullmatch(r"\d{5}",fips) or fips[:2] not in STATES or age not in ("1-4","5-14"):continue
    county_by_age[(fips,age)]=row
    value,status=cell_value(row.get("Deaths"))
    metric="child_mortality_"+age.replace("-","_")+"_count"
    county_name=str(row.get("County") or "")
    emit(metric,fips,county_name,"county","2020-2024",value,"deaths_in_period",county_wonder,
        **wonder_common(county_wonder,fips,county_name,"county",age,
            denominator_population=None,denominator_unit="not_supplied_for_10_year_county_table",
            source_value_text=row.get("Deaths"),source_value_status=status,
            source_suppression_flag="Suppressed" if status=="source_suppressed" else None,
            suppression_reason="CDC WONDER privacy suppression: fewer than 10 deaths" if status=="source_suppressed" else None,
            source_reporting_note="Directly published pooled count; no county rate or population is supplied for these 10-year-age-group county outputs."))

county_5y={}
for row in tsv_rows(county_5y_wonder):
    fips=str(row.get("County Code") or "")
    age=str(row.get("Five-Year Age Groups Code") or "")
    if not re.fullmatch(r"\d{5}",fips) or fips[:2] not in STATES or age not in ("1-4","5-9","10-14"):continue
    county_5y[(fips,age)]=row

# Explicit county-rate records: age 1-4 denominator/rates are not available in
# this public county source; 5-14 is not a published county rate row in D158.
for (fips,age),count_row in county_by_age.items():
    county_name=str(count_row.get("County") or "")
    if age=="1-4":
        direct=county_5y.get((fips,"1-4"),{})
        raw_rate=direct.get("Crude Rate")
        value,status=cell_value(raw_rate)
        reason="CDC WONDER reports county 1-4 counts, but the age-group population denominator and rate are Not Applicable/not available at county level."
        rate_source=county_5y_wonder
    else:
        raw_rate=""
        value,status=None,"source_not_available"
        reason="CDC WONDER returns county 5-14 death counts but not population or rates for 10-year age groups at county level."
        rate_source=county_wonder
    emit("child_mortality_"+age.replace("-","_")+"_rate",fips,county_name,"county","2020-2024",value,
        "deaths_per_100000_age_group_population_per_year",rate_source,
        **wonder_common(rate_source,fips,county_name,"county",age,
            denominator_population=number(county_5y.get((fips,"1-4"),{}).get("Population")) if age=="1-4" else None,
            denominator_unit="summed_age_group_population_person_years" if age=="1-4" else "not_supplied_for_10_year_county_table",
            lower_95_ci=number(direct.get("Crude Rate Lower 95% Confidence Interval")) if age=="1-4" else None,
            upper_95_ci=number(direct.get("Crude Rate Upper 95% Confidence Interval")) if age=="1-4" else None,
            source_value_text=raw_rate,source_value_status=status,suppression_reason=reason,
            source_reporting_note=reason))

# Separate transparent county 5-14 derivation: use the directly published 5-14
# count plus the two published 5-year population denominators. Do not sum or infer
# death counts from the 5-9/10-14 rows; any suppressed direct 5-14 count stays null.
secondary=source_meta(county_5y_wonder)
for (fips,age),count_row in county_by_age.items():
    if age!="5-14":continue
    county_name=str(count_row.get("County") or "")
    deaths,status=cell_value(count_row.get("Deaths"))
    lower=county_5y.get((fips,"5-9"),{});upper=county_5y.get((fips,"10-14"),{})
    pop_lower,pop_lower_status=cell_value(lower.get("Population"))
    pop_upper,pop_upper_status=cell_value(upper.get("Population"))
    denominator=(pop_lower+pop_upper) if pop_lower is not None and pop_upper is not None else None
    value=(deaths/denominator*100000.0) if deaths is not None and denominator and denominator>0 else None
    if status=="source_suppressed":
        reason="Direct CDC WONDER 5-14 death count is suppressed (<10); derived county rate remains null."
    elif denominator is None:
        reason="The direct 5-14 death count is visible, but at least one five-year population denominator is unavailable."
    else:reason=None
    emit("child_mortality_5_14_derived_county_rate",fips,county_name,"county","2020-2024",value,
        "derived_deaths_per_100000_age_group_population_per_year",county_wonder,
        **wonder_common(county_wonder,fips,county_name,"county","5-14",
            denominator_population=denominator,denominator_unit="sum_of_5-9_and_10-14_population_person_years",
            numerator=deaths,numerator_source_file="raw/"+county_wonder,
            numerator_source_sha256=source_meta(county_wonder).get("sha256"),
            denominator_source_file="raw/"+county_5y_wonder,
            denominator_source_sha256=secondary.get("sha256"),
            source_value_text="" if value is None else format(value,".12g"),
            source_value_status="source_suppressed" if status=="source_suppressed" else "source_denominator_unavailable" if denominator is None else "derived_numeric",
            source_suppression_flag="Suppressed" if status=="source_suppressed" else None,
            suppression_reason=reason,estimation_status="derived_from_direct_5-14_count_and_published_5-9_plus_10-14_population_denominators",
            source_reporting_note="Derived county crude rate, not a rate published for the 5-14 county cross-tab. Numerator is the directly published 5-14 count. Denominator sums published 5-9 and 10-14 person-year populations; no suppressed subgroup counts are summed or reconstructed. CDC WONDER crude-rate formula count/population*100,000."))

# Separate 1-4 county-rate derivation. WONDER does not publish the county
# population denominator for ages 1-4; use public Census PEP single-year ages
# 1, 2, 3, and 4 only where source FIPS match exactly. This is not a
# CDC-published rate and is not mixed into the direct state-rate series.
pep_file=ROOT/"child-age-bands"/"census-pep-2025-age1-4-population.csv"
pep_by_key={}
if pep_file.exists():
    with pep_file.open(encoding="utf-8-sig",newline="") as handle:
        for row in csv.DictReader(handle):
            key=(row["geoid"],int(row["year"]),int(row["age"]))
            if key in pep_by_key:raise ValueError(f"duplicate Census PEP denominator key {key}")
            pep_by_key[key]=row
    for (fips,age),count_row in county_by_age.items():
        if age!="1-4":continue
        county_name=str(count_row.get("County") or "")
        deaths,count_status=cell_value(count_row.get("Deaths"))
        selected=[pep_by_key.get((fips,year,single_age)) for year in range(2020,2025) for single_age in range(1,5)]
        # A missing FIPS or incomplete age/year grid is unavailable geography,
        # not a population zero and never a cue to crosswalk or allocate.
        denominator=(sum(int(row["population"]) for row in selected)
                     if all(row and row.get("population") not in (None,"") for row in selected) else None)
        source_row=selected[0] if selected and selected[0] else None
        value=(deaths/denominator*100000.0
               if deaths is not None and denominator is not None and denominator>0 else None)
        if count_status=="source_suppressed":
            reason="Direct CDC WONDER 1-4 death count is suppressed (<10); derived county rate remains null."
        elif denominator is None:
            reason="Census PEP Vintage 2025 has no exact matching county FIPS and complete age/year denominator; no county crosswalk or allocation was applied."
        else:
            reason=None
        unreliable=deaths is not None and 0<deaths<20
        emit("child_mortality_1_4_derived_county_rate",fips,county_name,"county","2020-2024",value,
            "derived_deaths_per_100000_age_group_population_per_year",county_wonder,
            **wonder_common(county_wonder,fips,county_name,"county","1-4",
                numerator=deaths,numerator_source_file="raw/"+county_wonder,
                numerator_source_sha256=source_meta(county_wonder).get("sha256"),
                denominator_population=denominator,denominator_count=denominator,
                denominator_unit="sum_of_20_annual_single_year_population_estimates_person_years",
                denominator_definition="Sum of July 1 population estimates for ages 1, 2, 3, and 4 for each year 2020-2024 (20 cells).",
                denominator_source="U.S. Census Bureau Population Estimates Program (PEP), County Vintage 2025",
                denominator_source_release="CC-EST2025-SYASEX; released June 2026",
                denominator_source_file=source_row["source_file"] if source_row else None,
                denominator_source_sha256=source_row["source_sha256"] if source_row else None,
                denominator_source_url=source_row["source_url"] if source_row else None,
                denominator_population_vintage="Census PEP Vintage 2025; county-equivalent boundaries as of January 1, 2025",
                denominator_year="2020-2024",lower_95_ci=None,upper_95_ci=None,
                source_rate_column="derived from direct death count / Census age-specific person-years * 100000",
                source_value_text="" if value is None else format(value,".12g"),
                source_value_status="source_suppressed" if count_status=="source_suppressed" else "source_denominator_unavailable" if denominator is None else "derived_numeric",
                source_count_status=count_status,source_suppression_flag="Suppressed" if count_status=="source_suppressed" else None,
                suppression_reason=reason,rate_unreliable=unreliable,
                unreliability_reason="Fewer than 20 direct deaths; flag follows the CDC/NCHS WONDER unreliable-rate threshold." if unreliable else None,
                estimation_status="derived_from_direct_WONDER_count_and_Census_PEP_Vintage_2025_age1-4_population_estimates",
                comparability_note="County-only derived crude rate. Cross-county comparison requires exact source county FIPS and matching Census PEP 2025 geography; not directly comparable to WONDER published state rates because denominator vintage/source differ. PEP Vintage 2025 may be revised in future releases.",
                source_reporting_note="Derived annualized county crude rate, not published by CDC WONDER. Numerator is the directly published 2020-2024 all-cause 1-4 death total. Denominator sums 20 Census PEP Vintage 2025 July 1 population estimates (ages 1-4, years 2020-2024). Suppressed death counts and unmatched county boundaries remain null; no deaths were inferred."))

# Archival gender-specific HIV strata are preserved raw; not mixed with current geographic totals.
keys=set();unique=[]
for d in observations:
    k=(d["metric_id"],d["geography_level"],d["geoid"],d["period"])
    if k not in keys:unique.append(d);keys.add(k)
observations=unique
(OUT/"observations.json").write_text(json.dumps(dict(schema_version="1.0",observations=observations),ensure_ascii=False,separators=(",",":"))+"\n")
fields=sorted({k for r in observations for k in r})
with (OUT/"observations.csv").open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(observations)

for metric in sorted({d["metric_id"] for d in observations}):
    rs=[d for d in observations if d["metric_id"]==metric]
    county=[d for d in rs if d["geography_level"]=="county"]
    state=[d for d in rs if d["geography_level"]=="state"]
    if metric.startswith("cancer_"):
        reason="Small-count suppression (<16 over pooled period), bounded rounded annual count, and source geography vintage; CT legacy counties and combined/retired FIPS require map reconciliation. Separate official state fallback collected; rates are not replicated to counties."
        source_name=rs[0]["source_file"].removeprefix("raw/")
        downloaded=receipts.get(source_name,{})
        downloaded_date=downloaded.get("finished_at", "unknown").split("T")[0]
        release=("NCI State Cancer Profiles export generated "+downloaded_date+
                 "; pooled observation period "+"|".join(sorted({d["period"] for d in rs})))
        if metric.startswith("cancer_incidence_"):
            release += "; registry data based on 2025 submission"
    elif metric.startswith("hiv_"):
        reason="CDC confidentiality suppressions and source unavailable cells remain null. Failed nationalcounty chunks recovered using100-ID batches; requested-versus-returned IDs documented in hiv-county-selection-audit.json. Source geography includes retired counties; no state replication."
        release="Live AtlasPlus queried2026-10-03; current app bundle Last-Modified2026-09-24; diagnoses2024 and diagnosed prevalence2024 (latter preliminary death followup)"
    elif metric.startswith("infant_mortality_under1_period_linked_"):
        reason="Period-linked CDC/NCHS infant death output by death year and maternal residence, not birth cohort and not the Stats of the States series. For 2017+ this table identifies counties meeting 250,000 population in the 2010 Census; counties below that cutoff are aggregated as state-specific Unidentified Counties. Counties meeting the cutoff may still have 1-9 death/birth cells suppressed; published rates are marked unreliable when fewer than 20 deaths contribute. Weighted linked-death counts may not exactly sum due to rounding. Do not distribute Unidentified Counties to counties."
        release="CDC WONDER Linked Birth / Infant Death Records, 2017-2024 Expanded (2024 vintage); period-linked observations by death year 2020-2024; fetched 2026-10-04"
    elif metric.startswith("infant_"):
        reason="This Stats of the States series publishes the 2024 state visualization only. A separate period-linked WONDER series is collected for 2020-2024 with identified-county coverage restricted to the 2010 Census 250,000 population threshold; these sources and definitions are not merged."
        release="CDC Stats of States page2026-03-09; embedded data JSON Last-Modified2026-05-18; observation2024"
    elif metric=="child_mortality_1_4_derived_county_rate":
        reason="Derived county crude rate (not published by CDC WONDER): direct 1-4 county death total divided by the sum of 20 Census PEP Vintage 2025 July 1 population estimates (ages 1-4, years 2020-2024), times 100,000. Source-suppressed deaths and exact-FIPS denominator gaps remain null. County rates use a different population vintage/source than WONDER state rates and are not directly comparable to them. Counts with 1-19 deaths carry the WONDER unreliable-rate flag where the rate is derived. Connecticut's eight legacy county FIPS do not match 2025 Census planning regions and are left without rates."
        release="CDC WONDER 2020-2024 final pooled deaths plus U.S. Census PEP County Vintage 2025 CC-EST2025-SYASEX denominator; rate is separately derived"
    elif metric.startswith("child_mortality_1_4_") or metric.startswith("child_mortality_5_14_"):
        reason="CDC WONDER 2020-2024 final all-cause resident deaths: counts are direct pooled death-year totals; state rates are direct age-specific crude rates per 100,000 summed age-specific person-years. County counts are subject to source suppression (<10). Direct county rates for these ten-year groups are unavailable. Separate derived county-rate metrics use exact matching denominators where available: Census PEP Vintage 2025 ages 1-4 or published WONDER ages 5-9 plus 10-14; they remain null for suppressed deaths or missing denominators. Connecticut 2022-2024 population/rates are unavailable for former county FIPS."
        release="CDC WONDER final Underlying Cause of Death 2018-2024 Single Race, 2024 final release; observations pooled years of death 2020-2024; national age-specific 2024 FastStats seed remains a separate period"
        if metric.endswith("derived_county_rate"):
            reason="Derived county crude rate (not directly published for 5-14 county group): directly published 5-14 count divided by summed published 5-9 and 10-14 population person-years times 100,000. Direct count suppression and denominator gaps remain null; no subgroup death-count reconstruction."
    elif metric.startswith("child_"):
        reason="CDC FastStats national 2024 observations for ages 1-4 and 5-14 are retained as a separate period. Subnational pooled 2020-2024 death-year counts and published state rates are separate metric IDs; County Health Rankings under-18/under-20 series use different ages and periods."
        release="Current CDC FastStats queried2026-10-03; finalNVSS2024"
    else:
        reason="Live AtlasPlus offers state data through2023 for hepatitisA/acuteB/acuteC; no county option in these metadata combinations. Unavailable jurisdictions remain null. Newer official2024 surveillance release needs separate review."
        release="Live AtlasPlus metadata queried2026-10-03: hepatitis year ceiling2023"
    county_numeric=sum(d["value"] is not None for d in county)
    state_numeric=sum(d["value"] is not None for d in state)
    county_status="collected" if county_numeric else "source_rows_returned_all_null" if county else "not_collected"
    if metric.startswith("infant_mortality_under1_period_linked_"):
        county_status="identified_counties_only_250k_2010_Census; small_counties_unidentified_state_aggregate" if county else "no_identified_county_rows"
    if metric in {"child_mortality_1_4_rate","child_mortality_5_14_rate"} and county and not county_numeric:
        county_status="not_available_in_source_for_county_age_group"
    metric_entry=dict(metric_id=metric,block_group="not_available_in_selected_official_bulk_source",tract="not_available_in_selected_official_bulk_source",
        county=county_status,state="collected" if state_numeric else "source_rows_returned_all_null" if state else "not_collected",
        finest_collected="county" if county_numeric else "state" if state_numeric else "national" if any(d["geography_level"]=="national" and d["value"] is not None for d in rs) else "none",periods=sorted({d["period"] for d in rs}),
        numeric_observations=sum(d["value"] is not None for d in rs),missing_or_suppressed=sum(d["value"] is None for d in rs),
        county_source_rows=len(county),county_numeric_rows=sum(d["value"] is not None for d in county),
        county_current_census_numeric=sum(d["value"] is not None and d.get("geography_compatibility")=="matches_2025_census_county" for d in county),
        state_numeric_rows=sum(d["value"] is not None for d in state),state_source_rows=len(state),
        definition=next(d.get("universe","") for d in rs),unit=rs[0]["unit"],age_adjustment=rs[0].get("age_adjustment"),
        source_urls=sorted({url for d in rs for url in (d.get("source_url"),d.get("denominator_source_url")) if url}),
        current_release=release,reason_missing=reason)
    if metric.startswith("infant_mortality_under1_period_linked_"):
        unidentified=[d for d in rs if d["geography_level"]=="unidentified_county_aggregate"]
        metric_entry.update(unidentified_county_aggregate_rows=len(unidentified),
            unidentified_county_aggregate_numeric=sum(d["value"] is not None for d in unidentified),
            unidentified_county_aggregate_geographies=sorted({d["source_geoid"] for d in unidentified}),
            identified_county_source_fips=sorted({d["source_geoid"] for d in county}),
            threshold_census_vintage="2010 Census",threshold_population=250000)
    inventory.append(metric_entry)
inventory.append(dict(metric_id="genital_herpes_cases",block_group="not_available",tract="not_available",county="no_uniform_national_notifiable_surveillance",state="no_uniform_national_notifiable_surveillance",finest_collected="none",numeric_observations=0,missing_or_suppressed=0,county_source_rows=0,county_numeric_rows=0,county_current_census_numeric=0,state_source_rows=0,state_numeric_rows=0,definition="HSV-1/HSV-2 seroprevalence is distinct from diagnosed cases",unit="not_established",periods=[],source_urls=["https://ndc.services.cdc.gov/conditions/genital-herpes/"],reason_missing="Genital herpes is not nationally notifiable; national NHANES seroprevalence is a separate potential metric"))
(ROOT/"metric-inventory.json").write_text(json.dumps(dict(metrics=inventory),ensure_ascii=False,indent=2)+"\n")
with (ROOT/"metric-inventory.csv").open("w",newline="") as f:
    fields=sorted({k for r in inventory for k in r});w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for r in inventory:w.writerow({k:"|".join(v) if isinstance(v,list) else v for k,v in r.items()})
(ROOT/"geography-mismatches.json").write_text(json.dumps(dict(reference="2025 Census Gazetteer; no automatic conversion to project map",source_geoid_occurrences=unmatched),indent=2)+"\n")
summary=dict(observations=len(observations),numeric=sum(r["value"] is not None for r in observations),missing_or_suppressed=sum(r["value"] is None for r in observations),metrics=len(inventory),county_reference_geographies=len(COUNTIES),by_metric=inventory)
(ROOT/"coverage.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({k:v for k,v in summary.items() if k!="by_metric"}))
