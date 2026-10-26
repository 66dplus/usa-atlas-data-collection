"""Deterministic candidate preparation from existing local research inputs."""
import csv, hashlib, json, os, pathlib, sys, shutil, subprocess
ROOT=pathlib.Path('/Users/dmitrijrybkin/Documents/USA-MAPS/research/data-collection/research/2026-10-25/politics-native')
OUT=pathlib.Path('/tmp/usa-maps-data-flow-20261026/reader-results')
_BOUNDARY_FILE=pathlib.Path('/tmp/usa-maps-data-flow-20261026/boundary/cd119.geojson')
_AT_LARGE_STATES=set()
if _BOUNDARY_FILE.exists():
 _AT_LARGE_STATES={f['properties']['STATEFP'] for f in json.loads(_BOUNDARY_FILE.read_text())['features'] if f['properties'].get('CD119FP')=='00'}
SOURCES={
 'president':('raw/president_county_2000_2024.csv','9299583148f5f8264baf50b5d929c260699c46d915909b13ea3c3850918946f8','12.01'),
 'senate':('raw/senate_state_1976_2024.csv','d4492e286046f73b111cf5706ee02be4c305897898317818afd06c0ac8a464e0','12.02'),
 'house':('raw/house_district_1976_2024.csv','bd0690fbcd753e45edb40810c99d1b8afbb0de928aa54bff1b227c615d69c163','12.03')}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def padded(value,width):
 try: return str(int(float(str(value)))) .zfill(width)
 except (TypeError,ValueError): return str(value or '').strip().zfill(width)
def geo(r,office):
 if office=='president':
  gid=padded(r.get('county_fips'),5); return ('county',gid,gid[:2],None,None,False)
 if office=='senate':
  sid=padded(r.get('state_fips'),2); return ('state',sid,sid,None,None,False)
 sid=padded(r.get('state_fips'),2); district=padded(r.get('district'),2); year=int(r.get('year') or 0)
 is_special=str(r.get('special','False')).lower()=='true'; stage=(r.get('stage') or 'GEN').upper()
 vintage,session=(2024,'119') if year==2024 and stage=='GEN' and not is_special else (None,None)
 if vintage and sid in _AT_LARGE_STATES: district='00'
 return ('congressional_district',sid+district,sid,district,vintage, district=='00')
def norm_party(s):
 s=(s or '').strip().upper()
 if s in {'DEMOCRAT','DEMOCRATIC'}: return 'DEMOCRAT'
 if s in {'REPUBLICAN','GOP'}: return 'REPUBLICAN'
 if s in {'LIBERTARIAN','GREEN','INDEPENDENT','OTHER'}: return s
 return s or None
