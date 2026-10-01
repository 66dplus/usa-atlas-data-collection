#!/usr/bin/env python3
"""One bounded unauthenticated public Google Trends Explore comparison; never bypass access controls."""
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

BASE=Path(__file__).resolve().parent
KEYWORDS=['data center','electricity rates','water shortage','overdose']
REQUEST={'comparisonItem':[{'keyword':k,'geo':'US','time':'today 12-m'} for k in KEYWORDS], 'category':0,'property':''}

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,j):p.write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n')

def main():
    run=BASE/'explore-attempts'/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run.mkdir(parents=True)
    receipts=[]
    manifest={'started_at':now(),'status':'requesting_public_explore','keywords':KEYWORDS,'request':REQUEST,
       'official_ui_url':'https://trends.google.com/trends/explore?'+urllib.parse.urlencode({'geo':'US','q':','.join(KEYWORDS),'date':'today 12-m'}),
       'authorization_used':False,'proxy_or_access_bypass_used':False,'maximum_requests':2,
       'collector_sha256':sha(Path(__file__).read_bytes()),'measurement':'relative_search_interest_not_absolute_search_volume'}
    write(run/'manifest.json',manifest)
    def get(name,url):
        record={'name':name,'requested_at':now(),'url':url}
        body=None
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'USA-Atlas-public-demand-research/1.0','Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=30) as response:
                record.update(status=response.status,final_url=response.url,content_type=response.headers.get('Content-Type'),http_date=response.headers.get('Date'))
                body=response.read(2_000_001)
            if len(body)>2_000_000:raise ValueError('response exceeds2MB')
            text=body.decode('utf-8')
            if text.startswith(")]}'"):
                text=text.split('\n',1)[1]
            data=json.loads(text)
            record['result']='received'
        except Exception as exc:
            data=None
            record.update(result='error',error=f'{type(exc).__name__}: {exc}')
            if isinstance(exc,urllib.error.HTTPError):
                record.update(status=exc.code,retry_after=exc.headers.get('Retry-After'),content_type=exc.headers.get('Content-Type'))
                body=exc.read(200000)
        if body is not None:
            (run/(name+'.raw')).write_bytes(body)
            record.update(bytes=len(body),response_sha256=sha(body),raw_file=name+'.raw')
        record['completed_at']=now();receipts.append(record);write(run/'receipts.json',receipts)
        return data
    explore=get('explore','https://trends.google.com/trends/api/explore?'+urllib.parse.urlencode({'hl':'en-US','tz':'0','req':json.dumps(REQUEST,separators=(',',':'))}))
    if explore is None:
        manifest.update(status='public_explore_unavailable',failure=receipts[-1],blocked_requests_not_retried=True)
    else:
        widget=next((w for w in explore.get('widgets',[]) if w.get('id')=='TIMESERIES'),None)
        if not widget or not widget.get('token') or not widget.get('request'):
            manifest.update(status='no_public_timeseries_widget',response_keys=list(explore))
        else:
            # The token is supplied by this public query response, not an account credential.
            series=get('multiline','https://trends.google.com/trends/api/widgetdata/multiline?'+urllib.parse.urlencode({
                'hl':'en-US','tz':'0','req':json.dumps(widget['request'],separators=(',',':')),'token':widget['token']}))
            if series is None:
                manifest.update(status='public_multiline_unavailable',failure=receipts[-1],blocked_requests_not_retried=True)
            else:
                timeline=series.get('default',{}).get('timelineData',[])
                rows=[]
                for point in timeline:
                    values=point.get('value',[])
                    if len(values)!=len(KEYWORDS):raise ValueError('Series width differs from requested4keywords')
                    for i,keyword in enumerate(KEYWORDS):
                        rows.append({'keyword':keyword,'geo':'US','time_epoch':point.get('time'),
                            'formatted_time':point.get('formattedTime'),'value_0_100':values[i],
                            'has_data':point.get('hasData',[None]*len(KEYWORDS))[i],
                            'is_partial':point.get('isPartial',False),'monthly_searches':None})
                write(run/'timeseries.normalized.json',rows)
                if rows:
                    with (run/'timeseries.normalized.csv').open('w',newline='') as f:
                        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
                manifest.update(status='collected_relative_interest_timeseries' if rows else 'empty_public_timeseries',
                    time_points=len(timeline),normalized_rows=len(rows),
                    returned_request=widget['request'],window_start_epoch=timeline[0].get('time') if timeline else None,
                    window_end_epoch=timeline[-1].get('time') if timeline else None,
                    scale_note='Google normalized0..100 within this shared comparison; zero may represent low volume, not absence of searches.')
    manifest.update(completed_at=now(),http_requests=len(receipts),monthly_keyword_volume_available=False)
    write(run/'manifest.json',manifest);write(BASE/'explore-latest.json',{'run':str(run.relative_to(BASE)),**manifest})
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['failure','returned_request']},indent=2))
    if 'failure' in manifest:print('HTTP outcome:',manifest['failure'].get('status'),manifest['failure'].get('error'))

if __name__=='__main__':main()
