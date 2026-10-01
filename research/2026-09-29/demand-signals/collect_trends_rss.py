#!/usr/bin/env python3
"""Snapshot Google's public US Trending Now RSS; preserve supplied values, not inferred keyword demand."""
import collections
import csv
import datetime as dt
import email.utils
import fcntl
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2]
URL = 'https://trends.google.com/trending/rss?geo=US'
HT = {'ht': 'https://trends.google.com/trending/rss'}
TOPICS = REPO / 'research/2026-09-28/demand/topics.json'
SEEDS = REPO / 'research/2026-09-28/demand/keyword-seeds.csv'
ALIASES = {
 'data-centers': ['data center','data centers','datacenter','datacenters'],
 'electricity': ['electricity','electric bill','electric bills','power outage','power outages'],
 'energy-burden': ['energy burden','utility bill','utility bills','energy assistance'],
 'water-drought': ['drought','water shortage','water shortages','groundwater','water supply'],
 'pfas': ['pfas','forever chemicals','drinking water contamination'],
 'housing-cost': ['rent prices','home prices','housing prices','housing affordability','mortgage rates'],
 'adu-housing': ['accessory dwelling unit','accessory dwelling units','adu housing'],
 'cost-of-living': ['cost of living','consumer prices','inflation'],
 'home-insurance': ['home insurance','homeowners insurance'],
 'flood-wildfire': ['flood','flooding','floods','wildfire','wildfires'],
 'overdose': ['overdose','overdoses','fentanyl'],
 'treatment-access': ['naloxone','narcan','addiction treatment','drug rehabilitation'],
 'crime': ['crime rates','violent crime','homicide','homicides','murder rate'],
 'jobs-income': ['unemployment','wages','median income','job openings','layoffs'],
 'homelessness': ['homeless','homelessness'],
 'wealth': ['millionaire','millionaires','billionaire','billionaires','wealth inequality'],
 'large-companies': ['company revenue','corporate revenue','billion dollar company','billion dollar companies'],
 'broadband': ['broadband','internet access','internet availability'],
 'air-quality': ['air quality','air pollution','aqi'],
 'heat': ['heat wave','heatwave','extreme heat','heat index']}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def norm(value):
    return ' '.join(re.sub(r'[^\w]+', ' ', unicodedata.normalize('NFKC', value).casefold()).split())


def contains(query, phrase):
    return (' ' + norm(phrase) + ' ') in (' ' + norm(query) + ' ')


