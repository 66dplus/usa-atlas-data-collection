#!/usr/bin/env python3
"""Bounded fetch for CDC's official modeled HIV incidence/prevalence report.

The downloadable report is the currently linked source for estimated HIV
incidence and total prevalence.  It is not the AtlasPlus diagnosed-case table.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
RECEIPTS = ROOT / "http-receipts.jsonl"
URL = "https://stacks.cdc.gov/view/cdc/156513/cdc_156513_DS1.pdf"
NAME = "cdc-hiv-estimated-incidence-prevalence-2018-2022.pdf"
MAX_BYTES = 16 * 1024 * 1024


def fetch():
    started = datetime.now(timezone.utc).isoformat()
    rec = {"name": NAME, "requested_url": URL, "method": "GET",
           "params": {}, "started_at": started}
    try:
        with requests.get(URL, timeout=(20, 120), stream=True,
                          headers={"User-Agent": "USA-Atlas-medical-research/1.0"}) as response:
            body = bytearray()
            for part in response.iter_content(256 * 1024):
                if not part:
                    continue
                body.extend(part)
                if len(body) > MAX_BYTES:
                    raise ValueError("bounded response exceeds 16 MiB")
            payload = bytes(body)
            rec.update(url=response.url, http_status=response.status_code,
                       content_type=response.headers.get("Content-Type"),
                       content_disposition=response.headers.get("Content-Disposition"),
                       last_modified=response.headers.get("Last-Modified"),
                       etag=response.headers.get("ETag"), bytes=len(payload),
                       sha256=hashlib.sha256(payload).hexdigest())
            response.raise_for_status()
            if not payload.startswith(b"%PDF-"):
                raise ValueError("response is not a PDF")
            target = RAW / NAME
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(payload)
            rec.update(status="downloaded", path=str(target.relative_to(ROOT)))
    except Exception as exc:
        rec.update(status="error", error=f"{type(exc).__name__}: {exc}")
    rec["finished_at"] = datetime.now(timezone.utc).isoformat()
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    print(json.dumps(rec, ensure_ascii=False))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="download CDC report PDF")
    args = ap.parse_args()
    if not args.fetch:
        ap.error("pass --fetch to make the bounded public request")
    fetch()


if __name__ == "__main__":
    main()
