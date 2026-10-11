# Реестр 35 полей карты — D1, D2 и D5

Проверен исходный runtime `20261011-collected35` с базой `2e9280d` и сохранёнными хешами незакоммиченных файлов. PROD прочитан READ ONLY 2026-10-11T14:20:13.745328+00:00; HTTP-снимок — 2026-10-11T14:19:16.497337+00:00. Более поздние три медицинских поля исключены фиксированным списком видимости.

Готовы отдельный реестр и проверенные вычисления; интерфейс и исходные наблюдения не изменены. [CSV](metric-registry.csv), [JSON](metric-registry.json), [машинные определения](../../../full/map-metric-definitions.json), [примеры формул](formula-examples.json).

`2024` для ACS означает оценку за **2020–2024**, не годовую статистику. `source_defined` восстановлен по конкретной переменной, поэтому исходный count в таблице ниже не становится процентом без числителя и знаменателя.

| ID | Поле каталога | Выбранная подсерия | Источник / период | Выпуск | Восстановленная исходная единица |
|---|---|---|---|---|---|
| 01.01 | Population | 01.01:B01003_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 01.02 | Age | 01.02:B01001_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 01.03 | Sex | 01.03:B01001_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 01.04 | Race / ethnicity | 01.04:B03002_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 01.05 | Foreign-born population | 01.05:B05002_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 01.06 | Country / region of birth | 01.06:B05006_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 01.07 | Citizenship | 01.07:B05001_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 01.08 | Year / period of immigration | 01.08:B05005_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 02.01 | Median household income | 02.01:B19013_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | USD |
| 02.02 | Per-capita income | 02.02:B19301_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | USD |
| 02.03 | Median rent | 02.03:B25064_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | USD |
| 02.04 | Median home value | 02.04:B25077_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | USD |
| 02.05 | Mortgage / selected monthly owner costs | 02.05:B25088_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | USD |
| 02.06 | Rent as % of income / rent burden | 02.06:B25070_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | housing_units |
| 02.07 | Owner / renter ratio | 02.07:B25003_002E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | housing_units |
| 02.08 | Poverty | 02.08:B17001_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 02.09 | Households earning $200k+ | 02.09:B19001_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | households |
| 02.10 | Cost of living / Regional Price Parities | 02.10 | bea_rpp / 2024 | BEA-SARPP-2024-release-2026-02-19 | index_us_100 |
| 03.01 | Bachelor's degree | 03.01:B15003_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 03.02 | Master's degree | 03.02:B15003_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 03.03 | Doctorate | 03.03:B15003_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 03.04 | High school attainment | 03.04:B15003_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 03.05 | No diploma | 03.05:B15003_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | persons |
| 03.06 | Unemployment | 03.06:unemployment_rate | bls_laus / 2024-M12 | BLS-LAUS-2024 | % |
| 03.09 | Work from home share | 03.09:B08301_001E | census_acs / 2020–2024 (stored 2024) | 2024-acs-acs5 | workers |
| 04.01 | Murders | 04.01 | fbi_cde / 2023 | FBI-CDE-2019-2023 | count |
| 04.02 | Violent crime | 04.02 | fbi_cde / 2023 | FBI-CDE-2019-2023 | count |
| 04.03 | Robbery | 04.03 | fbi_cde / 2023 | FBI-CDE-2019-2023 | count |
| 04.04 | Aggravated assault | 04.04 | fbi_cde / 2023 | FBI-CDE-2019-2023 | count |
| 04.05 | Burglary | 04.05 | fbi_cde / 2023 | FBI-CDE-2019-2023 | count |
| 04.06 | Motor vehicle theft | 04.06 | fbi_cde / 2023 | FBI-CDE-2019-2023 | count |
| 04.07 | Rape | 04.07 | fbi_cde / 2023 | FBI-CDE-2019-2023 | count |
| 07.01 | Adjusted Gross Income (AGI) | 07.01:A00100:county_sum_agi_stubs_1_8 | irs_soi / 2023 | IRS-SOI-COUNTY-2023 | thousand_USD |
| 08.05 | Electricity price | 08.05:sector_ALL | eia / 2024 | EIA-electricity-retail-sales-2024 | cents per kilowatt-hour |
| 09.04 | Fitness / recreation centers per capita | 09.04 | usda_fea / 2020 | USDA-FEA-2025 | facilities_per_1000_persons |

Уровни ниже относятся **к выбранной подсерии, периоду и выпуску**, а не ко всем подсериям родительского поля. Для nation/state/county есть точные counts в JSON. На остальных уровнях присутствие подтверждается совпавшей записью в ограниченной индексной выборке; `?` означает, что полное отсутствие не доказано. Counts state могут включать PR, США или региональные коды; это не количество штатов США.

