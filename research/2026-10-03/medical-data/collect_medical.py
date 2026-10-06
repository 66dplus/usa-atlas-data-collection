#!/usr/bin/env python3
"""Bounded public primary-source downloads. Writes only this research directory."""
import argparse
import csv
import hashlib
import json
import time
import re
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
RAW.mkdir(exist_ok=True)
RECEIPTS = ROOT / "http-receipts.jsonl"

def fetch(name, url, params=None, maximum=256*1024*1024, method="GET", payload=None):
    target = RAW / name
    started = datetime.now(timezone.utc).isoformat()
    rec = dict(name=name, requested_url=url, params=params, method=method, payload=payload, started_at=started)
    h = hashlib.sha256()
    size = 0
    try:
        with requests.request(method, url, params=params, json=payload, timeout=(20, 120), stream=True) as r:
            rec.update(url=r.url, http_status=r.status_code,
                       content_type=r.headers.get("Content-Type"),
                       last_modified=r.headers.get("Last-Modified"), etag=r.headers.get("ETag"))
            r.raise_for_status()
            with target.open("wb") as f:
                for b in r.iter_content(1024*1024):
                    size += len(b)
                    if size > maximum:
                        raise ValueError("bounded download exceeds byte limit")
                    h.update(b)
                    f.write(b)
            rec.update(bytes=size, sha256=h.hexdigest(), path=str(target.relative_to(ROOT)), status="downloaded")
    except Exception as e:
        rec.update(status="error", error=str(e), partial_bytes=size)
    rec["finished_at"] = datetime.now(timezone.utc).isoformat()
    with RECEIPTS.open("a") as f:
        f.write(json.dumps(rec)+"\n")
    # The exact payload stays in the receipt; avoid printing thousands of IDs.
    print(json.dumps({k:v for k,v in rec.items() if k not in ["payload","params"]}), flush=True)
    return rec

def cancer():
    # Sex-specific cancers use the appropriate denominator. No total-case reconstruction.
    cancer_types = [("all_sites","001","0"),("lung","047","0"),
                    ("breast_female","055","2"),("colorectal","020","0"),
                    ("prostate_male","066","1"),("melanoma","053","0"),
                    ("pancreas","040","0"),("liver_intrahepatic_bile_duct","035","0")]
    for kind, code, sex in cancer_types:
        for level in ["county", "state"]:
            p=dict(stateFIPS="00", areatype=level, cancer=code, race="00", sex=sex,
                   age="001", type="incd", sortVariableName="rate", sortOrder="default", output="1")
            fetch("nci-incidence-"+kind+"-"+level+".csv", "https://statecancerprofiles.cancer.gov/incidencerates/index.php", p)
            time.sleep(.5)
    # State totals are retrieved separately, never synthesized by summing rounded county rates.
    for level in ["county", "state"]:
        mortality(level)

def mortality(level="state"):
    p=dict(stateFIPS="00", areatype=level, cancer="001", race="00", sex="0", age="001",
           type="death", sortVariableName="rate", sortOrder="default", output="1")
    fetch("nci-mortality-all_sites-"+level+".csv", "https://statecancerprofiles.cancer.gov/deathrates/index.php", p)

def mortality_types():
    # CDC/NCI State Cancer Profiles provides a distinct five-year pooled mortality
    # table by site and area. Female breast and male prostate retain sex-specific
    # populations in their source selectors; no counts or rates are synthesized.
    cancer_types = [("lung", "047", "0"), ("breast_female", "055", "2"),
                    ("colorectal", "020", "0"), ("prostate_male", "066", "1"),
                    ("melanoma", "053", "0")]
    for kind, code, sex in cancer_types:
        for level in ["county", "state"]:
            p=dict(stateFIPS="00", areatype=level, cancer=code, race="00", sex=sex,
                   age="001", type="death", sortVariableName="rate", sortOrder="default", output="1")
            fetch("nci-mortality-"+kind+"-"+level+".csv", "https://statecancerprofiles.cancer.gov/deathrates/index.php", p)
            time.sleep(.5)

def supporting():
    fetch("infant-visualization-config.json", "https://www.cdc.gov/nchs/pressroom/sosmap/infant_mortality_rates/infant_mortality_dfe.json")
    fetch("cdc-child-health-final-2024.html", "https://www.cdc.gov/nchs/fastats/child-health.htm")
    fetch("census-2025-county-gazetteer.zip", "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_counties_national.zip")

