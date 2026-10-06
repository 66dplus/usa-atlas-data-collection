#!/usr/bin/env python3
"""Bounded CDC WONDER collection for age 1-4 and 5-14 mortality."""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT=Path(__file__).resolve().parent
RAW=ROOT/"raw"
RECEIPTS=ROOT/"http-receipts.jsonl"
LANDING="https://wonder.cdc.gov/ucd-icd10-expanded.html"
REQUEST="https://wonder.cdc.gov/controller/datarequest/D158"
MAX_FORM=2*1024*1024
MAX_EXPORT=12*1024*1024


def safe_url(url):
    return re.sub(r";jsessionid=[^/?;]+", "", url)


def fetch(session,name,url,*,method="GET",payload=None,maximum=MAX_FORM,save=True):
    started=datetime.now(timezone.utc).isoformat()
    receipt={"name":name,"requested_url":safe_url(url),"method":method,"params":payload,
             "started_at":started}
    target=None
    try:
        with session.request(method,url,data=payload,timeout=(20,120),stream=True) as response:
            body=bytearray()
            for part in response.iter_content(256*1024):
                if not part: continue
                body.extend(part)
                if len(body)>maximum: raise ValueError("bounded response exceeds byte limit")
            raw=bytes(body)
            receipt.update(url=safe_url(response.url),http_status=response.status_code,
                content_type=response.headers.get("Content-Type"),
                content_disposition=response.headers.get("Content-Disposition"),
                bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            if save:
                target=RAW/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(raw)
                receipt["path"]=str(target.relative_to(ROOT))
            response.raise_for_status()
            receipt["status"]="downloaded" if save else "accessed"
            receipt["body"]=raw
    except Exception as exc:
        receipt.update(status="error",error=type(exc).__name__+": "+safe_url(str(exc)))
    receipt["finished_at"]=datetime.now(timezone.utc).isoformat()
    clean={k:v for k,v in receipt.items() if k!="body"}
    with RECEIPTS.open("a",encoding="utf-8") as output:
        output.write(json.dumps(clean,ensure_ascii=False,separators=(",",":"))+"\n")
    print(json.dumps(clean,ensure_ascii=False),flush=True)
    return receipt


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__();self.form_action=None;self.form_id=None;self.data={}
        self.select=None;self.textarea=None
    def add(self,name,value):
        if name is None:return
        self.data.setdefault(name,[]).append("" if value is None else value)
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="form" and d.get("id")=="wonderform":
            self.form_action=d.get("action");self.form_id=d.get("id")
        elif tag=="input" and d.get("name") and "disabled" not in d:
            typ=d.get("type","").lower()
            if typ in ("hidden","text"):
                self.add(d["name"],d.get("value",""))
            elif typ in ("radio","checkbox") and "checked" in d:
                self.add(d["name"],d.get("value",""))
        elif tag=="select" and d.get("name"):
            self.select=[d["name"],"multiple" in d,[],None]
        elif tag=="option" and self.select is not None:
            if self.select[3] is None:self.select[3]=d.get("value","")
            if "selected" in d:self.select[2].append(d.get("value",""))
        elif tag=="textarea" and d.get("name"):
            self.textarea=d["name"]
    def handle_data(self,data):
        if self.textarea:
            self.data.setdefault(self.textarea,[]).append(data)
    def handle_endtag(self,tag):
        if tag=="select" and self.select is not None:
            name,multiple,values,first=self.select
            if values:self.data[name]=values[:]
            elif not multiple and first is not None:self.data[name]=[first]
            self.select=None
        elif tag=="textarea" and self.textarea:
            self.textarea=None


def parse_form(body):
    parser=FormParser();parser.feed(body.decode("utf-8","replace"))
    if not parser.form_action or "D158" not in parser.form_action or not parser.data:
        raise RuntimeError("CDC WONDER did not return the expected D158 request form")
    payload={k:(v if len(v)>1 else v[0]) for k,v in parser.data.items()}
    return parser.form_action,payload


def query_payload(base,area,age_resolution="ten-year"):
    p=dict(base)
    p["B_1"]="D158.V9-level2" if area=="county" else "D158.V9-level1"
    age_var="D158.V51" if age_resolution=="five-year" else "D158.V5"
    age_field="V_D158.V51" if age_resolution=="five-year" else "V_D158.V5"
    p["B_2"]=age_var
    p["B_3"]="*None*";p["B_4"]="*None*";p["B_5"]="*None*"
    p["O_location"]="D158.V9"
    p["F_D158.V9"]="*All*"
    p["O_age"]=age_var
    p[age_field]=["1-4","5-9","10-14"] if age_resolution=="five-year" else ["1-4","5-14"]
    p["V_D158.V5"]="*All*" if age_resolution=="five-year" else p["V_D158.V5"]
    p["V_D158.V51"]="*All*" if age_resolution=="ten-year" else p["V_D158.V51"]
    p["VM_D158.M6_D158.V1_S"]=["2020","2021","2022","2023","2024"]
    p["O_show_suppressed"]="true"
    p["O_show_zeros"]="true"
    p["O_post_pops"]="true"
    p["O_title"]="All-cause resident deaths by state/county and age group, years of death 2020-2024"
    p["O_change_action-Send-Export Results"]="true"
    p["O_export-format"]="tsv"
    p["action-Send"]="Send"
    return p


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--fetch",action="store_true",help="accept WONDER terms and retrieve county/state exports")
    args=parser.parse_args()
    if not args.fetch:
        parser.error("use --fetch to retrieve the public CDC WONDER extract")
    RAW.mkdir(exist_ok=True)
    session=requests.Session()
    landing=fetch(session,"cdc-wonder-ucd-expanded-landing.html",LANDING,
                  maximum=MAX_FORM,save=True)
    if landing.get("status")!="downloaded":return
    consent=fetch(session,"cdc-wonder-ucd-expanded-consent.html",REQUEST,
                  method="POST",payload={"stage":"about","action-I Agree":"I Agree"},
                  maximum=MAX_FORM,save=False)
    if consent.get("status")!="accessed":return
    form_action,base=parse_form(consent["body"])
    form_action=urljoin(LANDING,form_action)
    for area,age_resolution in (("state","ten-year"),("county","ten-year"),("county","five-year")):
        payload=query_payload(base,area,age_resolution)
        suffix="-5year" if age_resolution=="five-year" else ""
        result=fetch(session,"cdc-wonder-child-mortality-"+area+suffix+"-2020-2024.tsv",
                     form_action,method="POST",payload=payload,maximum=MAX_EXPORT,save=True)
        if result.get("status")=="downloaded":
            raw=result["body"]
            content_type=(result.get("content_type") or "").lower()
            if "html" in content_type:
                title=re.search(rb"<title[^>]*>(.*?)</title>",raw,re.I|re.S)
                result_title=title.group(1).decode("utf-8","replace") if title else None
                print(json.dumps({"result_name":result["name"],"result_title":result_title,
                    "html_response":True,"response_bytes":len(raw)},ensure_ascii=False),flush=True)
        time.sleep(1.0)


if __name__=="__main__":main()