def main():
    BASE.mkdir(exist_ok=True)
    lock = (BASE / '.collection.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run = BASE / 'snapshots' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run.mkdir(parents=True)
    started = now()
    receipts = []
    payload = None
    for attempt in [1, 2]:
        receipt = {'url': URL, 'attempt': attempt, 'started_at': now()}
        try:
            request = urllib.request.Request(URL, headers={'User-Agent': 'USA-Atlas-public-demand-research/1.0', 'Accept': 'application/rss+xml, application/xml, text/xml'})
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(2_000_001)
                receipt.update(status=response.status, final_url=response.url,
                    content_type=response.headers.get('Content-Type'), http_date=response.headers.get('Date'),
                    etag=response.headers.get('ETag'), last_modified=response.headers.get('Last-Modified'),
                    cache_control=response.headers.get('Cache-Control'))
            if len(body) > 2_000_000:
                raise ValueError('RSS exceeds bounded2MB')
            root = ET.fromstring(body)
            if root.tag != 'rss' or root.find('channel') is None:
                raise ValueError('response is not an RSS channel')
            payload = body
            (run / 'google-trends-us.xml').write_bytes(body)
            receipt.update(result='received', bytes=len(body), sha256=sha(body), raw_file='google-trends-us.xml')
        except Exception as exc:
            receipt.update(result='error', error=f'{type(exc).__name__}: {exc}')
            if isinstance(exc, urllib.error.HTTPError):
                receipt['status'] = exc.code
                receipt['retry_after'] = exc.headers.get('Retry-After')
        receipt['completed_at'] = now()
        receipts.append(receipt)
        write(run / 'receipts.json', receipts)
        if payload is not None:
            break
        if isinstance(exc if 'exc' in locals() else None, ValueError):
            break
        if receipt.get('status') in [401,403,404]:
            break
        if attempt == 1:
            delay = receipt.get('retry_after')
            if delay and (not delay.isdigit() or int(delay) > 30):
                break
            time.sleep(int(delay) if delay else 3)
    if payload is None:
        manifest = {'status':'source_unavailable','source_url':URL,'started_at':started,'completed_at':now(),'receipts':receipts}
        write(run/'manifest.json',manifest);write(BASE/'latest.json',{'run':str(run.relative_to(BASE)),**manifest})
        raise SystemExit(1)
    channel = root.find('channel')
    records = []
    for index, item in enumerate(channel.findall('item'), 1):
        query = item.findtext('title')
        traffic = item.findtext('ht:approx_traffic', namespaces=HT)
        date_raw = item.findtext('pubDate')
        try:
            date_utc = email.utils.parsedate_to_datetime(date_raw).astimezone(dt.timezone.utc).isoformat() if date_raw else None
        except (ValueError, TypeError):
            date_utc = None
        match = re.fullmatch(r'([0-9][0-9,]*)([KMB]?)\+', (traffic or '').strip(), re.I)
        bucket = int(match.group(1).replace(',','')) * {'':1,'K':1000,'M':1000000,'B':1000000000}[match.group(2).upper()] if match else None
        records.append({'feed_position':index,'query':query,'source_geo':'US',
            'approx_traffic_raw':traffic,'displayed_traffic_bucket_floor':bucket,
            'bucket_floor_is_exact_search_count':False,'monthly_search_volume':None,
            'pub_date_raw':date_raw,'pub_date_utc':date_utc,'link':item.findtext('link'),
            'news_items_count':len(item.findall('ht:news_item',HT)),
            'record_id':sha(((query or '')+'\0'+(date_raw or '')).encode()),
            'time_window_start':None,'time_window_end':None,
            'time_window_note':'RSS does not state a measurement-window boundary; pubDate is preserved without treating it as monthly/day volume.'})
    if not records or any(not r['query'] for r in records):
        raise ValueError('empty feed or missing query titles')
    write(run/'trends.normalized.json',records)
    with (run/'trends.normalized.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    topics = json.loads(TOPICS.read_text())
    with SEEDS.open(newline='') as f:
        seeds = list(csv.DictReader(f))
    comparisons = []
    for topic in topics:
        topic_seeds = [s['keyword'] for s in seeds if s['topic_id']==topic['id']]
        exact = []
        lexical = []
        for record in records:
            for seed in topic_seeds:
                if norm(record['query']) == norm(seed):
                    exact.append({'query':record['query'],'seed':seed,'record_id':record['record_id']})
            for alias in ALIASES.get(topic['id'],[]):
                if contains(record['query'],alias):
                    lexical.append({'query':record['query'],'alias':alias,'record_id':record['record_id'],'status':'lexical_candidate_needs_context_review'})
        comparisons.append({'topic_id':topic['id'],'name_ru':topic['name_ru'],'keywords_compared':len(topic_seeds),
            'exact_seed_matches':exact,'lexical_candidates':lexical,
            'demand_status':'not_estimated_from_trending_sample','monthly_searches':None,'demand_rank':None,
            'absence_means_no_demand':False})
    write(run/'topic-comparison.json',comparisons)
    write(run/'topic-aliases.json',ALIASES)
    dates=sorted(r['pub_date_utc'] for r in records if r['pub_date_utc'])
    files=[]
    for p in sorted(run.iterdir()):
        if p.is_file():files.append({'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
    manifest={'status':'collected_public_trending_snapshot','started_at':started,'completed_at':now(),
        'source_url':URL,'source_owner':'Google Trends','source_geo':'US','feed_channel_title':channel.findtext('title'),
        'feed_channel_link':channel.findtext('link'),'feed_channel_pub_date':channel.findtext('pubDate'),
        'channel_last_build_date':channel.findtext('lastBuildDate'),'records':len(records),
        'distinct_query_titles':len({r['query'] for r in records}),'pub_date_min_utc':dates[0] if dates else None,
        'pub_date_max_utc':dates[-1] if dates else None,'supplied_traffic_field':'ht:approx_traffic',
        'traffic_bucket_counts':dict(collections.Counter(r['approx_traffic_raw'] for r in records)),
        'topics_compared':len(comparisons),'keywords_compared':len(seeds),
        'topics_with_exact_seed_matches':sum(bool(x['exact_seed_matches']) for x in comparisons),
        'topics_with_lexical_candidates':sum(bool(x['lexical_candidates']) for x in comparisons),
        'seed_file_sha256':sha(SEEDS.read_bytes()),'topics_file_sha256':sha(TOPICS.read_bytes()),
        'collector_sha256':sha(Path(__file__).read_bytes()),'sample_complete_market_demand':False,
        'monthly_keyword_volume_available':False,'causal_or_correlational_analysis_performed':False,
        'definition_reference':'https://support.google.com/trends/answer/3076011?hl=en',
        'access_gap_reference':'https://developers.google.com/search/apis/trends',
        'caveats':['Trending queries are a selected surge/news signal, not all American searches.',
            'Traffic is an approximate displayed bucket for a trend which may group related queries.',
            'RSS pubDate boundaries are not asserted to be volume-window boundaries.',
            'No presence/absence or ranking conclusions for all20atlas topics follow from one snapshot.'],
        'files':files}
    write(run/'manifest.json',manifest)
    write(BASE/'latest.json',{'run':str(run.relative_to(BASE)),**manifest})
    print(json.dumps(manifest,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
