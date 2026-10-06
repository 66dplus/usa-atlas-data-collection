#!/usr/bin/env python3
"""Reconcile successful local research snapshots; no HTTP calls or DB writes."""
import csv
import hashlib
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATES = runpy.run_path(str(ROOT / 'collect_open_sources.py'))['STATES']


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    current_sources = {}
    attempts = []
    for path in sorted((ROOT / 'runs').glob('*/manifest.json')):
        manifest = json.loads(path.read_text())
        for source_id, result in manifest['results'].items():
            attempts.append(dict(run=manifest['run_path'], source_id=source_id, **result))
            if result['status'] == 'collected':
                current_sources[source_id] = dict(run=manifest['run_path'], result=result,
                    completed_utc=manifest['completed_utc'], manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    observations = []
    for source_id, source in sorted(current_sources.items()):
        raw_rows = json.loads((ROOT / source['run'] / 'observations.json').read_text())
        observations.extend(r for r in raw_rows if r['source_id'] == source_id)
    keys = [(r['metric_id'], r['geo_type'], r['geo_id'], r['observation_period'],
             r.get('source_status'), r.get('project_type')) for r in observations]
    if len(keys) != len(set(keys)):
        raise RuntimeError('Duplicate observation keys in reconciled snapshots')
    out = ROOT / 'normalized'; out.mkdir(exist_ok=True)
    write_json(out / 'observations.json', observations)
    # Nested provenance and flags stay intact in JSON; CSV is a readable flat index.
    flat = ['metric_id','geo_type','geo_id','geo_name','value','unit','source_id','observation_period',
            'source_status','project_type','retrieved_utc','source_url','source_response_sha256',
            'quality_flags','coverage_note','admission_status']
    with (out / 'observations.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=flat);writer.writeheader()
        for r in observations:
            writer.writerow({k: '|'.join(r.get(k,[])) if k=='quality_flags' else r.get(k,'') for k in flat})
    epa_counts=current_sources.get('epa_energy_star',{}).get('result',{}).get('state_counts',{})
    repo=ROOT.parents[2]
    legacy=repo/'research/2026-09-28/new-topics/normalized/irs-wealth-2019.csv'
    existing_irs={r['geo_id']:r for r in csv.DictReader(legacy.open()) if r['geo_type']=='state'}
    coverage=[]
    for state,fips in sorted(STATES.items(),key=lambda p:p[1]):
        irs=existing_irs.get(fips,{})
        coverage.append(dict(state_name=state,state_fips=fips,
            millionaires_resident_persons_value=None,
            millionaires_resident_persons_status='source_or_license_needed',
            historical_investable_household_candidate='Phoenix 2019; no licensed numeric table collected',
            existing_irs_wealth_11_4m_person_proxy_value=irs.get('adult_count_estimate') or None,
            existing_irs_wealth_proxy_quality=irs.get('quality','unavailable'),
            billionaires_resident_persons_value=None,
            billionaires_resident_persons_status='source_or_license_needed',
            operating_data_centers_complete_state_value=None,
            operating_data_centers_status='partial_registry_and_county_sources' if state in epa_counts or state in ('Texas','Minnesota','Virginia') else 'no_matching_new_observation',
            energy_star_ever_certified_listed_properties=epa_counts.get(state),
            energy_star_latest_source_date='snapshot 2026-10-03, certifications vary',
            new_state_tax_project_source='Texas Comptroller' if state=='Texas' else 'Minnesota DEED' if state=='Minnesota' else None,
            new_verified_county_source='Loudoun County GIS; county_fips=51107' if state=='Virginia' else None,
            county_followup='Validate Minnesota city labels/addresses before admitting 10 candidate counties' if state=='Minnesota' else 'Find authoritative facility records and operating evidence',
            notes='Unknown target totals remain null. Separate metrics do not fill these target fields.'))
    write_json(ROOT/'state-coverage.json',coverage)
    with (ROOT/'state-coverage.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(coverage[0]));writer.writeheader();writer.writerows(coverage)
    status=dict(as_of_utc=max(v['completed_utc'] for v in current_sources.values()),
        sources=current_sources,observations=len(observations),
        source_status_count=len(current_sources),
        target_state_coverage=dict(resident_millionaire_person_counts=0,resident_billionaire_person_counts=0,
                                  complete_operating_data_center_totals=0),
        partial_epa_state_coverage=len(epa_counts),
        geographic_scope='50 states + DC ledger; Puerto Rico retained as extra raw EPA record',
        production_writes=0,attempts=attempts,
        artifact_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(out.glob('*')) if p.is_file()})
    write_json(ROOT/'current-status.json',status)
    print(json.dumps(dict(sources=len(current_sources),observations=len(observations),
                         epa_states=len(epa_counts),coverage_rows=len(coverage)),ensure_ascii=False))


if __name__=='__main__':
    main()
