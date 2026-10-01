# Региональные порталы: действующий сбор и поиск пробелов

Снимок: 2026-09-28. Все шесть разрешённых источников скачаны целиком в пределах выбранного регионального слоя/экспорта. **70 443 строки источников**: широкие записи и группы агрегирования, а не число нормализованных метрик основного сборщика. Источники не охватывают все США; production admission пока `needs_review`.

## Что лежит на сервере

| Источник | Строк | География и период | Что ограничивает использование |
|---|---:|---|---|
| CA DWR доходы/DAC | 25 607 | Все 58 counties California, Census 2020 block groups, ACS 2019–2023 | MHI, население, households; в слое нет ACS MOE. 1 580 групп имеют `DAC23=Data not available`; это не нулевой доход. |
| CA DWR water vulnerability | 25 607 | Все 58 counties; provider block groups; анализ обозначен 2024 | В метаданных конфликтуют 2020/2021 boundaries и периоды ACS; canonical boundary vintage оставлен `null`. |
| Loudoun existing/permitted data centers | 239 | Официальные точки коммерческих зданий; слой назван 3/1/2026, editingInfo 2026-06-11 | 187 `BUILT`, 52 `UNDER CONSTRUCTION`, 238 различных building/unit IDs. Это 239 записей, не 239 работающих независимых дата-центров. |
| DC MPD 2025 | 2 840 | Provider BG × tract × offense; 24 153 incident reports | Проверена сумма групп против полного count API; 6 incident reports без BG. |
| DC MPD 2026 | 2 635 | Те же агрегаты; 16 049 incident reports на дату скачивания | **YTD, неполный 2026 год**, 11 incident reports без BG; возможны последующие исправления. |
| NY income tax table 4 | 13 515 | County labels/итоги × income band × tax year, 1999–2014 | Историческая таблица timely-filed resident returns, 87 строк с disclosure `d/`. Не текущая налоговая статистика. |

Полные данные: `runtime/normalized/*.jsonl.gz`. Исходные HTTP-ответы: `runtime/raw/`; для каждого запроса сохранены URL, конечный URL, время, headers, SHA-256 исходного тела и gzip-файла. Итоговые [manifests](manifests/) и [summary](collection-summary.json) содержат counts, пути и hashes. [samples](samples/) — только по три строки каждого источника, не полные выгрузки. `runtime/` исключён из Git; manifests, samples, конфигурация и код остаются в репозитории.

### Значение показателей

- CA `MHI23`: median household income из ACS; `Pop23` — население, `HH23` — households. Не средняя зарплата. `DAC23` — классификация DWR, не самостоятельная замена poverty rate.
- Water `Percent_Poverty` по alias означает долю населения ниже **200% poverty level**, не стандартную долю ниже 100%. `DomesticWell1977_Count` считает зарегистрированные domestic wells с 1977; это не запасы воды. `Total_Score` — индекс социальной уязвимости, не физический объём водоснабжения.
- Loudoun `AM_LOUD_ID`/`AM_LOUD_UNIT_ID` сохранены для проверки дубля; координаты относятся к коммерческим объектам. Адрес, parcel ID и персональные поля не запрашиваются. `YEAR_BUILT=1000` — source sentinel. Старый PDF давал 233 здания; расхождение с live layer не скрыто и требует согласования версий/единиц.
- MPD считает incident reports, не жертв, смерти или rate на 100 тысяч. Загружаются только серверные агрегаты; event-level строки, имена, адреса и координаты происшествий не сохраняются. Реальный ArcGIS API возвращает alias `INCIDENT_COUNT`; нормализация подтверждена по ответам. BG/tract присвоены самим MPD до обобщения координат; vintage не подтверждён, поэтому `geo_type=provider_block_group`. Собственный spatial join не выполнялся.
- NY единица — tax return, суммы AGI/tax в тысячах долларов. Верхний income band — $500 000+ (для части лет $200 000+). **Нельзя получить ни AGI≥$1m, ни число миллионеров по wealth.** Totals и suppressed rows не суммируются автоматически. Идентификаторы county пока source-native, без предположительного FIPS.

## Проверка официальности и доступ

[portals.json](portals.json) содержит семь порталов: California, CNRA, New York State, NYC, Loudoun, DC, Virginia. Socrata catalog ограничивается `domains=…` и проверяет domain каждого результата; `search_context` для такой проверки недостаточно. ArcGIS search ограничивается подтверждённым organization ID, чтобы не собирать учебные копии слоёв.

Первичные цепочки:

