# Богатство и дата-центры — первая сессия 2026-10-03

Собраны **403 машиночитаемых наблюдения** из семи открытых government источников/слоёв. Это отдельные исследовательские метрики с реальными скачанными исходными bytes, URL, датами, SHA-256 и flags. Полных текущих чисел жителей-миллионеров, жителей-миллиардеров или работающих дата-центров по всем штатам этот пакет пока не содержит.

| Набор | Реально получено | География и смысл |
|---|---|---|
| Federal Reserve SCF 2022 | Взвешенная оценка **23,684,985 семей** с net worth ≥$1m; **18.04%** из 131,306,389 оцениваемых семей | Национальная оценка, включающая жилищный капитал. Семьи, а не отдельные люди; не точная перепись. Sampling standard error ещё не рассчитана |
| EPA ENERGY STAR | **336** property records; **335** в 31 штате и **1** в Puerto Rico | Историческая добровольная сертифицированная выборка. 31 state observation об ever-certified properties и 338 state/year observations об label years |
| Texas Comptroller | **66** qualifying data-center project rows и **105** large-project rows | Texas. Строки двух tax registries; программы могут перекрываться и проект может иметь несколько зданий. Эти итоги не являются количеством работающих объектов |
| Minnesota DEED | **42** Certified tax-exemption project rows: **16 New**, **26 Refurbishment** | 21 опубликованная City label; документ датирован **2026-07-15**. 10 county кандидатов из Census 2020 reference сохранены отдельно, county итоги пока не допущены |
| Loudoun existing parcel GIS | **139** feature records, **137** разных PA_MCPI после дедупликации | Один county **51107**. 102 BUILT, 28 UNDER CONSTRUCTION, 6 BUILT/UNDER CONSTRUCTION, 1 BULT/UNDER CONSTRUCTION |
| Loudoun pipeline GIS | **85** polygon records | 16 Approved, 18 Approved: Conditionally, 51 Active. Это planning areas, а не работающие здания или подтверждённо разные проекты |
| Loudoun building outlines GIS | **271** building footprint records | Один county **51107**, геометрия EPSG:4326. Описание источника говорит о **August 2024**; новая дата редактирования не делает vintage текущим |

403 наблюдения: 369 EPA + 23 Minnesota + 4 Loudoun existing statuses + 3 pipeline statuses + 2 Texas program rows + 1 building footprint aggregate + 1 SCF estimate. Эти числа описывают объём исследовательского пакета; сложение разных видов объектов не даёт число дата-центров США.