| ID | Native уровни | Проверенное значение / требуемый выбор | Единица результата |
|---|---|---|---|
| 01.01 | nation, state, county, place, tract, block_group | B01003_001E | people |
| 01.02 | nation, state, county, place, tract, block_group | Choose median age or an explicit age band; the current total is population, not age. | Требуется выбор |
| 01.03 | nation, state, county, place, tract, block_group | Choose a sex category or breakdown; the current total is population. | Требуется выбор |
| 01.04 | nation, state, county, place, tract, block_group | Choose an explicit race/origin category; the current total is population. Race and Hispanic origin differ. | Требуется выбор |
| 01.05 | nation, state, county, place, tract | (B05002_013E) / (B05002_001E) × 100 | % |
| 01.06 | nation, state, county, place, tract | Choose a country/region and foreign-born denominator; the current value is the total foreign-born population. | Требуется выбор |
| 01.07 | nation, state, county, place, tract | Choose citizenship status or distribution; the current value is total population. | Требуется выбор |
| 01.08 | nation, state, county, place, tract | Choose entry period and nativity; the current total includes all persons born outside the US, including native citizens. | Требуется выбор |
| 02.01 | nation, state, county, place, tract, block_group | B19013_001E | 2024 USD/year |
| 02.02 | nation, state, county, place, tract, block_group | B19301_001E | 2024 USD/year |
| 02.03 | nation, state, county, place, tract, block_group | B25064_001E | USD/month |
| 02.04 | nation, state, county, place, tract, block_group | B25077_001E | USD |
| 02.05 | nation, state, county, place, tract, block_group | B25088_001E; Current median covers all owners. With-mortgage-only B25088_002E is a separate explicit choice. | USD/month |
| 02.06 | nation, state, county, place, tract, block_group | (B25070_007E + B25070_008E + B25070_009E + B25070_010E) / (B25070_002E + B25070_003E + B25070_004E + B25070_005E + B25070_006E + B25070_007E + B25070_008E + B25070_009E + B25070_010E) × 100 | % |
| 02.07 | nation, state, county, place, tract, block_group | (B25003_002E) / (B25003_003E) | ratio |
| 02.08 | nation, state, county, place, tract, block_group? | (B17001_002E) / (B17001_001E) × 100 | % |
| 02.09 | nation, state, county, place, tract, block_group | (B19001_017E) / (B19001_001E) × 100 | % |
| 02.10 | state, metro | 02.10 | index · US = 100 |
| 03.01 | nation, state, county, place, tract, block_group | (B15003_022E) / (B15003_001E) × 100 | % |
| 03.02 | nation, state, county, place, tract, block_group | (B15003_023E) / (B15003_001E) × 100 | % |
| 03.03 | nation, state, county, place, tract, block_group | (B15003_025E) / (B15003_001E) × 100 | % |
| 03.04 | nation, state, county, place, tract, block_group | (B15003_017E + B15003_018E + B15003_019E + B15003_020E + B15003_021E + B15003_022E + B15003_023E + B15003_024E + B15003_025E) / (B15003_001E) × 100 | % |
| 03.05 | nation, state, county, place, tract, block_group | (B15003_002E + B15003_003E + B15003_004E + B15003_005E + B15003_006E + B15003_007E + B15003_008E + B15003_009E + B15003_010E + B15003_011E + B15003_012E + B15003_013E + B15003_014E + B15003_015E + B15003_016E) / (B15003_001E) × 100 | % |
| 03.06 | state, county, block_group? | 03.06:unemployment_rate | % |
| 03.09 | nation, state, county, place, tract, block_group | (B08301_021E) / (B08301_001E) × 100 | % |
| 04.01 | state | 04.01; Preserve reported counts; per-100k comparison needs annual covered population and participation metadata from the same period. | events |
| 04.02 | state | 04.02; Preserve reported counts; per-100k comparison needs annual covered population and participation metadata from the same period. | events |
| 04.03 | state | 04.03; Preserve reported counts; per-100k comparison needs annual covered population and participation metadata from the same period. | events |
| 04.04 | state | 04.04; Preserve reported counts; per-100k comparison needs annual covered population and participation metadata from the same period. | events |
| 04.05 | state | 04.05; Preserve reported counts; per-100k comparison needs annual covered population and participation metadata from the same period. | events |
| 04.06 | state | 04.06; Preserve reported counts; per-100k comparison needs annual covered population and participation metadata from the same period. | events |
| 04.07 | state | 04.07; Preserve reported counts; per-100k comparison needs annual covered population and participation metadata from the same period. | events |
| 07.01 | county, zip? | 07.01:A00100:county_sum_agi_stubs_1_8 × 1000; Display USD by ×1,000; state/US values require separate validated aggregation and disclosure review. | USD |
| 08.05 | state | 08.05:sector_ALL × 0.01 | USD/kWh |
| 09.04 | county | 09.04; Display facilities per 1,000 people; county-only and incomplete numeric coverage. State density requires compatible weights. | facilities/1,000 people |

