#!/usr/bin/env python3
"""Bounded public CDC WONDER collection for linked infant mortality."""
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
LANDING="https://wonder.cdc.gov/lbd-current-expanded.html"
MAX_FORM=2*1024*1024
MAX_EXPORT=12*1024*1024


def safe_url(url):
    return re.sub(r";jsessionid=[^/?;]+", "", url)


def fetch(session,name,url,*,method="GET",payload=None,maximum=MAX_FORM,save=True,expected_tsv=False):
    started=datetime.now(timezone.utc).isoformat()
    receipt={"name":name,"requested_url":safe_url(url),"method":method,"params":payload,
             "started_at":started}
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
            response.raise_for_status()
            if expected_tsv and (".tsv" not in (response.headers.get("Content-Disposition") or "").lower()
                    or not raw.startswith(b'"Notes"\t')):
                raise ValueError("HTTP response was not the expected tab-delimited WONDER export")
            if save:
                target=RAW/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(raw)
                receipt["path"]=str(target.relative_to(ROOT))
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


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__();self.forms=[];self.current=None;self.select=None;self.textarea=None
    def add(self,name,value):
        if name is not None:self.current["data"].setdefault(name,[]).append("" if value is None else value)
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="form":
            self.current={"action":d.get("action"),"id":d.get("id"),"data":{}}
            self.forms.append(self.current)
        elif self.current is not None and tag=="input" and d.get("name") and "disabled" not in d:
            typ=d.get("type","").lower()
            if typ in ("hidden","text"):
                self.add(d["name"],d.get("value",""))
            elif typ in ("radio","checkbox") and "checked" in d:
                self.add(d["name"],d.get("value",""))
        elif self.current is not None and tag=="select" and d.get("name"):
            self.select=[d["name"],"multiple" in d,[],None]
        elif self.current is not None and tag=="option" and self.select is not None:
            if self.select[3] is None:self.select[3]=d.get("value","")
            if "selected" in d:self.select[2].append(d.get("value",""))
        elif self.current is not None and tag=="textarea" and d.get("name"):
            self.textarea=d["name"]
    def handle_data(self,data):
        if self.current is not None and self.textarea:
            self.current["data"].setdefault(self.textarea,[]).append(data)
    def handle_endtag(self,tag):
        if tag=="select" and self.select is not None:
            name,multiple,values,first=self.select
            if values:self.current["data"][name]=values[:]
            elif not multiple and first is not None:self.current["data"][name]=[first]
            self.select=None
        elif tag=="textarea" and self.textarea:self.textarea=None
        elif tag=="form":self.current=None


def forms(body):
    parser=PageParser();parser.feed(body.decode("utf-8","replace"))
    out=[]
    for form in parser.forms:
        data={k:(v if len(v)>1 else v[0]) for k,v in form["data"].items()}
        out.append({"action":form["action"],"id":form["id"],"data":data})
    return out


def request_form(body):
    for item in forms(body):
        if item["id"]=="wonderform" and item["action"] and "D159" in item["action"]:
            return item["action"],item["data"]
    raise RuntimeError("CDC WONDER did not return the expected D159 request form")


def query_payload(base,level,year):
    p=dict(base)
    p["B_1"]="D159.V10-level1" if level=="state" else "D159.V10-level2"
    p["B_2"]="*None*"
    p["B_3"]="*None*";p["B_4"]="*None*";p["B_5"]="*None*"
    p["O_location"]="D159.V10";p["O_V10_fmode"]="freg";p["F_D159.V10"]="*All*"
    p["V_D159.V9"]=str(year)
    p["O_rate_per"]="1000"
    p["O_export-format"]="tsv"
    p["O_show_totals"]="true";p["O_show_suppressed"]="true";p["O_show_zeros"]="true"
    p["O_precision"]="3"
    p["O_title"]=f"Period-linked infant deaths, births, and rate by maternal residence: {year}"
    p["O_change_action-Send-Export Results"]="true"
    p["action-Send"]="Send"
    return p


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--fetch",action="store_true",help="accept WONDER terms and download 2020-2024 tables")
    args=ap.parse_args()
    if not args.fetch:ap.error("use --fetch to retrieve the public CDC WONDER export")
    RAW.mkdir(exist_ok=True)
    session=requests.Session()
    landing=fetch(session,"cdc-wonder-lbd-expanded-landing.html",LANDING,maximum=MAX_FORM)
    if landing.get("status")!="downloaded":return
    consent=fetch(session,"cdc-wonder-lbd-expanded-consent.html",
        "https://wonder.cdc.gov/controller/datarequest/D159",method="POST",
        payload={"stage":"about","saved_id":"","action-I Agree":"I Agree"},
        maximum=MAX_FORM,save=True)
    if consent.get("status")!="downloaded":return
    action,base=request_form(consent["body"])
    endpoint=urljoin(LANDING,action)
    for year in range(2020,2025):
        for level in ("state","county"):
            name=f"cdc-wonder-linked-infant-mortality-{level}-{year}.tsv"
            result=fetch(session,name,endpoint,method="POST",payload=query_payload(base,level,year),
                maximum=MAX_EXPORT,save=True,expected_tsv=True)
            if result.get("status")!="downloaded":return
            print(json.dumps({"name":result["name"],"content_type":result.get("content_type"),
                "content_disposition":result.get("content_disposition"),"bytes":result.get("bytes")},ensure_ascii=False),flush=True)
            time.sleep(1.0)


if __name__=="__main__":main()
