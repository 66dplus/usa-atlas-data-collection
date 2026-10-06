#!/usr/bin/env python3
"""Rebuild research-only state fact cards from pinned, admitted-source ACS inputs.

No production writes. API verification uses the existing key without persisting it.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import shlex
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEEP = ROOT / 'full/runtime/deep-20260928'
DATE = '2026-10-03'
TABLES = ['B01001', 'B01002', 'B01003', 'B03002', 'B05002', 'B15003',
          'B17001', 'B19001', 'B19013', 'B19301', 'B25003', 'B25064',
          'B25070', 'B25077', 'B08301']
RU = dict(zip(
    ['01','02','04','05','06','08','09','10','11','12','13','15','16','17','18',
     '19','20','21','22','23','24','25','26','27','28','29','30','31','32','33',
     '34','35','36','37','38','39','40','41','42','44','45','46','47','48','49',
     '50','51','53','54','55','56'],
    ['Алабама','Аляска','Аризона','Арканзас','Калифорния','Колорадо','Коннектикут',
     'Делавэр','Округ Колумбия','Флорида','Джорджия','Гавайи','Айдахо','Иллинойс',
     'Индиана','Айова','Канзас','Кентукки','Луизиана','Мэн','Мэриленд','Массачусетс',
     'Мичиган','Миннесота','Миссисипи','Миссури','Монтана','Небраска','Невада',
     'Нью-Гэмпшир','Нью-Джерси','Нью-Мексико','Нью-Йорк','Северная Каролина',
     'Северная Дакота','Огайо','Оклахома','Орегон','Пенсильвания','Род-Айленд',
     'Южная Каролина','Южная Дакота','Теннесси','Техас','Юта','Вермонт','Вирджиния',
     'Вашингтон','Западная Вирджиния','Висконсин','Вайоминг']))


def dump(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def load():
    rows = {}
    receipts = []
    for table in TABLES:
        path = DEEP / f'data/acs-summary-{table}.csv.gz'
        meta = json.loads((DEEP / f'raw/acs-summary-{table}.gz.json').read_text())
        raw_path = DEEP / meta['path']
        if sha(raw_path) != meta['sha256']:
            raise ValueError('Stored upstream checksum mismatch: ' + table)
        with gzip.open(path, 'rt') as f:
            for row in csv.DictReader(f):
                if row['geo_type'] not in ('nation', 'state'):
                    break  # Existing summary files emit national and state rows first.
                rows.setdefault(row['geo_id'], {})[row['variable']] = row
        receipts.append({'table': table, 'source_url': meta['url'],
                         'retrieved_at': meta['retrieved_at'],
                         'last_modified': meta['last_modified'],
                         'source_payload_sha256': meta['sha256'],
                         'uncompressed_upstream_sha256': meta['upstream_sha256'],
                         'normalized_path': str(path.relative_to(ROOT)),
                         'normalized_sha256': sha(path), 'hash_verified': True})
    with gzip.open(ROOT / 'full/raw/full/census_acs/2024-state-all-pack-00.json.gz', 'rt') as f:
        names = {r[-1]: r[0] for r in json.load(f)[1:]}
    dump('source-receipts.json', receipts)
    dump('acs-state-evidence.json', rows)
    return rows, names, {r['table']: r for r in receipts}


def scalar(code, ids, label, unit, universe, caveat=''):
    return {'variables': [code], 'denominator': [], 'ids': ids, 'label': label,
            'unit': unit, 'universe': universe, 'caveat': caveat}


def ratio(nums, dens, ids, label, universe, caveat='', denominator_mode='sum'):
    return {'variables': nums, 'denominator': dens, 'ids': ids, 'label': label,
            'unit': 'percent', 'universe': universe, 'caveat': caveat,
            'denominator_mode': denominator_mode}


METRICS = {
    'age': scalar('B01002_001', ['01.02'], 'Медианный возраст', 'years', 'Total population'),
    'population': scalar('B01003_001', ['01.01'], 'Население', 'people', 'Total population'),
    'income': scalar('B19013_001', ['02.01'], 'Медианный годовой доход домохозяйства',
                     'USD_2024', 'Households', 'Это доход домохозяйства, а не зарплата одного человека.'),
    'home': scalar('B25077_001', ['02.04'], 'Медианная стоимость собственного жилья',
                   'USD', 'Owner-occupied housing units', 'Оценка стоимости владельцами; это не медиана цен текущих продаж.'),
    'rent': scalar('B25064_001', ['02.03'], 'Медианная месячная валовая аренда', 'USD_per_month',
                   'Renter-occupied housing units paying cash rent',
                   'Gross rent включает договорную плату и коммунальные расходы арендатора; это не цена новых объявлений.'),
    'wfh': ratio(['B08301_021'], ['B08301_001'], ['03.09'], 'Доля работающих из дома',
                  'Workers 16 years and over', 'Основной способ поездки на работу за опорную неделю; показатель не охватывает любой гибридный график.'),
    'owner': ratio(['B25003_002'], ['B25003_002', 'B25003_003'], ['02.07'],
                   'Доля жилья, занятого собственниками', 'Occupied housing units',
                   'Знаменатель — занятые жилые единицы, а не все жители и не весь жилищный фонд.'),
    'foreign': ratio(['B05002_013'], ['B05002_001'], ['01.05'], 'Доля родившихся за рубежом',
                     'Total population', 'Foreign-born означает, что при рождении человек не был гражданином США; включает натурализованных граждан.'),
    'native': ratio(['B05002_003'], ['B05002_001'], ['01.06'],
                    'Доля жителей, родившихся в штате проживания', 'Total population',
                    'Место рождения не показывает год переезда или его причину.'),
    'masters': ratio(['B15003_023'], ['B15003_001'], ['03.02'], 'Доля со степенью магистра',
                     'Population 25 years and over', 'Здесь только категория Master’s degree; doctorate и professional school degree считаются отдельно.'),
    'doctorate': ratio(['B15003_025'], ['B15003_001'], ['03.03'], 'Доля со степенью doctorate',
                       'Population 25 years and over', 'Это исследовательские докторские степени; professional school degree — отдельная категория.'),
    'bachelors_plus': ratio([f'B15003_{n:03}' for n in range(22, 26)], ['B15003_001'],
                            ['03.01', '03.02', '03.03'], 'Доля со степенью бакалавра или выше',
                            'Population 25 years and over', 'Сумма Bachelor’s, Master’s, Professional school и Doctorate; это не только бакалавры.'),
    'highschool_plus': ratio([f'B15003_{n:03}' for n in range(17, 26)], ['B15003_001'],
                             ['03.04'], 'Доля окончивших high school или выше',
                             'Population 25 years and over', 'Включает GED и все более высокие уровни образования.'),
    'poverty': ratio(['B17001_002'], ['B17001_001'], ['02.08'], 'Доля ниже федеральной черты бедности',
                     'Population for whom poverty status is determined', 'ACS использует федеральные пороги бедности; часть жителей исключена из universe.'),
    'highincome': ratio(['B19001_017'], ['B19001_001'], ['02.09'],
                         'Доля домохозяйств с годовым доходом $200 000 и выше', 'Households',
                         'Доход в долларах 2024 года; высокий годовой доход не означает состояние миллион долларов.'),
    'seniors': ratio([f'B01001_{n:03}' for n in list(range(20, 26)) + list(range(44, 50))],
                      ['B01001_001'], ['01.02'], 'Доля жителей 65 лет и старше', 'Total population'),
    'children': ratio([f'B01001_{n:03}' for n in list(range(3, 7)) + list(range(27, 31))],
                       ['B01001_001'], ['01.02'], 'Доля жителей младше 18 лет', 'Total population'),
    'male': ratio(['B01001_002'], ['B01001_001'], ['01.03'], 'Доля мужчин', 'Total population',
                   'Категория Male в ACS sex; не показатель гендерной идентичности.'),
    'hispanic': ratio(['B03002_012'], ['B03002_001'], ['01.04'], 'Доля Hispanic or Latino',
                       'Total population', 'Hispanic or Latino — этническая категория независимо от расы.'),
    'black': ratio(['B03002_004'], ['B03002_001'], ['01.04'],
                    'Доля non-Hispanic Black or African American alone', 'Total population',
                    'Только указанная Census категория; не включает multiracial и Hispanic Black.'),
    'asian': ratio(['B03002_006'], ['B03002_001'], ['01.04'],
                    'Доля non-Hispanic Asian alone', 'Total population',
                    'Только указанная Census категория; не включает multiracial и Hispanic Asian.'),
    'severe_rent': ratio(['B25070_010'], ['B25070_001', 'B25070_011'], ['02.06'],
                          'Доля арендаторов, отдающих на аренду не менее половины дохода',
                          'Renter-occupied housing units paying cash rent with computable gross rent as percentage of income',
                          'Знаменатель исключает Not computed; валовая аренда включает коммунальные расходы.',
                          'subtract'),
}

# Curated pairs: housing, education, mobility, age, ethnicity, income and working patterns.
SELECTION = {
    '01': ['owner','rent'], '02': ['male','income'], '04': ['native','wfh'],
    '05': ['home','rent'], '06': ['foreign','severe_rent'], '08': ['wfh','bachelors_plus'],
    '09': ['masters','highincome'], '10': ['owner','seniors'],
    '11': ['wfh','masters'], '12': ['seniors','foreign'], '13': ['black','wfh'],
    '15': ['asian','home'], '16': ['owner','home'], '17': ['foreign','highincome'],
    '18': ['native','home'], '19': ['rent','owner'], '20': ['children','bachelors_plus'],
    '21': ['native','home'], '22': ['native','wfh'], '23': ['age','seniors'],
    '24': ['income','masters'], '25': ['doctorate','bachelors_plus'],
    '26': ['native','owner'], '27': ['owner','income'], '28': ['home','poverty'],
    '29': ['rent','masters'], '30': ['foreign','age'], '31': ['children','home'],
    '32': ['native','foreign'], '33': ['poverty','age'], '34': ['foreign','highincome'],
    '35': ['hispanic','doctorate'], '36': ['owner','foreign'],
    '37': ['wfh','home'], '38': ['age','rent'], '39': ['native','home'],
    '40': ['home','children'], '41': ['wfh','home'], '42': ['native','seniors'],
    '44': ['foreign','home'], '45': ['owner','seniors'], '46': ['rent','children'],
    '47': ['native','home'], '48': ['hispanic','children'], '49': ['age','children'],
    '50': ['seniors','bachelors_plus'], '51': ['masters','highincome'],
    '53': ['wfh','home'], '54': ['owner','home'], '55': ['native','highschool_plus'],
    '56': ['population','native'],
}


def estimates(rows, state, metric):
    d = rows[state]
    def total(codes, subtract=False):
        values, moes = [], []
        for c in codes:
            row = d[c]
            if row['estimate_status'] != 'observed':
                raise ValueError('Unobserved value: ' + state + ' ' + c)
            values.append(float(row['estimate']))
            moes.append(float(row['moe']) if row['moe'] else None)
        value = values[0] - sum(values[1:]) if subtract else sum(values)
        # Controlled population MOE is not estimated; preserve that distinction.
        moe = math.sqrt(sum(x*x for x in moes)) if all(x is not None for x in moes) else None
        return value, moe
    numerator, nmoe = total(metric['variables'])
    if not metric['denominator']:
        return numerator, nmoe, numerator, None
    denominator, dmoe = total(metric['denominator'], metric.get('denominator_mode') == 'subtract')
    value = 100 * numerator / denominator
    # Approximation for subset proportions from published ACS component MOEs.
    if nmoe is None:
        moe = None
    elif dmoe is None:
        moe = 100 * nmoe / denominator  # denominator is population-controlled
    else:
        term = nmoe*nmoe - (numerator / denominator)**2 * dmoe*dmoe
        if term < 0:
            term = nmoe*nmoe + (numerator / denominator)**2 * dmoe*dmoe
        moe = 100 * math.sqrt(term) / denominator
    return value, moe, numerator, denominator


def shown(value, unit):
    if unit.startswith('USD'):
        return '$' + f'{value:,.0f}'.replace(',', ' ')
    if unit == 'people':
        return f'{value:,.0f}'.replace(',', ' ')
    suffix = '%' if unit == 'percent' else ' года'
    return f'{value:.1f}'.replace('.', ',') + suffix


def headline(key, value, unit):
    n = shown(value, unit)
    templates = {
        'age': 'Медианный возраст жителей — {n}',
        'population': 'Весь штат — {n} жителей по оценке ACS',
        'income': 'Медианный доход домохозяйства — {n} в год',
        'home': 'Медианная стоимость собственного жилья — {n}',
        'rent': 'Медианная валовая аренда — {n} в месяц',
        'wfh': '{n} работающих жителей работают из дома',
        'owner': 'Собственники занимают {n} занятого жилья',
        'foreign': '{n} жителей родились за пределами США',
        'native': 'В этом штате родились {n} его нынешних жителей',
        'masters': 'Степень магистра имеют {n} жителей в возрасте 25+',
        'doctorate': 'Докторскую степень имеют {n} жителей в возрасте 25+',
        'bachelors_plus': 'Бакалавриат или более высокую степень имеют {n} жителей 25+',
        'highschool_plus': '{n} жителей 25+ окончили high school или имеют более высокое образование',
        'poverty': '{n} жителей с определённым статусом бедности находятся ниже её федеральной черты',
        'highincome': '{n} домохозяйств получают не менее $200 000 в год',
        'seniors': '{n} жителей — в возрасте 65 лет и старше',
        'children': 'Дети младше 18 лет составляют {n} населения',
        'male': 'Мужчины составляют {n} населения',
        'hispanic': '{n} жителей относят себя к Hispanic or Latino',
        'black': '{n} жителей — non-Hispanic Black or African American alone',
        'asian': '{n} жителей — non-Hispanic Asian alone',
        'severe_rent': '{n} арендаторов с рассчитанной долей расходов отдают на жильё не менее половины дохода',
    }
    return templates[key].format(n=n)


MEMORABLE = {
    ('06','foreign'): 'Больше четверти жителей Калифорнии родились за пределами США',
    ('08','wfh'): 'В Колорадо из дома работает примерно каждый пятый работающий житель',
    ('12','seniors'): 'Более пятой части жителей Флориды — люди в возрасте 65+',
    ('15','home'): 'На Гавайях медианная стоимость собственного жилья превышает $800 000',
    ('22','native'): 'Больше трёх четвертей жителей Луизианы родились в самом штате',
    ('23','age'): 'В Мэне медианный возраст жителей — почти 45 лет',
    ('25','doctorate'): 'В Массачусетсе докторская степень встречается почти вдвое чаще, чем в среднем по США',
    ('26','native'): 'Больше трёх четвертей жителей Мичигана родились в самом штате',
    ('32','native'): 'Меньше трети жителей Невады родились в самой Неваде',
    ('34','foreign'): 'Почти каждый четвёртый житель Нью-Джерси родился за пределами США',
    ('35','hispanic'): 'Почти половина жителей Нью-Мексико относят себя к Hispanic or Latino',
    ('38','rent'): 'В Северной Дакоте медианная валовая аренда ниже $1 000 в месяц',
    ('46','rent'): 'В Южной Дакоте медианная валовая аренда ниже $1 000 в месяц',
    ('48','children'): 'В Техасе примерно каждый четвёртый житель — младше 18 лет',
    ('49','children'): 'В Юте дети младше 18 лет составляют больше четверти населения',
    ('54','owner'): 'В Западной Вирджинии собственники занимают почти три четверти занятого жилья',
}


def verify_api(rows, used_variables):
    secret = None
    for line in (Path.home() / '.config/usa-atlas/credentials.env').read_text().splitlines():
        if line.startswith('CENSUS_API_KEY='):
            secret = shlex.split(line.split('=',1)[1])[0]
    if not secret:
        raise ValueError('Census key not present in configured credential file')
    HERE.joinpath('raw').mkdir(exist_ok=True)
    variables = sorted({v+s for v in used_variables for s in ('E','M')})
    receipts = []
    compared = 0
    for i in range(0, len(variables), 49):
        pack = variables[i:i+49]
        for geo in ('state:*','us:1'):
            query = {'get': 'NAME,' + ','.join(pack), 'for': geo}
            safe_url = 'https://api.census.gov/data/2024/acs/acs5?' + urllib.parse.urlencode(query)
            wire_url = safe_url + '&key=' + urllib.parse.quote(secret)
            try:
                with urllib.request.urlopen(wire_url, timeout=30) as r:
                    raw = r.read()
                data = json.loads(raw)
            except Exception as exc:
                raise RuntimeError('Census verification failed: ' + type(exc).__name__) from None
            if not isinstance(data, list) or not data or data[0][0] != 'NAME':
                raise ValueError('Unexpected Census verification schema')
            filename = f'acs5-2024-{geo.split(":")[0]}-pack-{i//49:02}.json'
            (HERE / 'raw' / filename).write_bytes(raw)
            for values in data[1:]:
                d = dict(zip(data[0], values))
                state = d['state'] if 'state' in d else 'US'
                for variable in pack:
                    code, suffix = variable[:-1], variable[-1]
                    row = rows[state][code]
                    value = row['estimate'] if suffix == 'E' else (row['moe'] or row['moe_code'])
                    if d[variable] != value:
                        raise ValueError('API mismatch: ' + state + ' ' + variable)
                    compared += 1
            receipts.append({'url': safe_url, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                             'artifact': 'raw/' + filename, 'sha256': hashlib.sha256(raw).hexdigest(),
                             'rows': len(data)-1, 'variables': len(pack), 'matched_existing_evidence': True})
            time.sleep(1.05)
    dump('api-verification.json', {'status': 'verified', 'cells_compared': compared, 'requests': receipts})


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--verify-api', action='store_true')
    args = args.parse_args()
    rows, names, receipts = load()
    facts = []
    used = set()
    for state, keys in SELECTION.items():
        for order, key in enumerate(keys, 1):
            metric = METRICS[key]
            value, moe, numerator, denominator = estimates(rows, state, metric)
            usvalue, usmoe, _, _ = estimates(rows, 'US', metric)
            codes = list(dict.fromkeys(metric['variables'] + metric['denominator']))
            used.update(codes)
            table = metric['variables'][0].split('_')[0]
            ranks = sorted([estimates(rows, s, metric)[0] for s in RU if s != '11'], reverse=True)
            rank = 1 + sum(x > value for x in ranks) if state != '11' else None
            caveats = ['Период 2020–2024; это оценка обследования, а не состояние на сегодня.',
                       'Место в рейтинге точечных оценок не используется в заголовке; статистическая значимость ранга не проверена.']
            if metric['caveat']:
                caveats.append(metric['caveat'])
            if metric['denominator']:
                caveats.append('Процент рассчитан из официальных числителя и знаменателя; производная MOE приблизительна.')
            if key == 'owner':
                caveats.append('MOE знаменателя приближённо рассчитана из owner+renter; ковариация не учтена.')
            if key == 'severe_rent':
                caveats.append('MOE разности Total − Not computed рассчитана приближённо без ковариации.')
            detail = f'По ACS 2020–2024: {metric["label"].lower()} — {shown(value, metric["unit"])}; оценка США за тот же период — {shown(usvalue, metric["unit"])}.'
            if metric['unit'] == 'USD_2024':
                detail += ' Доход приведён к долларам 2024 года.'
            if metric['caveat']:
                detail += ' ' + metric['caveat']
            facts.append({
                'fact_id': f'US-{state}-ACS2024-{key}', 'state_fips': state,
                'state_name': names[state], 'state_name_ru': RU[state],
                'state_kind': 'federal_district' if state == '11' else 'state',
                'display_order': order, 'headline_ru': MEMORABLE.get((state,key), headline(key, value, metric['unit'])),
                'detail_ru': detail, 'linked_field_ids': metric['ids'],
                'link_kind': 'contextual' if key == 'native' else 'same_metric_or_explicit_derived_metric',
                'topic': key, 'statistic': metric['label'], 'value': round(value, 6),
                'unit': metric['unit'], 'source_year': 2024, 'source_period': '2020-2024',
                'scope': 'state' if state != '11' else 'federal_district',
                'universe': metric['universe'], 'denominator_value': denominator,
                'numerator_value': numerator, 'source_variables': codes,
                'derivation': {'numerator': metric['variables'], 'denominator': metric['denominator'],
                               'denominator_operation': metric.get('denominator_mode', 'sum')},
                'coverage': 'All 50 states and DC; Puerto Rico excluded from displayed cards and state ranks',
                'national_comparison_value': round(usvalue,6),
                'rank_50_states_by_point_estimate_desc': rank, 'rank_is_display_claim': False,
                'moe_90': round(moe,6) if moe is not None else None,
                'moe_unit': metric['unit'],
                'moe_status': 'derived_approximate' if metric['denominator'] else rows[state][metric['variables'][0]]['moe_status'],
                'source_url': receipts[table]['source_url'],
                'source_title': f'U.S. Census Bureau, 2020–2024 ACS 5-Year Detailed Table {table}',
                'human_source_url': f'https://data.census.gov/table/ACSDT5Y2024.{table}?g=040XX00US{state}',
                'metadata_url': f'https://api.census.gov/data/2024/acs/acs5/groups/{table}.html',
                'published_date': '2026-01-29', 'retrieved_date': receipts[table]['retrieved_at'],
                'reviewed_date': DATE, 'verification_status': 'verified_primary_numeric',
                'display_ready': True, 'valid_until': None, 'recheck_on_or_before': '2027-01-31',
                'recheck_instructions': 'Сохранять период 2020–2024 в карточке. Перед сменой винтажа проверить выпуск ACS 2025 5-year, определения, MOE и национальный benchmark; не смешивать ACS 1-year и 5-year.',
                'caveats': caveats,
            })
    if args.verify_api:
        verify_api(rows, used)
    supplement_path = HERE / 'supplemental-facts.json'
    if supplement_path.exists():
        for supplement in json.loads(supplement_path.read_text()):
            fact = dict.fromkeys(facts[0])
            fact.update({'rank_is_display_claim': False, 'display_order': 3,
                         'valid_until': None, 'reviewed_date': DATE,
                         'denominator_value': None, 'national_comparison_value': None,
                         'moe_status': 'not_applicable'})
            fact.update(supplement)
            fact.update({'state_name': names[fact['state_fips']],
                         'state_name_ru': RU[fact['state_fips']],
                         'state_kind': 'federal_district' if fact['state_fips']=='11' else 'state'})
            facts.append(fact)
    for fact in facts:
        fact['display_conditions'] = ['Показывать источник и период/дату факта рядом с карточкой.',
                                      'Сохранять scope и ограничения в доступном пояснении.']
        if fact['link_kind'] == 'contextual':
            fact['display_conditions'].append('Контекстная связь с полем не означает, что это его измеренное значение или доказанная причинная связь.')
    dump('facts.json', {'schema_version': 1, 'as_of': DATE,
                        'display_requires_period_and_source': True, 'facts': facts})
    dump('claims.json', {'schema_version': 1, 'as_of': DATE,
                        'status': 'ready_research_snapshot',
                        'production_admitted': False,
                        'claims': [x for x in facts if x['display_ready']]})
    with (HERE/'facts.csv').open('w',newline='') as f:
        out = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for fact in facts for k in fact)))
        out.writeheader()
        for fact in facts:
            out.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in fact.items()})
    counts = Counter(x['state_fips'] for x in facts)
    if len(counts) != 51 or any(v < 2 for v in counts.values()):
        raise ValueError('Incomplete state coverage')
    if any(not x['linked_field_ids'] or not x['source_url'].startswith('https://') for x in facts):
        raise ValueError('Missing source or field mapping')
    dump('coverage.json', {'states_covered': 50, 'dc_covered': True,
                          'cards': len(facts), 'display_ready': len(facts),
                          'acs_cards':sum(x['verification_status']=='verified_primary_numeric' for x in facts),
                          'supplemental_cards':sum(x['verification_status']!='verified_primary_numeric' for x in facts),
                          'topic_counts': dict(Counter(x['topic'] for x in facts)),
                          'state_card_counts': dict(sorted(counts.items())),
                          'validation': 'Coverage, source hashes, observed numeric status and field/source presence checked during build'})
    print(json.dumps({'cards':len(facts), 'states':50, 'dc':True, 'topics':len({x['topic'] for x in facts})}))


if __name__ == '__main__':
    main()
