#!/usr/bin/env python3
"""Rebuild the 81-field research ledger from pinned contract and local evidence."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FULL = ROOT / 'full'
EXCLUDED = {'08.01', '08.02', '08.03', '08.06', '09.01', '09.02', '09.03'}
REFS = {
    'acs': 'https://www.census.gov/data/developers/data-sets/acs-5year.html',
    'acs_restrictions': 'https://www2.census.gov/programs-surveys/acs/tech_docs/data_suppression/ACS_Data_Release_Rules.pdf',
    'acs_tablelist': 'https://www2.census.gov/programs-surveys/acs/tech_docs/table_shells/table_lists/2024_DataProductList.xlsx',
    'acs_summary': 'https://www.census.gov/programs-surveys/acs/data/summary-file.2024.html',
    'places': 'https://data.cdc.gov/500-Cities-Places/PLACES-Census-Tract-Data-GIS-Friendly-Format-2025-/yjkw-uj5s',
    'laus': 'https://www.bls.gov/lau/laugeo.htm',
    'qcew': 'https://www.bls.gov/cew/overview.htm',
    'fbi': 'https://www.fbi.gov/how-we-can-help-you/more-fbi-services-and-information/ucr',
    'wonder': 'https://wonder.cdc.gov/wonder/help/mcd-provisional.html',
    'wonder_api': 'https://wonder.cdc.gov/wonder/help/wonder-api.html',
    'usaleep': 'https://www.cdc.gov/nchs/nvss/usaleep/update/usaleep.html',
    'hud': 'https://www.huduser.gov/portal/datasets/ahar.html',
    'irs': 'https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-zip-code-data-soi',
    'irs_county': 'https://www.irs.gov/statistics/soi-tax-stats-county-data-2022',
    'bea': 'https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area',
    'eia': 'https://www.eia.gov/electricity/data/eia861/',
    'gas': 'https://www.eia.gov/dnav/pet/pet_pri_gnd_a_epm0_pte_dpgal_m.htm',
    'debt': 'https://www.newyorkfed.org/microeconomics/databank',
    'insurance': 'https://www.cms.gov/data-research/statistics-trends-reports/marketplace-products/2026-marketplace-open-enrollment-period-public-use-files',
    'fitness': 'https://www.ers.usda.gov/data-products/food-environment-atlas/documentation',
    'epa': 'https://aqs.epa.gov/aqsweb/airdata/download_files.html',
    'ubs_millionaires': 'https://www.ubs.com/global/en/wealthmanagement/insights/global-wealth-report.html',
    'ubs_billionaires': 'https://www.ubs.com/us/en/wealth-management/our-solutions/private-wealth-management/insights/billionaires-ambition-report.html',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def detail(field):
    fid, provider = field['field_id'], field['rate_limit_profile']
    if fid in EXCLUDED:
        return None, 'excluded_food', 'excluded_by_user', [], 'Новый сбор еды, напитков, ресторанов, магазинов и food access исключён.'
    if provider == 'census_acs':
        restricted = fid in {'01.05', '01.06', '01.07', '01.08'}
        return ('tract_pending_table_validation' if restricted else 'block_group', 'Census ACS 2024 Detailed Tables',
                'partial_cache_only' if fid in {'01.02', '01.03'} else 'blocked_network',
                ['acs', 'acs_summary', 'acs_restrictions', 'acs_tablelist'],
                'Наличие block group проверять по каждой таблице; B050xx с чувствительными темами консервативно оставлены tract до чтения 2024 Table List. Summary File сохраняет только опубликованные GEO_ID.' if restricted else
                'Dataset публикует BG; конкретный 2024 payload ещё не скачан. E/M сохраняются вместе, EA/MA отсутствуют в старом кэше; пересчёт долей требует отдельной формулы MOE.')
    if provider == 'cdc_places':
        return 'tract', 'CDC PLACES 2025', 'blocked_network_variant_required', ['places'], 'Трактовый GIS файл: crude prevalence, год 2023, границы 2023, модель и 95% CI. Текущий county контракт: age-adjusted. Создать отдельный variant, не заменять существующую серию.'
    if provider == 'bls_laus':
        return 'selected_city_or_city_part', 'BLS LAUS', 'native_ceiling_no_tract_bg', ['laus'], 'Национальный county слой; также официальные города 25k+ и города/тауншипы Новой Англии. Городская серия отдельная; tract/BG отсутствуют. ACS unemployment — другая методология.'
    if provider == 'bea_rpp':
        return 'metro', 'BEA RPP', 'native_ceiling_no_county_tract_bg', ['bea'], 'Официальный RPP штат/метро; metro не county. Старый SARPP download содержит штатные серии; MARPP требует отдельного артефакта.'
    if provider == 'fbi_cde' or fid == '04.08':
        return 'agency', 'FBI CDE/UCR', 'agency_adapter_pending', ['fbi'], 'ORI и участие/месяцы отчётности обязательны. Агентство не совпадает с county/place; нельзя суммировать пересекающиеся зоны. Для 04.08 сначала уточнить police homicide vs mortality.'
    if fid.startswith('05.') and int(fid.split('.')[1]) <= 12:
        return 'county', 'CDC WONDER/NVSS', 'restricted_geographic_api', ['wonder', 'wonder_api'], 'County доступен в интерфейсе; публичный WONDER API запрещает group/filter по location для NVSS. Нужен разрешённый экспорт/публичный файл. Подавленные значения, CI, ICD-10 и underlying/multiple cause обязательны; drug categories пересекаются.'
    if fid == '05.13':
        return 'tract', 'CDC NCHS USALEEP 2010-2015', 'historical_source_selected_download_pending', ['usaleep'], 'Есть официальный tract baseline 2010–2015 с observed/modelled flag, SE, границами 2010. Не выдавать его за текущий ежегодно обновляемый показатель.'
    if fid.startswith('06.'):
        return 'continuum_of_care', 'HUD PIT/HIC AHAR', 'native_ceiling_coc_download_pending', ['hud'], 'CoC может включать несколько counties или часть территории. PIT — однодневная оценка; sheltered/unsheltered, population и method сохранять. County/tract/BG автоматически не выводятся.'
    if provider == 'irs_soi' or fid in {'07.02', '07.05'}:
        return 'zip', 'IRS SOI ZIP and County 2022', 'native_zip_county_download_pending', ['irs', 'irs_county'], 'ZIP и county доступны отдельными таблицами, ZIP не ZCTA. AGI stub/единицы $1000/returns сохранять; налоговая декларация не человек. Для 07.02/07.05 определить порог и метрику.'
    if fid in {'07.06', '07.07'}:
        return ('nation', 'UBS national wealth aggregates; small-area source unconfirmed',
                'national_context_collected_smallarea_unconfirmed',
                ['ubs_millionaires' if fid == '07.06' else 'ubs_billionaires'],
                'В ../new-topics/NEW-TOPICS.md и normalized/ubs-national-wealth.csv сохранены national UBS aggregates: 23 627 000 взрослых миллионеров на конец 2025 / 924 миллиардера на 2025-04-04. Это контекст США, не county/tract/BG; малая география не подтверждена. Условия регулярного использования/лицензия требуют проверки. IRS net worth >=$11.4m — отдельная метрика и exact-millionaire поле >=$1m не заменяет.')
    if fid == '03.07':
        return 'metro_or_nonmetro', 'BLS OEWS; QCEW county alternative', 'definition_source_adapter_pending', ['qcew'], 'Контракт ссылается на среднюю зарплату OEWS. QCEW даёт county average weekly/annual pay, но это другая совокупность; не подменять без нового определения.'
    if fid == '03.08':
        return 'county', 'BLS QCEW', 'definition_required', ['qcew'], 'Можно county employment growth по сопоставимым годам/NAICS/ownership с disclosure flag. Выбрать годовой или квартальный рост и базовый период.'
    if fid == '08.04':
        return 'selected_city', 'EIA retail gasoline', 'definition_required', ['gas'], 'Публичная EIA серия для отдельных городов/штатов, не национальная station/BG. Выбрать grade, frequency и unit USD/gallon.'
    if provider == 'eia':
        return 'utility_state_sector', 'EIA 861', 'utility_adapter_pending', ['eia'], 'Средняя цена revenue/sales в utility×state×sector; territory file перечисляет counties, но county price не измеряет. Нельзя растянуть цену utility на BG.'
    if fid in {'08.07', '08.08'}:
        return 'county_candidate_unconfirmed_metric', 'Federal Reserve Bank of New York public aggregates', 'source_definition_pending', ['debt'], 'Есть публичные county агрегаты, но конкретный average debt/student balance denominator, выпуск и покрытие требуют проверки. Consumer Credit Panel microdata не являются открытыми.'
    if fid == '08.09':
        return 'county', 'CMS Marketplace 2026 OEP county PUF', 'definition_required_partial_national_coverage', ['insurance'], 'County average monthly premium доступна для 30 HealthCare.gov states; это enrolled Marketplace consumers, не стоимость страховки всего населения. До/после subsidy и denominator выбрать явно.'
    if fid == '09.04':
        return 'county', 'USDA FEA fitness indicator / Census CBP', 'native_ceiling_no_tract_bg', ['fitness'], 'Fitness не исключён; RECFACPTH county из NAICS 713940. Скачивать только нефудовый показатель/CBP; общий food sweep отключён.'
    if fid == '09.05':
        return 'unconfirmed_point_or_polygon', 'provider_unselected', 'definition_required', [], 'Сначала определить parks/recreation/public access. PAD-US protected lands не эквивалент всем городским паркам и спортивным объектам; point/polygon агрегаты требуют отдельной методики.'
    if provider == 'epa_airdata':
        return 'monitor', 'EPA AirData', 'native_monitor_aggregation_pending', ['epa'], 'Нативный монитор: station/POC, parameter, duration, standard, units, completeness. County AQI — отдельный продукт; среднее всех monitor рядов не равно exposure в tract/BG.'
    raise ValueError('unmapped_field:' + fid)


def main():
    contract = json.loads((FULL / 'field-contract.json').read_text())
    historical = json.loads((FULL / 'state/run-manifest.json').read_text())
    recovery = json.loads((HERE / 'cache-recovery-manifest.json').read_text())
    fixture_rows = {}
    for provider in ['fbi_cde', 'eia']:
        path = FULL / 'normalized' / (provider + '.jsonl')
        expected = historical['sources'][provider]['normalized_artifact']['sha256']
        if sha(path) != expected:
            raise ValueError('fixture_hash_mismatch')
        counts = Counter()
        for line in path.read_text().splitlines():
            record = json.loads(line)
            counts[(record['field_id'].split(':')[0], record['geo_type'])] += 1
        fixture_rows[provider] = counts
    output = []
    for f in contract:
        finest, selected, status, refkeys, note = detail(f)
        fid, provider = f['field_id'], f['rate_limit_profile']
        local = {}
        observed_vars = set()
        if provider == 'census_acs':
            for geo, variables in recovery['observed_variables_by_geography'].items():
                matching = set(variables) & set(f['source_variables'])
                if matching:
                    local[geo] = {'geographies': recovery['geography_counts'][geo], 'variables_present': len(matching), 'field_complete': False}
                    observed_vars |= matching
        elif provider in fixture_rows:
            local = {geo: {'rows': count, 'artifact_kind': 'committed_integration_fixture'}
                     for (field, geo), count in fixture_rows[provider].items() if field == fid}
        hist = historical['sources'].get(provider, {})
        output.append({
            'field_id': fid, 'label': f['catalog_label'], 'excluded_from_new_collection': fid in EXCLUDED,
            'contract_provider': provider, 'contract_state': f['planned_state'],
            'contract_declared_geographies': f['target_geographies'],
            'historical_run_source_status': hist.get('status', 'not_run'),
            'historical_source_rows_not_field_rows': hist.get('normalized_rows'),
            'verified_local_coverage': local, 'finest_verified_local': 'tract' if 'tract' in local else 'state' if 'state' in local else None,
            'catalog_required_variables': len(f['source_variables']), 'local_acs_variables_present': len(observed_vars),
            'finest_legitimate_geography_or_unresolved_candidate': finest,
            'selected_provider_or_candidate': selected, 'collection_status': status,
            'probe': 'DNS/network_gaierror; see run-acs-summary.json' if provider == 'census_acs' else 'DNS/network_gaierror; see run-cdc-places.json' if provider == 'cdc_places' else 'not_requested_excluded' if fid in EXCLUDED else 'official_documentation_only_no_bulk_probe',
            'evidence_urls': [REFS[k] for k in refkeys], 'notes_ru': note,
            'related_research_paths': ['../new-topics/NEW-TOPICS.md', '../new-topics/normalized/ubs-national-wealth.csv'] if fid in {'07.06', '07.07'} else [],
        })
    assert len(output) == 81 and len({x['field_id'] for x in output}) == 81
    value = {'as_of': '2026-09-28', 'contract_sha256': sha(FULL / 'field-contract.json'),
             'food_excluded': sorted(EXCLUDED), 'new_live_observations_downloaded': 0,
             'database_introspected': False, 'important': 'Historical manifest is not proof that bulk artifacts or DB rows are present in this checkout.',
             'fields': output}
    (HERE / 'coverage-matrix.json').write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    columns = ['field_id', 'label', 'excluded_from_new_collection', 'contract_provider',
               'finest_verified_local', 'finest_legitimate_geography_or_unresolved_candidate',
               'collection_status', 'probe', 'notes_ru']
    with (HERE / 'coverage-matrix.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(output)
    series = []
    metadata = {}
    for path in sorted((FULL / 'raw/full/census_acs').glob('group-*.json.gz')):
        import gzip
        with gzip.open(path, 'rt') as f:
            metadata.update(json.load(f)['variables'])
    for table, variables in recovery['observed_variables_by_geography'].items():
        if table != 'tract':
            continue
        for base in sorted({v[:-1] for v in variables}):
            parents = [f['field_id'] for f in contract if base + 'E' in f['source_variables']]
            series.append({'variable': base, 'catalog_field_ids': parents,
                           'label': metadata.get(base + 'E', {}).get('label'),
                           'universe': 'Total population', 'unit': 'persons',
                           'estimate_variable': base + 'E', 'moe_variable': base + 'M',
                           'moe_column_collected': base + 'M' in variables})
    (HERE / 'recovered-series.json').write_text(json.dumps(series, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'fields': len(output), 'excluded_food_fields': len(EXCLUDED),
                      'status_counts': dict(Counter(x['collection_status'] for x in output))}, indent=2))


if __name__ == '__main__':
    main()
