#!/usr/bin/env python3
"""Build a reproducible US Google Trends export queue; never invent metrics."""
import csv
import json
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
WINDOWS = ("2025-09-01 2026-08-31", "2021-09-01 2026-08-31")
ANCHOR = "cost of living"


def main():
    with (ROOT / "keyword-seeds.csv").open(newline="", encoding="utf-8") as stream:
        seeds = list(csv.DictReader(stream))
    topics = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))
    known = {topic["id"] for topic in topics}
    if len(known) != len(topics):
        raise ValueError("duplicate topic IDs")
    if any(row["topic_id"] not in known for row in seeds):
        raise ValueError("unknown topic ID")
    if len({(row["topic_id"], row["keyword"]) for row in seeds}) != len(seeds):
        raise ValueError("duplicate topic keywords")
    jobs = []
    for topic in topics:
        terms = [row["keyword"] for row in seeds if row["topic_id"] == topic["id"]]
        terms = [term for term in terms if term != ANCHOR]
        for offset in range(0, len(terms), 4):
            compared = [ANCHOR, *terms[offset:offset + 4]]
            for window in WINDOWS:
                params = {"geo": "US", "date": window, "q": ",".join(compared), "hl": "en"}
                jobs.append({
                    "job_id": f"{topic['id']}-{offset // 4}-{window[:10]}",
                    "topic_id": topic["id"], "geo": "US", "date": window,
                    "search_type": "web", "category": 0, "input_kind": "search_term",
                    "terms": compared, "anchor": ANCHOR,
                    "url": "https://trends.google.com/trends/explore?" + urlencode(params),
                    "status": "not_collected", "artifact_sha256": None,
                    "note": "Shared anchor is a starting design; split by scale if rounded to zero.",
                })
    (ROOT / "trends-jobs.json").write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")
    # This is an empty template, separate from any real measurements.
    with (ROOT / "export-register-template.csv").open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow([
            "job_id", "provider", "geo", "period_start", "period_end", "retrieved_at",
            "query_kind", "search_network", "artifact_path", "artifact_sha256", "notes",
        ])
    print(json.dumps({"topics": len(topics), "seed_queries": len(seeds),
                      "planned_exports": len(jobs), "collected_exports": 0}))


if __name__ == "__main__":
    main()