Образование: Bachelor’s, Master’s и Doctorate — **наивысший завершённый уровень**, не накопительная степень «или выше». High school включает GED и все более высокие уровни; no diploma — 002–016. Варианты owner/renter ratio и owner/renter share имеют разные знаменатели и отдельные ID. Rent burden исключает `Not computed`, не включает весь count арендаторов.

Для широких age/sex/race/birthplace/citizenship/entry-полей сохранены явные варианты. Автоматически назначать одну категорию фронтенду нельзя: продуктовый выбор остаётся открытым. Текущий total — численность соответствующей universe, а не выбранная категория.

Для crime сохранены исходные reported counts и помечен пробел: корректный rate на 100 000 требует годового знаменателя и покрывающей его reporting population. ACS 2020–2024 не используется молча как население 2023 года. Поэтому D5 содержит готовые единицы и контракт, но event rates пока требуют совместимого источника.

USDA fitness — facilities на **1 000** жителей за 2020, выпуск 2025. У выбранной серии только 1 294 county-наблюдения; state плотность нельзя получить суммой округов. AGI хранится в тысячах USD, отображение USD — ×1 000; per-return знаменатель не выбран.

Для штата и США ACS-формулы вычисляются из их **native** компонентов того же выпуска. Медианы округов не усредняются. Национальная BLS-оценка и derived state-sum aggregate имеют разное происхождение; seasonal adjustment state/county различается. BEA сохраняет базу US = 100, EIA all sectors не заменяется residential ценой.

## Исходные и ожидаемые значения: Oregon и США

Данные из bounded PROD-запросов; это значения ACS **2020–2024**. Числители и знаменатели сохранены без округления; округление ниже используется только для чтения. MOE — 90%, вычисляемые интервалы приблизительны, неизвестный MOE не заменяется нулём.

| Формула | Oregon: числитель / знаменатель | Oregon: результат | США: результат |
|---|---|---|---|
| rent-burden-30-plus-share | 312,174 / 594,861 | 52.478478 % | 51.116763 % |
| owner-occupied-share | 1,087,983 / 1,718,422 | 63.312911 % | 65.164260 % |
| owner-renter-ratio | 1,087,983 / 630,439 | 1.725755 ratio | 1.870615 ratio |
| renter-occupied-share | 630,439 / 1,718,422 | 36.687089 % | 34.835740 % |
| poverty-share | 498,380 / 4,173,206 | 11.942377 % | 12.454373 % |
| households-income-200k-plus-share | 218,500 / 1,718,422 | 12.715154 % | 13.361114 % |
| bachelors-degree-exact-share | 690,053 / 3,044,782 | 22.663462 % | 21.605976 % |
| masters-degree-exact-share | 299,124 / 3,044,782 | 9.824152 % | 10.079586 % |
| doctorate-exact-share | 57,364 / 3,044,782 | 1.884010 % | 1.679311 % |
| high-school-or-higher-share | 2,796,561 / 3,044,782 | 91.847659 % | 89.605004 % |
| no-high-school-diploma-share | 248,221 / 3,044,782 | 8.152341 % | 10.394996 % |

## Проверка и использование

Из корня репозитория:

```bash
python3 full/build_map_metric_definitions.py
python3 research/2026-10-11/map-metrics/build_registry.py
python3 -m unittest discover -s full -p test_map_metrics.py
```

`full.map_metrics.calculate(metric_id, admission_rows)` принимает неизменённые source records, проверяет period/release/source/geography/unit и возвращает отдельный derived результат. `comparison_record(result, geo_vintage=..., adjustment=...)` связывает его с `database.map_quality.MetricObservation(**record)`; geography vintage и сезонность задаются явно. JSON содержит реальные input field IDs, исходные значения, source URL и метод неопределённости.

Источники: [ACS five-year guidance](https://www.census.gov/programs-surveys/acs/guidance/estimates.html), [ACS handbook and derived MOE](https://www.census.gov/programs-surveys/acs/library/handbooks/general.html), [BLS seasonal adjustment](https://www.bls.gov/lau/lauseas.htm), [BEA RPP](https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area), [IRS county data](https://www.irs.gov/statistics/soi-tax-stats-county-data), [EIA price data](https://www.eia.gov/electricity/sales_revenue_price/), [USDA definitions](https://www.ers.usda.gov/data-products/food-environment-atlas/documentation/). Конкретные Census variable labels/universes и payload hashes сохранены в [metadata](census-variable-metadata.json).
