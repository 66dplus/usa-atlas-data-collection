#!/usr/bin/env python3
"""Read existing evidence only; write a scoped 81-field audit in this directory."""
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'research/2026-09-28'
evidence = {}


def load(path):
    path = Path(path)
    data = path.read_bytes()
    name = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    evidence[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return json.loads(data)


def source_table(name):
    path = ROOT / 'full/runtime/public-20260928/tables' / (name + '.csv.gz')
    with gzip.open(path, 'rt', newline='') as handle:
        rows = list(csv.DictReader(handle))
    if rows and 'cells_json' in rows[0]:
        headers, result = {}, []
        for row in rows:
            cells = json.loads(row['cells_json'])
            member = row['source_member']
            if row['source_row'] == '1':
                headers[member] = cells
            elif len(cells) == len(headers[member]):
                result.append(dict(zip(headers[member], cells)))
        return result
    return rows


def main():
    contract = load(ROOT / 'full/field-contract.json')
    historical = load(OLD / 'geography/coverage-matrix.json')
    baseline = {r['field_id']: r for r in historical['fields']}
    live = load(OLD / 'geography/live-coverage.json')
    deep = {r['field_id']: r for r in live['fields']}
    fingerprint = load('/srv/usa-atlas/maintenance/20260928-compact/source-fingerprint.json')
    production = {r['source']: r for r in fingerprint}
    public = load(OLD / 'public-sources/collection-manifest.json')
    local_summary = load(OLD / 'local-portals/collection-summary.json')
    local = {r['source_id']: load(OLD / 'local-portals' / r['manifest']) for r in local_summary['sources']}
    intake = load(OLD / 'local-portals/gap-intake.json')
    companies = load(OLD / 'public-sources/company-receipts-2022.json')
    load(ROOT / 'full/runtime/deep-20260928/metadata/table-universes-and-restrictions.json')
    load(ROOT / 'full/runtime/deep-20260928/extensions/metric-equivalence.json')
    excluded = set(historical['food_excluded'])

    irs = source_table('irs-county-agi-2023')
    irs_coverage = {'county': len({r['STATEFIPS'] + r['COUNTYFIPS'] for r in irs if r['COUNTYFIPS'] != '000'}),
                    'state_totals': len({r['STATEFIPS'] for r in irs if r['COUNTYFIPS'] == '000'})}
    bea = [r for r in source_table('bea-metro-rpp') if r.get('TableName') == 'MARPP' and r.get('LineCode') == '1']
    epa = source_table('epa-monitors-2025')
    epa_coverage = {}
    for code in ['88101', '44201']:
        rows = [r for r in epa if r.get('Parameter Code') == code]
        us = [r for r in rows if r['State Code'] != '80']
        epa_coverage[code] = {'source_statistic_rows': len(rows), 'us_and_pr_statistic_rows': len(us),
            'source_state_codes': sorted({r['State Code'] for r in rows}),
            'us_and_pr_counties_with_monitors': len({(r['State Code'], r['County Code']) for r in us}),
            'us_and_pr_sites': len({(r['State Code'], r['County Code'], r['Site Num']) for r in us}),
            'note': 'Source also contains Mexico code 80; monitor coverage is not complete areal coverage.'}

    rows = []
    for field in contract:
        fid = field['field_id']
        old, current = baseline[fid], deep[fid]
        provider = field['rate_limit_profile']
        row = {'field_id': fid, 'label': field['catalog_label'], 'in_scope': fid not in excluded,
            'contract_provider': provider, 'contract_state': field['planned_state'],
            'contract_release': field['source_release'], 'contract_variables': field['source_variables'],
            'contract_derivation': field['derivation'], 'license_status': field['license_status'],
            'original_db_provider_present': provider in production, 'original_db_field_rows': None,
            'original_db_field_geographies': None,
            'original_db_evidence_scope': 'provider-only row fingerprint; no per-field or per-geography count inferred',
            'new_production_admitted': False, 'national_source_status': 'not_collected_in_new_run',
            'native_bg_status': 'not_verified', 'bg_counts_by_table': {}, 'native_coverage_by_table': {},
            'national_coverage_note': '', 'regional_candidates': [], 'definition_or_access_gap': '',
            'evidence': ['full/field-contract.json', 'research/2026-09-28/geography/live-coverage.json'],
            'historical_research_note': old['notes_ru']}
        if fid in excluded:
            row.update(national_source_status='excluded_food', native_bg_status='excluded_food',
                       definition_or_access_gap='Excluded from new collection by user; pre-existing DB rows not removed.')
        elif provider == 'census_acs':
            row['national_source_status'] = 'national_source_collected'
            row['native_coverage_by_table'] = current['coverage_by_table']
            row['bg_counts_by_table'] = {k: v.get('block_group', 0) for k, v in current['coverage_by_table'].items()}
            for variant in current.get('extension_variants', []):
                row['native_coverage_by_table']['extension:' + variant['table']] = variant['geography_counts']
                row['bg_counts_by_table']['extension:' + variant['table']] = variant['geography_counts'].get('block_group', 0)
            row['native_bg_status'] = 'native_source_estimates_collected' if any(row['bg_counts_by_table'].values()) else 'not_published_for_selected_tables'
            row['national_coverage_note'] = 'Source E/M pairs collected nationwide at published native levels; derived catalog ratios and admission pending. Multi-table GEOID intersections are not inferred from equal counts.'
            row['definition_or_access_gap'] = 'Preserve MOE/quality; derive required shares and ratios before admission/UI.'
            if fid == '02.08':
                row['native_bg_status'] = 'equivalent_count_variant_collected'
                row['national_coverage_note'] += ' B17021 provides poverty numerator/denominator at BG; equivalent common county/tract E/M verified, source variant remains explicit.'
        elif provider == 'cdc_places':
            row.update(national_source_status='national_source_collected_separate_variant', native_bg_status='tract_only',
                native_coverage_by_table=current['coverage_by_table'],
                national_coverage_note='83,522 tracts, data year 2023, crude prevalence + CI; separate from existing age-adjusted county series.',
                definition_or_access_gap='Retain variant and CI; no BG downscale.')
        elif fid == '02.10':
            row.update(national_source_status='national_source_table_collected_new_geography', native_bg_status='metro_native_no_bg',
                native_coverage_by_table={'bea-metro-rpp': {'metro': len(bea)-2, 'us_total_and_nonmetro_total': 2}},
                national_coverage_note='MARPP all-items RPP: 387 MSA plus US and US nonmetropolitan total; 2008–2024. Filter TableName=MARPP AND LineCode=1; MAIRPD is a different index.',
                definition_or_access_gap='Exact metric family, different table/geography from SARPP contract; adapter/admission pending.')
        elif fid in ['07.01', '07.03', '07.04']:
            missing = sorted(set(field['source_variables']) - set(irs[0]))
            row.update(national_source_status='national_source_table_partial_variable_match' if missing else 'national_source_table_collected_new_release_and_geography',
                native_bg_status='county_and_tax_zip_native_no_bg', native_coverage_by_table={'irs-county-agi-2023': irs_coverage},
                national_coverage_note='County/state source tables for tax year 2023; older contract is ZIP 2022. ZIP is not ZCTA. County code 000 is a state total.',
                definition_or_access_gap='Missing contract columns: '+', '.join(missing)+'. N1 is not silently aliased to N00100.' if missing else 'Requested source variable names present; review release, population, stubs, units and disclosure before admission.')
            row['public_missing_contract_variables'] = missing
        elif fid in ['09.06', '09.07']:
            code = field['source_variables'][0]
            row.update(national_source_status='national_source_table_collected_monitor_variant', native_bg_status='monitor_native_no_areal_bg',
                native_coverage_by_table={'epa-monitors-2025': epa_coverage[code]},
                national_coverage_note='Same pollutant parameter/source family; nationwide monitor network is spatially incomplete. Sample duration, standard, POC and event variants remain distinct.',
                definition_or_access_gap='Exclude foreign monitor code 80 for US scope; define monitor statistic and any aggregation explicitly.')
        elif fid in ['07.06', '07.07']:
            row.update(national_source_status='national_publisher_context_only', native_bg_status='small_area_source_unconfirmed',
                national_coverage_note='One UBS US aggregate saved for this topic, not official exact small-area coverage.',
                definition_or_access_gap='Subnational source and regular reuse rights unresolved; IRS wealth >=11.4m does not substitute exact millionaire >=1m.')
        else:
            state = field['planned_state']
            row['national_source_status'] = ('legacy_provider_present_new_collection_pending' if provider in production else
                'definition_required' if state == 'definition_required' else
                'source_or_license_required' if state in ['source_required', 'license_required'] else
                'source_not_collected_access_or_adapter_pending')
            row['definition_or_access_gap'] = old['notes_ru']
            row['native_bg_status'] = 'no_verified_national_bg_source'

        if fid in ['01.01', '02.01']:
            row['regional_candidates'].append({'source': 'ca-dwr-bg-income-2023', 'relation': 'older ACS regional republishing, 25,607 CA BG; no MOE, does not improve national coverage'})
        if fid in ['01.01', '02.02', '02.06', '02.08', '03.06']:
            row['regional_candidates'].append({'source': 'ca-dwr-bg-water-vulnerability-2024', 'relation': 'related regional attributes; release/vintage and metric differences unresolved; poverty is below 200%, not canonical poverty below 100%; not matched coverage'})
        if fid.startswith('04.'):
            row['regional_candidates'].append({'source': 'dc-mpd-crime-bg-2025 + dc-mpd-crime-bg-2026', 'relation': 'DC incident-report aggregates only; offense mapping, denominator, YTD comparison and provider BG vintage need review; not automatically FBI-equivalent'})
        if fid in ['07.01', '07.02', '07.05']:
            row['regional_candidates'].append({'source': 'ny-county-income-tax-1999-2014', 'relation': 'historical NY resident returns; definition/period differ, top band 500k+ is not millionaire wealth or >=1m AGI'})
        if fid in ['07.02', '07.05']:
            row['public_candidates'] = ['irs-state-agi-2023', 'irs-county-agi-2023']
            row['definition_or_access_gap'] += ' Source tables exist but selected threshold/tax measure is still undefined.'
        if row['regional_candidates']:
            row['evidence'].append('research/2026-09-28/local-portals/collection-summary.json')
        rows.append(row)

    bg_fields = [r['field_id'] for r in rows if any(r['bg_counts_by_table'].values())]
    result = {'captured_at': datetime.now(timezone.utc).isoformat(), 'scope': 'Existing files and read-only production fingerprint; no SQL or new network collection.',
        'summary': {'catalog_fields': len(rows), 'food_excluded': len(excluded), 'in_scope': len(rows)-len(excluded),
            'acs_source_fields_collected': 23, 'cdc_source_fields_collected_separate_variant': 3,
            'acs_cdc_source_fields_of_in_scope': '26/74', 'national_native_bg_source_or_equivalent_count_fields': len(bg_fields),
            'native_bg_fields': bg_fields, 'remaining_fields_without_verified_national_bg': 74-len(bg_fields),
            'completed_catalog_formulas_or_ui_claimed': False,
            'original_db_sources': len(production), 'original_db_rows': sum(r['rows'] for r in fingerprint),
            'original_db_per_field_counts_known': False,
            'main_acs_cdc_source_records': live['normalized_observations_total'],
            'extension_source_records': live['extension_observations_total'],
            'all_deep_source_records': live['all_normalized_observations_total'],
            'regional_datasets': len(local), 'regional_source_rows': sum(r['rows'] for r in local.values()),
            'regional_jurisdictions': ['CA', 'DC', 'VA (Loudoun County only)', 'NY'],
            'state_units_explained': 'Maximum ACS 52 = 50 states + District of Columbia + Puerto Rico; not 52 states.',
            'national_status_counts': dict(Counter(r['national_source_status'] for r in rows))},
        'production_provider_fingerprints': fingerprint,
        'local_datasets': local,
        'public_jobs': public['jobs'],
        'outside_81_fields': {'company_receipts': companies,
            'data_centers': 'Loudoun regional building/stage records only, not operating-facility count or national coverage.',
            'water': 'CA vulnerability/well-record metrics; not water reserves.',
            'wealth_11_4m': 'Separate IRS threshold, not exact 07.06 millionaire coverage.'},
        'gap_intake_schema_mismatch': {'current_gap_fields': intake['gap_fields'], 'corrected_gap_fields': 74-len(bg_fields),
            'field': '02.08', 'consumer': 'collect_local.py reads variant.available_native_levels',
            'original_cause': 'snapshot_live.py emitted extension_variants[].geography_counts, without available_native_levels',
            'producer_schema_fixed': any('block_group' in v.get('available_native_levels', []) for v in deep['02.08'].get('extension_variants', [])),
            'resolution': 'Root adds available_native_levels to snapshot producer; pinned consumer and its config unchanged; intake updates on next scheduled cycle.',
            'collector_patch_applied': False},
        'fields': rows, 'evidence_sha256': evidence}
    (HERE / 'coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    columns = ['field_id','label','in_scope','contract_provider','contract_state','original_db_provider_present',
               'original_db_field_rows','national_source_status','native_bg_status','bg_counts_by_table',
               'native_coverage_by_table','national_coverage_note','regional_candidates','definition_or_access_gap','new_production_admitted']
    with (HERE / 'coverage.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle, fieldnames=columns);writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(row[k],ensure_ascii=False,separators=(',',':')) if isinstance(row[k],(dict,list)) else row[k] for k in columns})
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