def hiv():
    fetch("cdc-atlas-historical-20250430.csv", "https://www.cdc.gov/nchhstp/media/files/2025/05/AtlasPlus_historic-data-extract_20250430_1.csv")
    fetch("cdc-atlas-historical-readme.pdf", "https://www.cdc.gov/nchhstp/media/pdfs/2025/05/ReadMe_AtlasPlus_historical-data-extract_20250430.pdf")

def atlas_live():
    fetch("atlas-init.json", "https://gis.cdc.gov/api/AtlasPlus/getInitData/0")
    j=json.loads((RAW/"atlas-init.json").read_text())
    state_fips={"01","02","04","05","06","08","09","10","11","12","13","15","16","17","18","19","20","21","22","23","24","25","26","27","28","29","30","31","32","33","34","35","36","37","38","39","40","41","42","44","45","46","47","48","49","50","51","53","54","55","56"}
    # Public application table-export API; POST performs a read-only statistical query.
    for level,geo_level in [("county",1003),("state",1002)]:
        geos=[v["id"] for v in j["varvals"] if v.get("vtid")==3 and v.get("geoLevel")==geo_level and str(v.get("fips",""))[:2] in state_fips]
        for indicator,kind,age in [(203,"hiv-diagnoses",650),(205,"hiv-diagnosed-prevalence",650)]:
            # Bounded requests avoid backend limits on a single national county query.
            for chunk_start in range(0,len(geos),400):
                suffix="" if level=="state" else "-part"+str(chunk_start//400+1)
                payload={"VariableIDs":",".join(str(x) for x in [indicator,546,551,601,age,801]+geos[chunk_start:chunk_start+400])}
                fetch("cdc-atlas-"+kind+"-"+level+"-2024"+suffix+".json", "https://gis.cdc.gov/api/AtlasPlus/qtOutputData", method="POST", payload=payload)
                time.sleep(.3)
    # Hepatitis incidence reporting is available at state, not county, in AtlasPlus.
    geos=[v["id"] for v in j["varvals"] if v.get("vtid")==3 and v.get("geoLevel")==1002 and str(v.get("fips",""))[:2] in state_fips]
    for indicator,kind in [(210,"hepatitis-a"),(211,"hepatitis-b-acute"),(212,"hepatitis-c-acute")]:
        # Init combinations document hepatitis through 2023 (value ID 545).
        payload={"VariableIDs":",".join(str(x) for x in [indicator,545,551,601,651,801]+geos)}
        fetch("cdc-atlas-"+kind+"-state-2023.json", "https://gis.cdc.gov/api/AtlasPlus/qtOutputData", method="POST", payload=payload)
        time.sleep(.3)

def atlas_retry():
    latest={}
    for line in RECEIPTS.read_text().splitlines():
        r=json.loads(line);latest[r["name"]]=r
    for name,r in latest.items():
        if not re.fullmatch(r"cdc-atlas-hiv-.*-county-2024-part\d+\.json",name):continue
        existing=RAW/name
        if r.get("status")=="downloaded" and existing.exists() and json.loads(existing.read_text()).get("sourcedata"):continue
        ids=r["payload"]["VariableIDs"].split(",");fixed,geos=ids[:6],ids[6:]
        for start in range(0,len(geos),100):
            part_name=name[:-5]+"-retry-"+str(start//100+1)+".json"
            if (RAW/part_name).exists() and json.loads((RAW/part_name).read_text()).get("sourcedata"):continue
            fetch(part_name,r["requested_url"],method="POST",payload={"VariableIDs":",".join(fixed+geos[start:start+100])})
            time.sleep(.3)

if __name__ == "__main__":
    p=argparse.ArgumentParser();p.add_argument("stage",choices=["cancer","mortality-state","mortality-types","supporting","hiv","atlas-live","atlas-retry"])
    args=p.parse_args()
    {"cancer":cancer,"mortality-state":mortality,"mortality-types":mortality_types,"supporting":supporting,"hiv":hiv,"atlas-live":atlas_live,"atlas-retry":atlas_retry}[args.stage]()
