"""Explicit full-input check; requires caller-supplied prepared input and generated output directories."""
import argparse, csv, json, math, pathlib
from prepare import sha256, POLITICS_FILES

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',required=True,type=pathlib.Path)
    parser.add_argument('--prepared-dir',required=True,type=pathlib.Path)
    args=parser.parse_args()
    inp,out=args.input_dir,args.prepared_dir
    rel,delimiter,expected,count,field,release,raw_rel,raw_expected=POLITICS_FILES['house']
    source=inp/rel
    if sha256(source)!=expected or sha256(inp/raw_rel)!=raw_expected:
        raise SystemExit('House prepared/raw source hash mismatch')
    with source.open(newline='',encoding='utf-8-sig') as stream:
        expected_rows=list(csv.DictReader(stream,delimiter=delimiter))
    output_rows=[json.loads(line) for line in (out/'election_candidates.jsonl').open() if '"office":"house"' in line]
    if len(expected_rows)!=count or len(output_rows)!=count:
        raise SystemExit('House input/output row count mismatch')
    output_rows.sort(key=lambda row:int(row['source_row_id']))
    for index,(source_row,prepared) in enumerate(zip(expected_rows,output_rows),1):
        if int(prepared['source_row_id'])!=index or prepared['source_record']!=source_row:
            raise SystemExit('House full record mismatch at row {}'.format(index))
        if prepared['result_mode']!='TOTAL':
            raise SystemExit('House normalized mode corruption at row {}'.format(index))
    dc=[row for row in output_rows if row['election_year']==2024 and row['state_fips']=='11']
    if len(dc)!=7 or any(row['geo_id']!='1198' or row['seat_type']!='nonvoting_delegate' or row['is_at_large'] for row in dc):
        raise SystemExit('DC delegate IDs/seat-type mismatch')
    if any(row['geo_id']=='1100' for row in dc):
        raise SystemExit('DC at-large ID was fabricated')
    shares=[json.loads(line) for line in (out/'election_party_results.jsonl').open()]
    dc_dem=next((row for row in shares if row['office']=='house' and row['election_year']==2024 and row['geo_id']=='1198' and row['party_normalized']=='DEMOCRAT'),None)
    expected_share=251540/328404
    if not dc_dem or dc_dem['party_aggregation_status']!='validated' or dc_dem['reported_total_votes']!=328404 or not math.isclose(dc_dem['share_all_votes'],expected_share,rel_tol=0,abs_tol=1e-12):
        raise SystemExit('known 2024 DC Democratic share did not match source totals')
    observations=[json.loads(line) for line in (out/'reader_observations.jsonl').open()]
    nation=next((row for row in observations if row['geo_type']=='nation' and row['geo_id']=='US'),None)
    if not nation or nation['raw_estimate']!='7990799' or nation['raw_estimate_moe']!='48461' or nation['value'] is None:
        raise SystemExit('US AIAN source estimate/MOE missing')
    print(json.dumps({'status':'pass','house_rows_compared_exactly':len(expected_rows),'house_modes_total':len(output_rows),'dc_delegate_rows':len(dc),'dc_2024_democratic_share':dc_dem['share_all_votes'],'aian_nation_value':nation['value'],'production_eligible':False},indent=2))
if __name__=='__main__': main()