Первая оценка SCF рассчитана на 22,975 implicate rows для 4,595 анонимных обследованных семей. В официальном summary extract `WGT=X42001/5` уже делён на пять: использовано `sum(WGT * I(NETWORTH>=1000000))`, без повторного деления. Официальный macro подтверждает `NETWORTH=ASSET-DEBT`. Межимпутационный диапазон сохранён как диагностический результат, а не confidence interval. Очень богатые Forbes 400 исключаются из sampling frame, поэтому SCF нельзя применять для подсчёта всех миллиардеров. [Данные и методика Federal Reserve](https://www.federalreserve.gov/econres/scfindex.htm).

EPA публикует только state для безопасности. Названия объектов не использованы для восстановления адресов/county. Отсутствие state в списке означает отсутствие подходящей опубликованной записи в этой выборке. В [state coverage](state-coverage.csv) у target population totals стоят пустые значения. Историческая сертификация не подтверждает текущую эксплуатацию. [Первичный список EPA](https://www.energystar.gov/buildings/certified-data-centers).

Texas выявил семь строк с flags: две со multiple registration stems, повторную ссылку на stem другого именованного проекта, две malformed effective dates, отсутствующую expiry cell и несовпадение DC registration prefix с large-project table. Исходные значения сохранены; числа 66/105 — **displayed rows**, не доказанное количество разных физических объектов. Owner/operator/occupant роли не считаются дополнительными проектами. [Официальный registry](https://comptroller.texas.gov/taxes/data-centers/data-center-lists.php), [правила программ](https://comptroller.texas.gov/taxes/data-centers/).

Minnesota PDF скачан и hash-pinned. Перенесены только project name, City, Type и Status; данные компаний/людей не нужны для этих наблюдений. County кандидаты получены из [официальной Census place/county таблицы 2020](https://www.census.gov/library/reference/code-lists/ansi/2020.html), но опубликованная City label может быть postal label, поэтому county totals ожидают location validation. [Документ Minnesota DEED](https://mn.gov/deed/assets/data-center-project-list_tcm1045-531119.pdf).

Loudoun имеет две повторные PA_MCPI: `089496314000` и `194498227000`. Их component statuses совпадают, поэтому в parcel counts каждая считается один раз. Floor area внутри компонентов различается и не суммировалась. Слой footprints, existing parcels и pipeline имеет разные единицы и даты; их нельзя складывать. BUILT не переименован в operational. County ArcGIS item metadata подтверждает владельца `@loudoun.gov_LoudounGIS`; лицензирующая пометка parcel/pipeline допускает public data и просит атрибуцию. Оригинальные геометрии и item metadata сохранены в успешных runs.

Предыдущие IRS ≥$11.4m state estimates и Prince William County здания уже были собраны; они прочитаны и учтены в coverage, их исходные записи здесь не дублировались. В IRS Table 6 действительно другой wealth threshold, а county AGI не является числом миллионеров.

Условия private wealth publishers проверены заново **2026-10-03**. [Forbes terms](https://www.forbes.com/terms/) продолжают запрещать автоматическое извлечение. [Henley terms](https://www.henleyglobal.com/terms-of-use) запрещают robots/scrapers и требуют лицензии для commercial reuse; сама методика 2025 использует liquid wealth без недвижимости и преимущественно work locations. [Altrata terms](https://altrata.com/terms-of-use), помеченные Updated August 2026, запрещают в том числе store/archive/extract без consent; методика Billionaire Census назначает географию по primary business address. Поэтому массовые цифровые таблицы этих издателей не вошли в этот пакет и зеркала не использовались для обхода условий.

Первичный Phoenix report найден на сайте самого издателя: таблица historical millionaire **households** охватывает 50 штатов + DC на конец 2019. Документ помечен Proprietary & Confidential, а current export/republication permission не установлена. Он зарегистрирован как historical candidate; это не текущая таблица millionaire persons и не готовый production dataset. [Первичный historical report](https://www.phoenixmi.com/wp-content/uploads/2020/04/Phoenix-MI_2019-Millionaire-Rankings-by-State_Confidential.pdf).

Основные файлы:

- [Машинные наблюдения JSON](normalized/observations.json) и [CSV индекс](normalized/observations.csv).
- [Source register](source-register.json), [definition decisions](definition-decisions.json).
- [51 строка state coverage CSV](state-coverage.csv) и [JSON с null](state-coverage.json).
- [Сводный current status](current-status.json): последняя успешная версия каждого источника, hashes и история попыток. `latest.json` указывает только на последний запуск collector и может относиться к одному выбранному источнику.
- [Недельный handoff](WEEKLY-HANDOFF.md) и [backlog](backlog.json).
- `runs/*/raw/`: оригинальные response bodies, сжатые gzip для хранения; SHA-256 response body и SHA-256 локального gzip артефакта различаются и явно подписаны в receipts.

GIS source IDs проверены до и после выгрузки. Проверены полнота страниц, уникальность OBJECTIDs и флаги transfer limit. Это подтверждает состав выгрузки; ArcGIS не предоставляет здесь транзакционный snapshot, и изменение атрибутов во время запросов полностью исключить нельзя. Ошибки ранних bounded попыток сохранены, а их partial observations не вошли в reconciled dataset. Отдельные тестовые наборы не добавлялись; обязательные проверки выполнялись при сборе и нормализации.

Production schema/pipeline и чужие файлы не менялись; commit/push из этой сессии не выполнялся.

## Продолжение исследования — 2026-10-04

Добавлены 18 наблюдений в normalized: state/county записи официальной карты Oregon DEQ, отдельно по сырому статусу CAO, плюс датированные подмножества operation evidence. Рабочий JSON содержал 404 строки перед продолжением и теперь содержит 422; число 403 в историческом отчёте описывает первую сессию и её manifest.

| Проверка | Результат | Ограничение |
|---|---:|---|
| Oregon DEQ CAO map, visible sheet `6.25.2026 update` | 421 строка в листе; 32 уникальных DEQ Source # с Facility Type `Data Processing, Hosting, and Related Services` | Карта относится только к объектам, обязанным участвовать в CAO; DEQ явно сообщает, что не все Oregon facilities подпадают под программу |
| County join из координат DEQ на Census TIGERweb Counties 2026-01-01 | Crook 2; Morrow 8; Umatilla 7; Wasco 3; Washington 12 | Это permit-map Source # записи, не физические здания, campus или полный county inventory |
| Сырой CAO status | Complete 17; Not Started 14; In Progress 1 | Статусы программы не означают operational / construction / proposed |
| Operation evidence | PDX-4 / Source # 25-0008 явно назван DEQ работающим; ещё два ID описаны в приказе DEQ от 2025-08-19 на события 2023–24 годов | Только один текущий page-confirmed Source # в этом subset; два других подтверждают прошлый период. Полный Oregon total неизвестен |

Официальная страница DEQ говорит о более чем 40 data centers, которые к 2025 году были permitted **или proposed**, но не публикует полный список; поэтому это не число действующих объектов. Презентация Oregon Department of Energy от 2026-02-27 приводит 123 по данным datacentermap.com и не предоставляет underlying records или rules идентификации. Этот вторичный directory count не принят. Для CAO workbook открытый license/reuse статус не установлен, поэтому записи остаются `research_only`.

Сохраняются null для полных state totals жителей-миллионеров, жителей-миллиардеров и работающих физических data-center объектов. Подробная provenance, county join, ограничения и следующая задача: [результаты Oregon](sessions/2026-10-04/oregon-deq-findings.json), [32 map records](sessions/2026-10-04/oregon-deq-cao-data-center-listings.csv), [operation evidence](sessions/2026-10-04/oregon-deq-operating-evidence.json), [session record](sessions/2026-10-04/session-record.md).

## Продолжение исследования — 2026-10-05

Добавлены **7 наблюдений** в normalized (итого 429; production writes — 0) и отдельный реестр датированных facility/site records. Работали с Alabama и Alaska — следующими открытыми штатами из приоритетной очереди. Все три желаемых полных target totals по-прежнему `null`; эти записи являются source-specific subsets.

| Штат / источник | Новая запись | Ограничение / география |
|---|---|---|
| Alabama Department of Commerce + Google | Commerce говорит, что Google **работает** с data center в North Alabama; Google называет Jackson County. Добавлена одна operator-named site/campus observation, county **01071** по Census TIGERweb. | Это Google location, не building count или state total. |
| City of Huntsville / Meta | Отчёт **2021-12-30**: **2** operating buildings; отдельно 1 третий building с CO и 3 under construction. | County не присвоен без parcel/точки; current status после 2021 не установлен. CO/construction не складывались с operation. |
| City of Auburn / AUBix / Core Scientific | Один West Samford site открылся в **2022**; Core release от 2025 описывает переход оператора, а нынешняя страница перечисляет Auburn 1. | Это один и тот же сайт. Census Geocoder не нашёл точный адрес; county FIPS не присвоен. Текущая operation после перехода не подтверждена dated commissioning evidence. |
| Alaska OIT Enterprise Service Catalog v1.16 | Датирован **2026-07-20**, называет 2 colocation site: Juneau State Office Building DC (**02110**) и GCI South Anchorage DC (**02020**). | Это только текущий OIT service subset, не полный Alaska inventory. GCI site не посчитан дважды по собственной странице оператора. |
| University of Alaska | Butrovich DC: вернулся в service после upgrades (2023); job listing до **2026-09-29** подтверждает 24/7 operations, Fairbanks North Star Borough **02090**. | Один именованный institutional facility; county через TIGERweb locality, не parcel. |
| UAA и Alaska Railroad | UAA говорит “several” центров в Anchorage, без адресов/числа. ARRC назвал 2 existing Anchorage server facilities в 2024 и 1 Fairbanks facility планировал на 2025. | UAA не превратили в число; ARRC оставлен historical/project subset, его Fairbanks plan не считался работающим. |

Google/OIT/UAF текущие страницы поддерживают именованные operation/service subsets; Meta Huntsville и Alaska Railroad сохранены как датированные исторические записи; AUBix — существующий сайт с неразрешённым current-operation status. Наблюдения различают building, named location/campus и provider facility. County GEOIDs взяты из сохранённых TIGERweb ответов; Auburn и Huntsville оставлены без GEOID.

По примеру «зарегистрированного триллионера»: личность и registry не указаны, поэтому точный claim остаётся `unverified`. SEC объясняет Form S-1 как issuer securities-offering filing; Form 3 от **2026-06-11** раскрывает beneficial ownership, а не personal net worth/assets-minus-liabilities или primary residence. Person-count observations не добавлялись.

Источники, checks/HTTP outcomes, definition/population, dates, omissions и hashes: [facility records](sessions/2026-10-05/state-facility-records.json), [wealth-claim review](sessions/2026-10-05/wealth-claim-review.json), [receipts and retained raw source bytes](sessions/2026-10-05/acquisition-receipts.json). Текущие подробности и blockers находятся в [session record](sessions/2026-10-05/session-record.md). Следующие state tasks: Arizona, затем Ohio; ничего из этой работы не устанавливает полные statewide counts.
