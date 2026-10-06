#!/usr/bin/env python3
"""Bounded public RSS/Atom metadata monitoring; never archives article bodies."""
import argparse
import datetime as dt
import email.utils
import fcntl
import hashlib
import html
import json
from pathlib import Path
import re
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET

BASE=Path(__file__).resolve().parent
UA='USA-Atlas-Source-Monitor/1.0'
TOPICS={'migration':['migration','moving','move to','moves to','relocat','leaving','population growth','population decline'],
 'wealth_moves':['billionaire','millionaire','wealth','bezos','musk','headquarters'],
 'taxes':['tax','capital gains','property taxes'],'housing':['housing','rent','home price','affordable','mortgage'],
 'jobs':['jobs','jobless','employment','unemployment','layoff','wage','manufactur'],
 'datacenters':['data center','data centre','datacenter','ai infrastructure','ai campus'],
 'income':['income','earnings','poverty'],'electricity':['electricity','energy demand','power grid']}
STATES=dict(zip(['Alabama','Alaska','Arizona','Arkansas','California','Colorado','Connecticut','Delaware','Florida','Georgia','Hawaii','Idaho','Illinois','Indiana','Iowa','Kansas','Kentucky','Louisiana','Maine','Maryland','Massachusetts','Michigan','Minnesota','Mississippi','Missouri','Montana','Nebraska','Nevada','New Hampshire','New Jersey','New Mexico','New York','North Carolina','North Dakota','Ohio','Oklahoma','Oregon','Pennsylvania','Rhode Island','South Carolina','South Dakota','Tennessee','Texas','Utah','Vermont','Virginia','Washington','West Virginia','Wisconsin','Wyoming'],['AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY']))
TRACKING={'fbclid','gclid','mc_cid','mc_eid','cmpid','ref','smid','ocid'}
ATOM='{http://www.w3.org/2005/Atom}'


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(payload): return hashlib.sha256(payload).hexdigest()
def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)

