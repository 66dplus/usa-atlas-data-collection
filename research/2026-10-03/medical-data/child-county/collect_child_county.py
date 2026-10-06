#!/usr/bin/env python3
"""Download official CHR observed child mortality sources. Standard library only."""
import argparse, concurrent.futures, csv, datetime, hashlib, io, json, re, threading, urllib.request, urllib.error
from pathlib import Path
P=Path(__file__).resolve().parent;R=P/'raw';R.mkdir(parents=True,exist_ok=True)
BASE='https://www.countyhealthrankings.org'
URLS={
 'chr2023-analytic.csv':BASE+'/sites/default/files/media/document/analytic_data2023_0.csv',
 'chr2025-analytic.csv':BASE+'/sites/default/files/media/document/analytic_data2025_v3.csv',
 'chr2026-supplement.csv':BASE+'/sites/default/files/media/document/analytic_supplement_20260325%5B1%5D.csv',
 'chr2023-analytic-codebook.pdf':BASE+'/sites/default/files/media/document/2023%20Analytic%20Documentation_0.pdf',
 'chr2026-supplement-codebook.pdf':BASE+'/sites/default/files/media/document/Analytic_Dataset_Codebook_Supplemental_Release_20260325%5B1%5D.pdf',
 'child-mortality-method.html':BASE+'/health-data/population-health-and-well-being/length-of-life/life-span/child-mortality',
 'chr2024-measure-changes.pdf':BASE+'/sites/default/files/media/document/Measure%20Changes%20%282023-2024%29_0.pdf',
 'chr2025-working-paper.pdf':BASE+'/sites/default/files/media/document/Working%20Paper%20CHRR%202025.pdf',
 'chr2025-technical-document.pdf':BASE+'/sites/default/files/media/document/CHRR%20Technical%20Documentation%202025_2.pdf',
 'current-data-index.html':BASE+'/health-data/methodology-and-sources/data-documentation',
 'historical-data-index.html':BASE+'/health-data/methodology-and-sources/data-documentation/national-data-documentation-2010-2023',
}
LOCK=threading.Lock()
def fetch(item):
 name,url=item;rec={'file':'raw/'+name,'url':url,'accessed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'USAAtlasResearch/1.0 (public aggregate data collection)'})
  with urllib.request.urlopen(req,timeout=45) as response:
   data=response.read();rec.update({'http_status':response.status,'final_url':response.url,'content_type':response.headers.get('Content-Type'),'last_modified':response.headers.get('Last-Modified'),'etag':response.headers.get('ETag'),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()});(R/name).write_bytes(data)
  rec['status']='downloaded'
 except Exception as e:rec.update({'status':'failed','error':str(e),'http_status':e.code if isinstance(e,urllib.error.HTTPError) else None})
 with LOCK:
  with (P/'http-receipts.jsonl').open('a') as f:f.write(json.dumps(rec)+'\n')
 print(json.dumps({k:rec.get(k) for k in ['file','status','http_status','bytes','error']}),flush=True)
 return rec
def numeric(raw):
 raw=raw.strip()
 if not raw or raw in ['NA','N/A','.']: return None
 try:
  value=float(raw)
  return int(value) if value.is_integer() else value
 except ValueError: return None

def normalize():
 receipts={r['file']:r for r in [json.loads(line) for line in (P/'http-receipts.jsonl').read_text().splitlines()] if r['status']=='downloaded'}
 cfgs=[('chr2023-analytic.csv','2023',17,'2017-2020','NCHS_Bridged_Race_Population_Estimates'),('chr2025-analytic.csv','2025',19,'2019-2022','Census_PEP_and_NCHS_natality_infant_approximation'),('chr2026-supplement.csv','2026-03-25',19,'2020-2023','Census_PEP_and_NCHS_natality_infant_approximation')]
 wide=[];observations=[];summary={};boundaries=[]
 for filename,release,age_max,period,den_source in cfgs:
  with (R/filename).open(encoding='utf-8-sig',newline='') as f:
   # Annual analytic files have a human header followed by a variable-code header.
   if filename!='chr2026-supplement.csv':next(f)
   rows=list(csv.DictReader(f))
  rec=receipts['raw/'+filename];county_rows=[r for r in rows if r['countycode']!='000'];numeric_count=0
  for r in county_rows:
   geoid=r['fipscode'].zfill(5);rate=numeric(r['v128_rawvalue']);num=numeric(r['v128_numerator']);den=numeric(r['v128_denominator']);low=numeric(r['v128_cilow']);high=numeric(r['v128_cihigh']);geo_type='county'
   boundary='source_release_geography_no_reallocation'
   if r['state']=='CT':boundary='CT_former_county' if int(r['countycode'])<100 else 'CT_planning_region'
   if r['state']=='AK':boundary='Alaska_source_release_county_equivalent_boundaries'
   status='numeric' if rate is not None else 'missing_or_suppressed'
   numeric_count+=rate is not None
   reason='Published blank; CHR suppresses mortality when fewer than 10 deaths, but blank alone does not establish an exact death count.' if rate is None else ''
   if r['state']=='CT' and rate is None:reason='Connecticut geography unavailable for this measure/release; former counties and planning regions differ. Do not infer zero or suppression alone.'
   calc=num/den*100000 if num is not None and den else None
   base={'geoid':geoid,'source_geoid':geoid,'geography_level':'county','geography_name':r['county'],'state_code':r['state'],'boundary_status':boundary,'release':release,'period':period,'age_group':f'0-{age_max}','age_min':0,'age_max':age_max,'includes_infants':True,'age_adjustment':'crude_not_age_adjusted','sex':'both','race_ethnicity':'all','data_type':'observed_registered_deaths_with_population_estimate_denominator','numerator':num,'denominator_population':den,'denominator':'sum_of_annual_resident_population_in_age_group_across_four_years','denominator_unit':'person_years_sum_of_annual_population_estimates','denominator_source':den_source,'source_url':rec['url'],'source_file':'child-county/raw/'+filename,'source_sha256':rec['sha256'],'accessed_at':rec['accessed_at'],'source_value_text':r['v128_rawvalue'],'source_suppression_code':'blank' if rate is None else '', 'suppression_reason':reason,'geography_compatibility':boundary,'production_ready':False,'preliminary':False,'universe':f'All-cause registered deaths among residents ages0-{age_max}, county of residence; four-year pooled count divided by summed annual population estimates.'}
   w={**base,'rate_per_100000_per_year':rate,'published_death_count':num,'lower_95_ci':low,'upper_95_ci':high,'value_status':status,'rate_recomputed_from_published_num_den':calc,'rate_recompute_absolute_difference':abs(calc-rate) if calc is not None and rate is not None else None,'source_fields':{'rate':'v128_rawvalue','death_count':'v128_numerator','denominator':'v128_denominator','lower_ci':'v128_cilow','upper_ci':'v128_cihigh'},'all_source_measure_values':{k:v for k,v in r.items() if k.startswith('v128_')}}
   wide.append(w)
   for suffix,value,unit,rawvalue,cilow,cihigh in [('rate',rate,'deaths_per_100000_age_group_population_per_year',r['v128_rawvalue'],low,high),('count',num,'registered_deaths_over_four_year_period',r['v128_numerator'],None,None)]:
    ob={**base,'metric_id':f'child_mortality_under{age_max+1}_{suffix}','unit':unit,'value':value,'value_status':'numeric' if value is not None else 'missing_or_suppressed','lower_95_ci':cilow,'upper_95_ci':cihigh,'source_value_text':rawvalue}
    observations.append(ob)
   if r['state'] in ['CT','AK']:boundaries.append({'release':release,'geoid':geoid,'state':r['state'],'name':r['county'],'boundary_status':boundary,'value_status':status,'rate':rate})
  summary[release]={'age_group':f'0-{age_max}','period':period,'county_geography_rows':len(county_rows),'county_numeric_rates':numeric_count,'county_missing_rates':len(county_rows)-numeric_count,'state_numeric_rates':sum(numeric(r['v128_rawvalue']) is not None for r in rows if r['countycode']=='000' and r['state']!='US'),'national_row_retained_in_raw_only':True,'ct_numeric_geographies':[{ 'geoid':r['fipscode'],'name':r['county'],'rate':numeric(r['v128_rawvalue'])} for r in county_rows if r['state']=='CT' and numeric(r['v128_rawvalue']) is not None]}
 (P/'county-observations.json').write_text(json.dumps({'schema_version':1,'production_admitted':False,'as_of':'2026-10-03','county_observations':wide},ensure_ascii=False,indent=2)+'\n')
 (P/'observations.json').write_text(json.dumps({'schema_version':1,'as_of':'2026-10-03','observations':observations},ensure_ascii=False,indent=2)+'\n')
 for fn,data in [('observations.csv',observations),('county-observations.csv',wide)]:
  # Rich source subgroup cells remain in JSON; CSV preserves scalar columns.
  cols=sorted({k for r in data for k,v in r.items() if not isinstance(v,(dict,list))})
  with (P/fn).open('w',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');writer.writeheader();writer.writerows(data)
 (P/'coverage-local.json').write_text(json.dumps({'as_of':'2026-10-03','series':summary,'numeric_observations':sum(r['value_status']=='numeric' for r in observations),'all_county_observation_rows':len(observations),'no_subcounty_values':True,'no_age_range_substitution':True},ensure_ascii=False,indent=2)+'\n')
 (P/'boundary-observations.json').write_text(json.dumps(boundaries,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--fetch',action='store_true');parser.add_argument('--normalize',action='store_true');parser.add_argument('--fetch-missing',action='store_true');args=parser.parse_args()
 if args.fetch or args.fetch_missing:
  selected={k:v for k,v in URLS.items() if args.fetch or not (R/k).exists()}
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(fetch,selected.items()))
  latest_receipts={r['file']:r for r in (json.loads(line) for line in (P/'http-receipts.jsonl').read_text().splitlines())}
  (P/'download-summary.json').write_text(json.dumps(list(latest_receipts.values()),indent=2)+'\n')

 if args.normalize: normalize()
