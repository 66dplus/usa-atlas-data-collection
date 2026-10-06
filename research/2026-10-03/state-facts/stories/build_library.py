#!/usr/bin/env python3
"""Build research indexes from independently researched story batches; no network or DB writes."""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(name, data):
    (ROOT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def valid_url(url):
    parts = urlsplit(str(url or ""))
    return parts.scheme in {"https", "http"} and bool(parts.netloc) and not parts.username


def url_key(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ""))


def action_place(place, states):
    """Atlas supports state/county selectors. Preserve cities in story evidence."""
    code = place.get("state_code", "").upper()
    if code not in states:
        return None
    geoid = str(place.get("geoid") or "")
    if place.get("kind") == "county" and len(geoid) == 5 and geoid.isdigit() and geoid[:2] == states[code]["fips"]:
        return {"name": place["name"], "kind": "county", "geoid": geoid, "state_code": code}
    return {"name": states[code]["name"], "kind": "state", "geoid": states[code]["fips"], "state_code": code}


def build():
    now = datetime.now(timezone.utc).isoformat()
    states = read(ROOT / "state-register.json")
    metrics = read(ROOT / "atlas-metric-register.json")
    definitions = read(ROOT / "collection-definitions.json")
    corpus, receipts, problems = [], [], []
    seen_ids = set()
    for path in sorted(ROOT.glob("*/*.json")):
        if path.parent.name in {"sources", "raw", "snapshots"} or path.name == "calculations.json":
            continue
        data = read(path)
        if not isinstance(data, dict) or not isinstance(data.get("stories"), list):
            continue
        receipts.append({"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "stories": len(data["stories"])})
        for original in data["stories"]:
            story = dict(original)
            sid = story.get("id")
            errors = []
            required = ["id", "headline_ru", "summary_ru", "themes", "states", "places", "period", "verification_status", "sources", "caveats", "refresh"]
            errors.extend("missing:" + key for key in required if key not in story)
            if not isinstance(sid, str) or not sid:
                errors.append("invalid_id")
            elif sid in seen_ids:
                errors.append("duplicate_id")
            if story.get("verification_status") not in {"verified", "candidate", "rejected"}:
                errors.append("unknown_verification_status")
            codes = story.get("states", [])
            if not isinstance(codes, list) or any(code not in states for code in codes):
                errors.append("unknown_state_code")
            sources = story.get("sources", [])
            if not isinstance(sources, list) or not sources:
                errors.append("no_sources")
            else:
                for source in sources:
                    if not isinstance(source, dict) or not valid_url(source.get("url")):
                        errors.append("invalid_source_url")
                    elif not source.get("evidence_ru") or not source.get("accessed_at"):
                        errors.append("missing_source_evidence_or_access_date")
                    elif not all(key in source for key in ["title", "publisher", "role", "published_date"]):
                        errors.append("missing_source_metadata")
            if not isinstance(story.get("refresh"), dict) or not all(key in story.get("refresh", {}) for key in ["method", "frequency", "source_urls"]):
                errors.append("missing_refresh_policy")
            if errors:
                problems.append({"id": sid, "batch": str(path.relative_to(ROOT)), "errors": errors})
                continue
            seen_ids.add(sid)
            story["batch_path"] = str(path.relative_to(ROOT))
            story["production_admitted"] = False
            story["display_ready"] = story["verification_status"] == "verified"
            story["collection_ids"] = []
            story["atlas_actions"] = []
            corpus.append(story)

    collections = []
    for definition in definitions:
        item = dict(definition)
        item["verified_story_ids"], item["candidate_story_ids"] = [], []
        for story in corpus:
            themes = {str(t).lower().replace("_", "-") for t in story["themes"]}
            pair_match = set(item.get("state_pair", [])).issubset(story["states"]) if item.get("state_pair") else True
            theme_match = bool(themes.intersection(item.get("theme_aliases", []))) if item.get("theme_aliases") else True
            if pair_match and theme_match and story["verification_status"] != "rejected":
                story["collection_ids"].append(item["id"])
                key = "verified_story_ids" if story["display_ready"] else "candidate_story_ids"
                item[key].append(story["id"])
        item["verified_count"] = len(item["verified_story_ids"])
        item["candidate_count"] = len(item["candidate_story_ids"])
        collections.append(item)

    comparisons = []
    for story in corpus:
        if not story["display_ready"]:
            continue
        for pair in story.get("comparisons", []):
            left_original, right_original = pair.get("from", {}), pair.get("to", {})
            left, right = action_place(left_original, states), action_place(right_original, states)
            if not left or not right:
                continue
            if left["kind"] != right["kind"]:
                left = action_place({"kind": "state", "state_code": left["state_code"]}, states)
                right = action_place({"kind": "state", "state_code": right["state_code"]}, states)
            if left["geoid"] == right["geoid"]:
                continue
            metric = pair.get("metric_id")
            field_to_metric = {info.get("catalog_field_id"): mid for mid, info in metrics.items()}
            metric = field_to_metric.get(metric, metric)
            if metric not in metrics:
                metric = "electricity-price" if set(story["themes"]).intersection({"energy", "electricity", "data-centers"}) else "median-household-income"
            if left["kind"] == "county" and not metrics[metric]["county_supported"]:
                metric = "median-household-income"
            mapped = left_original.get("kind") != left["kind"] or right_original.get("kind") != right["kind"]
            reason = pair.get("reason_ru", "Сравнить условия жизни в этих местах")
            if mapped:
                reason = f"Сравнить {left['name']} и {right['name']} по {metrics[metric]['name']}; сюжет относится к {left_original.get('name')} и {right_original.get('name')}."
            action = {
                "story_id": story["id"], "from": left, "to": right,
                "original_from": left_original, "original_to": right_original,
                "metric_id": metric, "metric_name": metrics[metric]["name"],
                "link_kind": "contextual", "reason_ru": reason,
                "original_reason_ru": pair.get("reason_ru"),
                "geography_note_ru": "Сюжет относится к указанным местам; кнопка сравнивает их штаты." if mapped else "Сравнение использует указанный уровень географии.",
                "period_note_ru": "Период статистики Atlas показывается отдельно от даты сюжета; число в сюжете не подставляется в показатель.",
                "url": "/ux/?" + urlencode({"concept": "compare", "place": left["geoid"], "other": right["geoid"], "metric": metric, "view": "2d"}),
                "integration_status": "research_action_spec_not_published",
            }
            story["atlas_actions"].append(action)
            comparisons.append(action)

    source_index = {}
    for story in corpus:
        for source in story["sources"]:
            key = url_key(source["url"])
            if key not in source_index:
                source_index[key] = dict(source, story_ids=[], refresh_policies=[])
            source_index[key]["story_ids"].append(story["id"])
            policy = {"story_id": story["id"], **story["refresh"]}
            source_index[key]["refresh_policies"].append(policy)
    status = Counter(s["verification_status"] for s in corpus)
    media = sum(any(source.get("role") == "media" for source in s["sources"]) for s in corpus if s["display_ready"])
    state_rows = []
    for code, info in states.items():
        rows = [s for s in corpus if code in s["states"]]
        verified = [s for s in rows if s["display_ready"]]
        state_rows.append({"state_code": code, **info, "verified_stories": len(verified), "candidate_stories": sum(s["verification_status"] == "candidate" for s in rows), "themes": sorted({t for s in verified for t in s["themes"]}), "story_ids": [s["id"] for s in verified], "growth_target": 10, "remaining_to_growth_target": max(0, 10 - len(verified))})
    common = {"schema_version": 1, "built_at": now, "production_admitted": False}
    write("library.json", {**common, "stories": corpus})
    write("collections.json", {**common, "collections": collections})
    write("comparison-actions.json", {**common, "actions": comparisons})
    write("story-source-register.json", {**common, "sources": list(source_index.values())})
    write("coverage.json", {**common, "counts": dict(status), "verified_with_media_source": media, "source_urls": len(source_index), "comparison_actions": len(comparisons), "collections": len(collections), "collections_with_verified_stories": sum(c["verified_count"] > 0 for c in collections), "states_with_verified_stories": sum(r["verified_stories"] > 0 for r in state_rows if r["state_code"] != "DC"), "dc_separate": True, "baseline_cards_not_counted": 115, "states": state_rows, "batch_receipts": receipts, "invalid_records": problems})
    columns = ["id", "headline_ru", "summary_ru", "verification_status", "states", "themes", "period", "collection_ids", "source_urls", "comparison_urls", "batch_path"]
    with (ROOT / "library.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for story in corpus:
            row = {key: story.get(key) for key in columns}
            for key in ["states", "themes", "collection_ids"]:
                row[key] = "|".join(story[key])
            row["source_urls"] = "|".join(s["url"] for s in story["sources"])
            row["comparison_urls"] = "|".join(a["url"] for a in story["atlas_actions"])
            writer.writerow(row)
    lines = ["# Библиотека сюжетов для сравнений", "", f"Собрано: {status['verified']} подтверждённых сюжетов, {status['candidate']} кандидатов, {status['rejected']} отклонённых формулировок. Исходные 115 статистических карточек сюда не включены.", "", "Подборки группируют сюжеты по теме и парам мест. Ссылки ниже — спецификации действий для существующего Atlas; исследовательский индекс ещё не опубликован в интерфейсе.", ""]
    for collection in collections:
        rows = [s for s in corpus if s["id"] in collection["verified_story_ids"]]
        if not rows:
            continue
        lines.extend(["## " + collection["title_ru"], ""])
        for story in rows:
            sources = "; ".join(f"[{s['publisher']}]({s['url']})" for s in story["sources"])
            lines.append(f"- **{story['headline_ru']}** {story['summary_ru']} Источники: {sources}. ID: `{story['id']}`.")
        lines.append("")
    (ROOT / "BROWSE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"counts": dict(status), "comparison_actions": len(comparisons), "source_urls": len(source_index), "invalid_records": problems}, ensure_ascii=False))


if __name__ == "__main__":
    build()