- [CA income catalog](https://catalog.data.gov/dataset/i16-census-blockgroup-disadvantagedcommunities-2023) → DWR/CNRA ArcGIS → официальный CSV export. Каталог указывает CC BY и boundary vintage 2020.
- [CA water catalog](https://catalog.data.gov/dataset/i07-water-shortage-social-vulnerability-blockgroups) и [DWR layer](https://gis.water.ca.gov/arcgis/rest/services/Environment/i07_Water_Shortage_Social_Vulnerability_BlockGroups/MapServer/0) фиксируют неоднозначность годов. Metadata сохранены до нормализации.
- [Loudoun County](https://www.loudoun.gov/DataCenters) → официальный Experience app `0c2021535c3f47589d1a10d6d0e2948c` → public map → layer item `ebd6a01332b74483a83ba10352d5fd51`, organization `MxjRokvPm7bjslyR`.
- [DC/MPD catalog](https://catalog.data.gov/dataset/crime-incidents-in-2025) → owner `DCGISopendata`, organization `neT9SoYxizqTHZPH`. Лицензия CC BY 4.0.
- [NY DTF table metadata](https://data.ny.gov/api/views/5kgr-h5g5.json), [NYC official open data](https://www.nyc.gov/opendata), [Virginia government directory](https://www.virginia.gov/state-government/) подтверждают владельцев порталов.

Для CA ArcGIS proxy `query` возвращал error 500; прямой `gis.water.ca.gov` из процесса истекал по timeout. Рабочий путь — CNRA Hub CSV, перенаправляющий на `hub.arcgis.com/api/v3/datasets/.../downloads/data`. Прочитан весь CSV-ответ, проверены уникальные source IDs/GEOIDs и все 58 CA counties. Независимый `returnCountOnly` недоступен: размер экспорта не объявляется сверенным с live service. Water export также не содержит четырёх metadata columns, присутствующих в layer schema; это явно записано в sources/manifest.

Условия NY: использовать для статистических отчётов/анализа; любые приведённые здесь анализ, интерпретации и выводы принадлежат авторам, а не New York State Department of Taxation and Finance.

## Поиск при отсутствии источника или нужной географии

Каждый цикл читает `geography/live-coverage.json` и `full/field-contract.json`, сохраняет их SHA-256 в [gap-intake.json](gap-intake.json). Поля без native BG попадают в intake с field ID, требуемой географией, фактическими уровнями и исходным статусом. Отсутствие BG в этой сводке не означает отсутствия других national/local данных в соседних workstreams.

[query-seeds.json](query-seeds.json) задаёт явные термины и порталы для известных полей. Новые незнакомые поля получают `needs_query_definition`; определение нельзя безопасно угадать по заголовку. Семь food IDs `08.01/02/03/06`, `09.01/02/03` исключены. На первом снимке intake: **56 полей и 90 уникальных поисковых запросов**, плюс 14 первоначальных запросов по water, taxes, crime, homelessness и data centers. Числа изменятся при обновлении live coverage.

За цикл выполняется максимум 16 запросов; сначала новые, затем самые давно проверенные. Для одного запроса читается страница по 20 кандидатов, курсор продолжается в последующих циклах максимум до 100 результатов, после чего поиск начинается заново. `search_complete=false` честно отмечает усечённую выдачу. [candidates](candidates/) сохраняет кандидатов с URL/resources и hash ответа; raw страницы остаются локально.

Статусы:

- `not_available`: конкретный запрос вернул 0 результатов; не утверждение, что данных не существует.
- `needs_review`: найден кандидат либо возникла ошибка API/schema; нужны проверка publisher, единицы, coverage, privacy и определения.
- `source_matched`: найден уже известный разрешённый источник; совпадение не означает пригодность для production metric.
- `source_collected`: весь разрешённый региональный export/слой скачан и прошёл проверки целостности.

Автосбор разрешён **только** для шести вручную проверенных записей [sources.json](sources.json). Новые результаты поиска не превращаются в сборщики автоматически. Отдельные поля `review_status=validated_for_aggregate_download` и `production_admission=needs_review` разделяют проверку допустимости скачивания и проверку пригодности метрики.

## Постоянный процесс

Работает systemd service **`usa-atlas-local-portals.service`**, `enabled`, `Restart=on-failure`, restart delay 60 секунд. Фактический unit: `/etc/systemd/system/usa-atlas-local-portals.service`; [копия в репозитории](usa-atlas-local-portals.service) привязана к пути этого сервера.

```bash
systemctl status usa-atlas-local-portals.service --no-pager
python3 research/2026-09-28/local-portals/collect_local.py status
tail -n 30 research/2026-09-28/local-portals/runtime/daemon.log
```

Loop раз в 6 часов; каждый catalog query не чаще 24 часов. Сбор DC/Loudoun — daily, CA — weekly, исторического NY — monthly. Ошибка источника повторяется не чаще 6 часов. Один HTTP-запрос: до 3 попыток, timeout 45 секунд, паузы 2/4 секунды, максимальный ответ 40 MB. Между запросами минимум 0.12 секунды.

`flock` предотвращает второй одновременный процесс. PID: `runtime/collector.pid`, состояние/время/cursor: `runtime/state.json`, лог: `runtime/daemon.log`. Завершённые datasets пропускаются до наступления cadence; при обрыве незавершённый источник собирается заново, его partial raw сохраняется отдельно. Завершённый normalized файл публикуется atomic rename только после проверок. Отчёт [status.json](status.json) — снимок, актуальное состояние даёт команда выше.

Это постоянный программный цикл каталогов и разрешённых загрузок. После завершения диалога никакой LLM-агент автоматически не решает спорные определения и не одобряет новые схемы.