def normalize_url(value,base):
 parsed=urllib.parse.urlsplit(urllib.parse.urljoin(base,value.strip()))
 if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
  return None
 query=[(k,v) for k,v in urllib.parse.parse_qsl(parsed.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in TRACKING]
 return urllib.parse.urlunsplit((parsed.scheme.lower(),parsed.netloc.lower(),parsed.path or '/',urllib.parse.urlencode(sorted(query)),''))

def fetch(url,deadline,max_bytes,headers=None):
 receipt={'url':url,'started_at':now(),'request_user_agent':UA}
 data=None
 try:
  seconds=min(15,max(1,deadline-time.monotonic()))
  request=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/rss+xml,application/atom+xml,text/plain,application/xml;q=.9,*/*;q=.1',**(headers or {})})
  with urllib.request.urlopen(request,timeout=seconds) as response:
   receipt.update(http_status=response.status,final_url=response.url,content_type=response.headers.get('Content-Type'),etag=response.headers.get('ETag'),last_modified=response.headers.get('Last-Modified'),http_date=response.headers.get('Date'))
   chunks=[];size=0
   while True:
    if time.monotonic()>=deadline: raise TimeoutError('global collection time budget reached')
    chunk=response.read(min(65536,max_bytes+1-size))
    if not chunk: break
    chunks.append(chunk);size+=len(chunk)
    if size>max_bytes: raise ValueError('response exceeds configured size limit')
   data=b''.join(chunks);receipt.update(result='received',bytes=len(data),sha256=sha(data))
 except urllib.error.HTTPError as exc:
  receipt.update(result='http_error',http_status=exc.code,final_url=exc.url,retry_after=exc.headers.get('Retry-After'))
  body=exc.read(min(max_bytes,8192));receipt.update(bytes_read=len(body),sha256_of_read_bytes=sha(body),body_archived=False)
 except (OSError,ValueError,TimeoutError) as exc:
  receipt.update(result='error',error_type=type(exc).__name__,error=str(exc))
 receipt['completed_at']=now()
 return data,receipt

def robot_check(feed_url,deadline,cache,receipts):
 p=urllib.parse.urlsplit(feed_url);url=urllib.parse.urlunsplit((p.scheme,p.netloc,'/robots.txt','',''))
 if url not in cache:
  body,receipt=fetch(url,deadline,250000);receipt['kind']='robots';receipts.append(receipt)
  parser=urllib.robotparser.RobotFileParser(url)
  if receipt.get('http_status')==404:
   parser.parse([]);result={'status':'no_robots_file_404','url':url,'http_status':404,'note':'This feed host returned404 for robots.txt; this is an observed endpoint status, not article-reuse permission.'}
  elif body is not None and receipt.get('http_status')==200:
   parser.parse(body.decode('utf-8',errors='replace').splitlines());result={'status':'parsed','url':url,'http_status':200,'sha256':receipt['sha256'],'note':'Robots rules were evaluated for '+UA+' on the exact feed URL.'}
  else:
   parser=None;result={'status':'robots_unavailable','url':url,'http_status':receipt.get('http_status'),'note':'Robots could not be checked; collector does not fetch this feed until access is reviewed.'}
  cache[url]=(parser,result)
 parser,result=cache[url];result=dict(result)
 allowed=parser.can_fetch(UA,feed_url) if parser else False
 result['can_fetch_feed']=allowed
 result['crawl_delay_seconds']=parser.crawl_delay(UA) if parser else None
 return allowed,result

def text(node,name):
 found=node.find(name)
 return ' '.join(''.join(found.itertext()).split()) if found is not None else None

def parse_date(value):
 if not value: return None
 try: parsed=email.utils.parsedate_to_datetime(value)
 except (TypeError,ValueError):
  try: parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
  except ValueError: return None
 if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=dt.timezone.utc)
 return parsed.astimezone(dt.timezone.utc).isoformat()

def classify_title(headline):
 lowered=headline.casefold()
 matched=[tag for tag,terms in TOPICS.items() if any(re.search(r'(?<!\w)'+re.escape(term)+r'\w*(?!\w)',lowered) for term in terms)]
 geography=[];spans=[]
 for state_name,code in sorted(STATES.items(),key=lambda item:len(item[0]),reverse=True):
  for match in re.finditer(r'(?<!\w)'+re.escape(state_name.casefold())+r'(?!\w)',lowered):
   if not any(match.start()>=a and match.end()<=b for a,b in spans): geography.append(code);spans.append(match.span())
 return matched,sorted(set(geography))

def parse_feed(payload,source,feed_url,max_items):
 if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper(): raise ValueError('XML entity declarations are unsupported')
 root=ET.fromstring(payload)
 if root.tag=='rss':
  channel=root.find('channel')
  if channel is None: raise ValueError('RSS channel is missing')
  nodes=root.findall('./channel/item');title=text(channel,'title')
 elif root.tag==ATOM+'feed': nodes=root.findall(ATOM+'entry');title=text(root,ATOM+'title')
 else: raise ValueError('response is neither RSS2.0 nor Atom')
 leads=[]
 for node in nodes[:max_items]:
  is_atom=root.tag==ATOM+'feed'
  headline=text(node,ATOM+'title' if is_atom else 'title')
  if is_atom:
   links=[e.attrib.get('href') for e in node.findall(ATOM+'link') if e.attrib.get('rel','alternate')=='alternate'];url=links[0] if links else None
  else:
   url=text(node,'link')
   if not url:
    guid=node.find('guid')
    if guid is not None and guid.attrib.get('isPermaLink','true')!='false': url=guid.text
  if not url: continue
  url=normalize_url(url,feed_url)
  if not headline or not url: continue
  # Prefixes retain inflected words, but migration must not match immigration.
  matched,geography=classify_title(headline)
  published=text(node,ATOM+'published' if is_atom else 'pubDate') or text(node,ATOM+'updated' if is_atom else '{http://purl.org/dc/elements/1.1/}date')
  leads.append({'lead_id':'lead-'+sha(url.encode())[:20],'title':html.unescape(headline)[:500],'url':url,'url_resolution_status':'normalized_feed_link_redirects_not_resolved','publisher':source['publisher'],'source_ids':[source['id']],'feed_url':feed_url,'source_role':source['source_role'],'published_at':parse_date(published),'published_at_supplied':published,'first_seen':now(),'last_seen':now(),'topic_tags_matched_in_title':matched,'geography_candidates_from_title':sorted(set(geography)),'geography_match_status':'lexical_candidates_only; Washington may mean DC; publisher geography is not article geography','publisher_geography_hint':source['geography'],'verification_status':'unreviewed_lead','article_body_archived':False,'description_archived':False,'next_action':'Open original source, resolve publisher URL, identify claim/date/geography, verify against primary dataset; create story only after review.'})
 if not leads: raise ValueError('no usable title/link records in feed')
 return title,leads,len(nodes)

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--source',action='append',default=[])
 parser.add_argument('--limit',type=int,default=8)
 parser.add_argument('--max-items',type=int,default=80)
 parser.add_argument('--max-bytes',type=int,default=2000000)
 parser.add_argument('--budget-seconds',type=int,default=240)
 parser.add_argument('--force',action='store_true',help='Ignore due date; never bypass robots/access errors.')
 args=parser.parse_args()
 if not 1<=args.limit<=24 or not 1<=args.max_items<=200 or not 10000<=args.max_bytes<=5000000 or not 30<=args.budget_seconds<=600: parser.error('parameters outside bounded collector limits')
 with (BASE/'.collection.lock').open('a+') as lock:
  try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError: print(json.dumps({'status':'already_running'}));return 0
  registry=json.loads((BASE/'registry.json').read_text());known={s['id'] for s in registry['sources']}
  if set(args.source)-known: parser.error('unknown source ID')
  selected=[s for s in registry['sources'] if s['access_method']=='rss_metadata' and (not args.source or s['id'] in args.source)]
  if not args.force: selected=[s for s in selected if not s.get('next_refresh') or dt.datetime.fromisoformat(s['next_refresh'])<=dt.datetime.now(dt.timezone.utc)]
  selected.sort(key=lambda s:s.get('last_checked') or '')
  selected=selected[:args.limit]
  run_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');run=BASE/'snapshots'/run_id;run.mkdir(parents=True)
  started=now();deadline=time.monotonic()+args.budget_seconds;receipts=[];results=[];new_leads={};robot_cache={}
  interrupted=False
  def alarm(_signum,_frame): raise TimeoutError('whole-run time budget reached')
  old=signal.signal(signal.SIGALRM,alarm);signal.alarm(args.budget_seconds)
  try:
   for source in selected:
    if time.monotonic()>=deadline: interrupted=True;break
    url=source['feed_urls'][0];source['last_checked']=now()
    source['next_refresh']=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=source['refresh_interval_hours'])).isoformat()
    result={'source_id':source['id'],'feed_url':url,'started_at':source['last_checked']}
    try:
     allowed,robots=robot_check(url,deadline,robot_cache,receipts);source['robots_notes']=robots
     if not allowed:
      result.update(status='robots_disallowed' if robots['status']=='parsed' else 'robots_unavailable',records=0)
     else:
      delay=robots.get('crawl_delay_seconds') or 0
      if delay:
       if time.monotonic()+delay>=deadline: raise TimeoutError('crawl delay exceeds remaining run budget')
       time.sleep(delay)
      payload,receipt=fetch(url,deadline,args.max_bytes);receipt.update(kind='feed',source_id=source['id'],body_archived=False);receipts.append(receipt)
      if payload is None: result.update(status='feed_unavailable',http_status=receipt.get('http_status'),records=0)
      else:
       title,leads,total=parse_feed(payload,source,url,args.max_items)
       for lead in leads:
        if lead['url'] in new_leads:
         new_leads[lead['url']]['source_ids']=sorted(set(new_leads[lead['url']]['source_ids']+lead['source_ids']))
        else: new_leads[lead['url']]=lead
       result.update(status='collected',channel_title=title,records=len(leads),feed_items_available=total,items_truncated=total>args.max_items,bytes=receipt['bytes'],sha256=receipt['sha256'],http_status=receipt['http_status'])
    except (ValueError,ET.ParseError,TimeoutError) as exc:
     result.update(status='parse_or_budget_error',error=str(exc),records=0)
    source['collector_status']=result['status'];result['completed_at']=now();results.append(result)
    # Explicit access denials are revisited less often, not retried in a tight loop.
    if result.get('http_status') in {401,403,429}:
     source['next_refresh']=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=72)).isoformat()
    write(run/'receipts.json',receipts);write(run/'source-results.json',results);write(BASE/'registry.json',registry)
  except TimeoutError:
   interrupted=True
  finally:
   signal.alarm(0);signal.signal(signal.SIGALRM,old)
  existing=json.loads((BASE/'leads.json').read_text()) if (BASE/'leads.json').exists() else []
  library={lead['url']:lead for lead in existing}
  for url,lead in new_leads.items():
   if url in library:
    lead['first_seen']=library[url]['first_seen'];lead['source_ids']=sorted(set(library[url]['source_ids']+lead['source_ids']))
   library[url]=lead
  merged=sorted(library.values(),key=lambda x:x['last_seen'],reverse=True)[:20000]
  for lead in merged:
   lead['topic_tags_matched_in_title'],lead['geography_candidates_from_title']=classify_title(lead['title'])
   lead.setdefault('url_resolution_status','normalized_feed_link_redirects_not_resolved')
   lead['geography_match_status']='lexical_candidates_only; Washington may mean DC; publisher geography is not article geography'
   lead['classification_version']='1.1'
  candidates=[lead for lead in new_leads.values() if lead['topic_tags_matched_in_title']]
  write(run/'leads.json',list(new_leads.values()));write(run/'story-candidates.json',candidates);write(BASE/'leads.json',merged)
  manifest={'run_id':run_id,'status':'budget_exhausted' if interrupted else 'completed','started_at':started,'completed_at':now(),'selected_sources':[s['id'] for s in selected],'source_results':results,'unique_leads_this_run':len(new_leads),'topic_matched_candidates_this_run':len(candidates),'cumulative_unique_leads':len(merged),'failed_or_blocked_sources':[r['source_id'] for r in results if r['status']!='collected'],'raw_article_or_feed_archive':False,'run_directory':str(run.relative_to(BASE)),'artifacts':{name:{'bytes':(run/name).stat().st_size,'sha256':sha((run/name).read_bytes())} for name in ['receipts.json','source-results.json','leads.json','story-candidates.json'] if (run/name).exists()}}
  write(run/'manifest.json',manifest);write(BASE/'latest.json',manifest);print(json.dumps(manifest,ensure_ascii=False))
  return 0 if any(r['status']=='collected' for r in results) else 1

if __name__=='__main__':
 raise SystemExit(main())