def run():
 OUT.mkdir(parents=True,exist_ok=True); inventory={'status':'candidate_not_admitted','fields':{'AIAN':'01.04','president':'12.01','senate':'12.02','house':'12.03'},'sources':{},'outputs':{}}
 for office,(rel,expected,field) in SOURCES.items():
  p=ROOT/rel
  if sha(p)!=expected: raise ValueError(f'source SHA256 mismatch: {office}')
  delimiter='\t' if office=='senate' else ','
  with p.open(newline='',encoding='utf-8-sig') as f:
   if office=='house':
    header=next(csv.reader([next(f)],delimiter=delimiter)); rows=[]
    for line in f:
     text=line.rstrip('\r\n')
     if text.startswith('"') and text.endswith('"'): text=text[1:-1]
     values=next(csv.reader([text],delimiter=delimiter))
     rows.append(dict(zip(header,values)))
   else: rows=list(csv.DictReader(f,delimiter=delimiter))
  # Fail closed on same-contest candidate repeats and fusion tickets; totals are checked as a set, never summed.
  def ckey(r):
   return (r.get('year'),r.get('state_fips') or r.get('state_po'),r.get('county_fips') or r.get('district') or r.get('state_po'),(r.get('stage') or 'GEN').upper(),str(r.get('special','False')).lower(),str(r.get('runoff','False')).lower(),(r.get('mode') or 'TOTAL').upper(),r.get('version'))
  groups={}
  for r in rows: groups.setdefault(ckey(r),[]).append(r)
  diagnostics=[]; quarantined={}
  for key,items in groups.items():
   candidates={}
   totals=set()
   for r in items:
    cand=(r.get('candidate') or '').strip().upper(); party=norm_party(r.get('party') or r.get('party_detailed') or r.get('party_simplified'))
    if cand and cand not in {'TOTAL VOTES CAST','UNDERVOTES','OVERVOTES'}: candidates.setdefault((cand,party),[]).append(r)
    totals.add((r.get('totalvotes') or '').strip())
   reasons=[]
   if any(str(r.get('fusion_ticket','False')).lower()=='true' for r in items): reasons.append('fusion_ticket_requires_review')
   if any(len(v)>1 for v in candidates.values()): reasons.append('repeated_candidate_row')
   if len(totals)>1: reasons.append('inconsistent_repeated_totalvotes')
   diagnostics.append({'contest_source_key':list(key),'result_mode':key[6],'row_count':len(items),'reported_total_votes_raw':next(iter(totals)) if len(totals)==1 else None,'party_aggregation_status':'quarantined' if reasons else 'not_evaluated','quarantine_reasons':reasons})
   for r in items: quarantined[id(r)]=reasons
  status_path=OUT/f'{office}_contest_review.jsonl'
  status_path.write_text(''.join(json.dumps(d,sort_keys=True)+'\n' for d in diagnostics))
  # Retain each original source row and make only conservative normalized fields.
  out=OUT/f'{office}_candidates.jsonl'; count=0
  with out.open('w',encoding='utf-8',newline='\n') as w:
   for n,r in enumerate(rows,1):
    party=r.get('party') or r.get('party_detailed') or r.get('party_simplified')
    candidate=(r.get('candidate') or '').strip()
    try: votes=int(float((r.get('candidatevotes') or '').strip()))
    except Exception: votes=None
    try: total=int(float((r.get('totalvotes') or '').strip()))
    except Exception: total=None
    gt,gid,state_fips,district_code,bv,atlarge=geo(r,office)
    row={'field_id':field,'office':office,'source_row_id':str(n),'geography_type':gt,'geo_id':gid,'state_fips':state_fips,'district_code':district_code,'boundary_vintage':bv,'congress_session':'119' if bv else None,'is_at_large':atlarge,'source_district_code':r.get('district'),'candidate_label':candidate,'candidate_kind':'candidate' if candidate and candidate.upper() not in {'TOTAL VOTES CAST','UNDERVOTES','OVERVOTES'} else 'source_aggregate','party_original':party,'party_normalized':norm_party(party),'candidatevotes_raw':r.get('candidatevotes'),'totalvotes_raw':r.get('totalvotes'),'candidate_votes':votes,'source_total_votes':total,'stage':r.get('stage') or 'GEN','is_special':str(r.get('special','False')).lower()=='true','is_runoff':str(r.get('runoff','False')).lower()=='true','result_mode':(r.get('mode') or 'TOTAL').upper(),'source_version':r.get('version'),'source_row':r,'quality_status':'invalid' if quarantined[id(r)] else 'observed','quarantine_reason':';'.join(quarantined[id(r)]) or None}
    w.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n'); count+=1
  inventory['sources'][office]={'path':str(p),'sha256':expected,'bytes':p.stat().st_size,'rows':len(rows)}
  inventory['outputs'][office]={'path':str(out),'sha256':sha(out),'rows':count}
  inventory['outputs'][office+'_contest_review']={'path':str(status_path),'sha256':sha(status_path),'contests':len(diagnostics),'quarantined':sum(d['party_aggregation_status']=='quarantined' for d in diagnostics)}
 # Explicit Senate 2024 schedule coverage; Class I states use the official Senate schedule.
 class_i={"AZ","CA","CT","DE","FL","HI","IN","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NJ","NM","NY","ND","OH","PA","RI","TN","TX","UT","VT","VA","WA","WV","WI","WY"}
 senate_src=ROOT/'raw/senate_state_1976_2024.csv'
 with senate_src.open(newline='',encoding='utf-8-sig') as f: sr=list(csv.DictReader(f,delimiter='\t'))
 seen={}
 for r in sr:
  if str(r.get('year'))=='2024':
   po=r.get('state_po'); key=(po,str(r.get('stage','GEN')).upper(),str(r.get('special','False')).lower()=='true',str(r.get('runoff','False')).lower()=='true')
   seen.setdefault(key,[]).append(r)
 # State FIPS set contains the 50 states; no DC/territory Senate rows are synthesized.
 fips={"AL":1,"AK":2,"AZ":4,"AR":5,"CA":6,"CO":8,"CT":9,"DE":10,"FL":12,"GA":13,"HI":15,"ID":16,"IL":17,"IN":18,"IA":19,"KS":20,"KY":21,"LA":22,"ME":23,"MD":24,"MA":25,"MI":26,"MN":27,"MS":28,"MO":29,"MT":30,"NE":31,"NV":32,"NH":33,"NJ":34,"NM":35,"NY":36,"NC":37,"ND":38,"OH":39,"OK":40,"OR":41,"PA":42,"RI":44,"SC":45,"SD":46,"TN":47,"TX":48,"UT":49,"VT":50,"VA":51,"WA":53,"WV":54,"WI":55,"WY":56}
 availability=[]
 for po,sid in sorted(fips.items(),key=lambda x:x[1]):
  if po in class_i:
   keys=[k for k in seen if k[0]==po]
   if not keys: availability.append({'field_id':'12.02','office':'senate','year':2024,'geo_type':'state','geo_id':f'{sid:02}','stage':'general','is_special':False,'is_runoff':False,'quality_status':'missing','source_release':'MEDSL prepared source','reason':'Official Class I schedule expects a contest but no 2024 candidate rows were found.'})
   for k in keys: availability.append({'field_id':'12.02','office':'senate','year':2024,'geo_type':'state','geo_id':f'{sid:02}','stage':k[1],'is_special':k[2],'is_runoff':k[3],'quality_status':'observed','source_release':'MEDSL prepared source','reason':'Candidate source rows present; contest quality is assessed separately.'})
  else: availability.append({'field_id':'12.02','office':'senate','year':2024,'geo_type':'state','geo_id':f'{sid:02}','stage':'general','is_special':False,'is_runoff':False,'quality_status':'no_election','source_release':'official Senate Class I schedule + MEDSL source','reason':'No regular Class I race and no 2024 special contest identified for this state.'})
 av=OUT/'senate_2024_availability.jsonl';av.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in availability))
 inventory['outputs']['senate_2024_availability']={'path':str(av),'sha256':sha(av),'rows':len(availability),'no_election':sum(r['quality_status']=='no_election' for r in availability),'missing':sum(r['quality_status']=='missing' for r in availability)}
 # ACS broad AIAN numerator and total population denominator from same ACS 2024 5-year table.
 for geography in ("state","county"):
  p=ROOT/f"raw/acs_2024_5yr_aian_{geography}.csv"
  expected={"state":"e86128465aa3ad35629c18062d381cb72132505cecaa5268443058f4ba363301","county":"ffbff1bf70d6cdd8af1e399f43e890a80349a53e9b3541bd1dd5b06e7e6c76a1"}[geography]
  if sha(p)!=expected: raise ValueError(f"ACS source SHA256 mismatch: {geography}")
  out=OUT/f"aian_{geography}.jsonl"
  with p.open(newline="",encoding="utf-8-sig") as f: rows=list(csv.DictReader(f))
  source_only={"02063","02066","09110","09120","09130","09140","09150","09160","09170","09180","09190"}
  with out.open("w",encoding="utf-8",newline="\n") as w:
   for r in rows:
    geoid=(r["state"]+r["county"]) if geography=="county" else r["state"]
    raw_n,raw_d=r.get("B02010_001E"),r.get("B01003_001E")
    try:
     n,d=int(raw_n),int(raw_d); good=n>=0 and d>0
    except (ValueError,TypeError): n=d=None;good=False
    if raw_n in {"-999999999","-888888888","-666666666"} or raw_d in {"-999999999","-888888888","-666666666"}: status="suppressed"; value=None
    elif raw_n is None or raw_d is None: status="missing";value=None
    elif not good: status="invalid";value=None
    else: status="observed";value=round(n/d*100,8)
    mapping="nonmapping_geography" if geography=="county" and geoid in source_only else "mapped"
    row={"field_id":"01.04","geography_type":geography,"geo_id":geoid,"period_kind":"multi_year","period_start_year":2020,"period_end_year":2024,"period_year":2024,"period_month":None,"raw_estimate":raw_n,"raw_estimate_moe":r.get("B02010_001M"),"raw_denominator":raw_d,"raw_denominator_moe":r.get("B01003_001M"),"value":value,"unit":"percent","quality_status":mapping if mapping!="mapped" and status=="observed" else status,"source_value_status":status,"geography_mapping_status":mapping,"source_sha256":sha(p),"overlap_note":"AIAN alone or in combination, all Hispanic origins; race responses overlap; shares do not sum to 100%. No derived ratio MOE."}
    w.write(json.dumps(row,sort_keys=True)+'\n')
  inventory['sources'][f"aian_{geography}"]={"path":str(p),"sha256":sha(p),"bytes":p.stat().st_size,"rows":len(rows)}
  inventory['outputs'][f"aian_{geography}"]={"path":str(out),"sha256":sha(out),"rows":len(rows)}
 # Import the already-downloaded official shape file through GDAL; no network access.
 geo_path=_BOUNDARY_FILE
 zip_path=pathlib.Path('/tmp/usa-maps-data-flow-20261026/cb_2024_us_cd119_500k.zip')
 if not geo_path.exists() and zip_path.exists():
  if not shutil.which('ogr2ogr'): raise RuntimeError('ogr2ogr is required to build candidate CD119 GeoJSON')
  geo_path.parent.mkdir(parents=True,exist_ok=True)
  subprocess.run(['ogr2ogr','-f','GeoJSON',str(geo_path),'/vsizip/'+str(zip_path),'-t_srs','EPSG:4326'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
 if geo_path.exists():
  data=json.loads(geo_path.read_text()); ids=[]
  for feature in data['features']:
   prop=feature['properties']; geom=json.dumps(feature.get('geometry'),sort_keys=True,separators=(',',':')).encode()
   ids.append({'geoid':prop.get('GEOID'),'state_fips':prop.get('STATEFP'),'district_code':prop.get('CD119FP'),'congress_session':str(prop.get('CDSESSN')),'boundary_vintage':2024,'is_at_large':prop.get('CD119FP')=='00','geometry_sha256':hashlib.sha256(geom).hexdigest()})
  ids.sort(key=lambda x:x['geoid'] or '')
  ip=OUT/'cd119_geometry_manifest.json';ip.write_text(json.dumps({'source_zip':'/tmp/usa-maps-data-flow-20261026/cb_2024_us_cd119_500k.zip','source_zip_sha256':'2b4238aed7e865df75d0c9cfcd8dffa1b79007b24519ecc4b213e683078b031a','source_url':'https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_cd119_500k.zip','features':ids,'feature_count':len(ids),'notice':'2024 119th Congress geometry only; do not join historic contests. No ZZ geometry synthesized.'},indent=2)+'\n')
  inventory['outputs']['cd119_geometry_manifest']={'path':str(ip),'sha256':sha(ip),'features':len(ids)}
  inventory['outputs']['cd119_geojson']={'path':str(geo_path),'sha256':sha(geo_path),'bytes':geo_path.stat().st_size,'features':len(ids)}
 ip=OUT/'reader-results.json';ip.write_text(json.dumps(inventory,indent=2)+'\n')
if __name__=='__main__': run()
