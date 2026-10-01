# Допуск новых детальных данных: анализ совместимости

Это рекомендации после чтения текущих `database/load.py`, `database/schema.sql` и UI `scripts/atlas_data.py`. Во время анализа агент БД отдельно выполняет уплотнение хранения. Этот документ не является миграцией, prodDB не изменяет.

## Непосредственные различия

| Сейчас | Новые данные | Требуемое решение |
|---|---|---|
| Loader читает JSONL, один конечный `value`, строго 13 ключей | CSV gzip с парой E/M, missing/suppression statuses, source tokens; CDC — estimate + CI | Новый admission adapter и явная схема quality/uncertainty; простое переименование файла недостаточно |
| `source` обязан совпадать с `rate_limit_profile` контракта | Runner provider называется `acs-summary` | При admission source должен быть `census_acs`; acquisition adapter и источник — разные сущности |
| Manifest ожидает `sources.<source>.status=pass`, один normalized artifact и точный row count | Независимые 19 table jobs, каждый с hash/coverage | Отдельный admission manifest объединяет проверенные артефакты, не переписывает исторический fail на pass |
| Fact `value NOT NULL`, finite number | Suppressed/missing estimates и nonnumeric MOE статусы обязательны | Сохранить quality rows/nullable observations с контролируемыми status codes; не превращать их в 0 и не терять |
| `catalog_field_id` встроен в каждый fact | Один B01001 fact служит и Age, и Sex | Нормальная связь catalog→series предотвращает повторение одного набора наблюдений |
| Ключ fact не включает `geo_type` | County и ZIP могут иметь одинаковый пятизначный ID | Добавить typed geography FK/ключ; для текущих ACS уровней длины различны, но общая модель уже требует типа |
| Catalog source variables для poverty — B17001 | B17021 даёт poverty counts на 242 297 BG | Зарегистрировать отдельную source variant: universe и числовая эквивалентность проверены; не менять source lineage задним числом |
| County PLACES — age-adjusted | Tract PLACES — crude prevalence | Отдельная variant + CI + 2023 observation year + 2023 tract vintage |

`validate_record` сегодня отвергает дополнительные quality-ключи и `None` в value. Поэтому загрузка только numeric subset через старый loader была бы неполной: SQL-потребитель потеряет различие между отсутствующей географией, отсутствующим estimate, suppressed и controlled MOE. Хранить это только в свободном `methodology_note` также нежелательно: один note на каждую строку разрушит выгоду от вынесения повторяющейся методологии в справочник и затруднит фильтры.

Рекомендуемый минимальный новый факт: `(source_series_id, geo_key, period, release_id, estimate, moe, estimate_status_id, moe_status_id, source_token_ids, ingest_id)`. Для CDC — отдельные CI low/high и variant. Source URL, retrieval timestamp, release, geography vintage, единицы, universe и описание переменной привязаны к series/release/resource, а не размножены в каждой строке. Дата загрузки уже есть в новом raw manifest; она отличается от 2024 release label и периода ACS 2020–2024.

## Практический adapter-план

1. После завершения collection проверять current code/contract/plan bindings, raw/normalized SHA-256, уникальность `(geo_type, geo_id, variable, release)`, все требуемые table jobs и количество строк. Географическое покрытие каждой таблицы проверяется отдельно: B19301 уже имеет меньше опубликованных BG, чем B01003.
2. Построить небольшой dictionary `source_series → catalog fields`: E/M-переменные и labels, unit, universe, transformation. Существующие 81 catalog IDs сохраняются, source-series IDs версионируются. Формулы из `derivation` не считать исполненными лишь потому, что исходные counts скачаны.
3. Для прямых показателей (population, median age, median income/rent/home value) допускать соответствующую E-серию и её MOE. Для shares/ratios проверять denominator, нулевой denominator, sample universe, совместное наличие E/M и корректную формулу неопределённости. Старый родитель `Age` не должен по алфавиту выбирать B01001 total population вместо median age B01002.
4. Стримить gzip CSV непосредственно в staging/COPY, сохраняя provenance IDs и quality; не создавать временный многогигабайтный JSONL с повторяющимися ссылками. Каждый admitted partition/table имеет собственный counts/hash; atomic publish делает слой видимым только после проверок.
5. Новые fact/quality таблицы и совместимый read view проектировать после завершения текущей compact migration. Loader защищает физическую схему digest-ом `EXPECTED_SCHEMA_CATALOG_SHA256`: обновление выполняется согласованно со схемой и integration tests, а не отключением проверки.

## UI и производительность

UI сейчас дважды фильтрует наблюдения `geo_type IN ('state','county')`, а `canonical_geo()` отвергает все другие типы. Простой admission BG не покажет их на карте. Нужны typed geography support, boundaries правильного vintage, bbox/parent filters, zoom-dependent tiles и bounded responses. API не должно отдавать 242 тыс. BG целиком на одну интеракцию.

`catalog()` сейчас группирует все факты на каждый запрос. После многомиллионного ACS слоя такой подход нужно заменить небольшим coverage/series summary, обновляемым по завершении admission. Не следует показывать каждую MOE как отдельный пользовательский показатель: UI выбирает measure, а uncertainty и quality получает рядом с estimate.

Extension worker завершён и сохранил `metric-equivalence.json`: 177 208 общих county/tract E/M-пар B17021 против B17001 и 175 090 пар B05012 против B05002 совпали по estimate, MOE и quality; mismatches и unmatched candidate pairs — 0. Universe подтверждены скачанным official 2024 Data Product List и сохранены в `metadata/table-universes-and-restrictions.json`. B17021 даёт 242 297 BG с тем же poverty universe; B05012 официально исключает BG и Puerto Rico. Он описывает только total/native/foreign-born и не заменяет полный 27-variable nativity/citizenship breakdown B05002. Равенство общих измерений позволяет подготовить явный alias выбранных counts, но не молча заменить lineage всей таблицы.
