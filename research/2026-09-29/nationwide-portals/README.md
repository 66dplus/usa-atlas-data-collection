# Каталоги 50 штатов, DC и Пуэрто-Рико

Проверка первичных сайтов: **2026-09-29**. Реестр содержит **52 юрисдикции: 50 штатов + DC + PR**.

**Выполнен реальный поиск во всех 52 юрисдикциях:** 180 серверных страниц и 80 фильтров полученных каталогов, 931 различная запись для review; 0 нерешённых адаптеров и 0 ошибок поисковых запросов в последнем проходе. [Фактический отчёт](DISCOVERY-REPORT.md). Отдельно собраны [248 зданий дата-центров Prince William County](../data-center-expansion/README.md).

## Инвентаризация каталогов

| Этап | Количество |
|---|---:|
| Юрисдикций в реестре | 52 |
| `verified_catalog`: просмотрен официальный каталог, перечень datasets или agency REST directory | 50 |
| `official_page_only`: первоначальная браузерная проверка страницы была ограничена | 2 |
| `unresolved`: официальная точка входа не найдена | 0 |
| Новых датасетов скачано в этой фазе | **0** |
| Новых коллекторов наблюдений подключено этим пакетом | **0** |
| Ранее собранных локальных datasets | 6 |

`verified_catalog` подтверждает существование официального каталога. Это не подтверждение работающего API-контракта, наличия конкретной метрики, block-group детализации или полного покрытия штата. Для 8 каталогов непосредственно виден ArcGIS REST directory. Реестр сохраняет первоначальную браузерную проверку; результаты последующих реальных HTTP-проб и поиска записываются отдельно в `discovery/` и не подменяют её. `search_endpoint=null` в реестре означает, что на стадии инвентаризации API не был установлен.

Две записи `official_page_only` в первоначальном браузерном реестре: **Oklahoma и Virginia**. Последующие прямые HTTP-запросы подтвердили рабочие CKAN API обоих каталогов. Для Indiana, Nebraska и Ohio найдены и проверены официальные альтернативы: Indianamap, NebraskaMap и Ohio GIS Hosted directory; доказательства сохранены в `registry-recovery/`. Статус браузерной страницы и результат сетевого адаптера учитываются отдельно.

[registry.json](registry.json) — основной реестр с evidence links, датой, платформой, endpoint status и оговорками. [coverage.csv](coverage.csv) — компактная таблица. [summary.json](summary.json) — сводка построения плана. Её `unverified_api_contracts`, `executed_queue_jobs` и `plan_only` относятся к первоначальным placeholder-статусам плановых заданий. Фактические исполнения, работающие адаптеры и ошибки следует читать из [discovery-report.json](discovery-report.json), `discovery-latest.json` и runtime checkpoint; плановый summary не является operational status.

## Почему в реестре есть ведомственные каталоги

Единого statewide портала может не быть, а старые ссылки меняются. Найдены официальные замены: Alaska Geoportal, Arkansas GIS Hub, Idaho Open Data Hub, Maine GeoLibrary, North Dakota GIS Hub, Tennessee geodata, Utah SGID. Для Alabama/Florida/Louisiana/Nevada/South Dakota использованы доступные ведомственные каталоги. Их тематический охват ограничен; например, roads directory не закрывает тему доходов или смертности. Для таких пробелов нужен следующий поиск по ведомствам, округам и городам внутри этой юрисдикции.

Официальность внешнего ArcGIS/университетского домена подтверждается ссылкой государственной организации: [Idaho](https://gis.idaho.gov/), [Maine](https://www.maine.gov/geolib/), [North Dakota](https://www.gis.nd.gov/data), [South Carolina](https://www.dnr.sc.gov/gis.html), [Wisconsin](https://dnr.wisconsin.gov/maps/GetGISData), [New Mexico](https://www.tax.newmexico.gov/businesses/geographic-information-system-gis/data-download/). Для PR проверен [каталог Instituto de Estadísticas](https://www.estadisticas.pr.gov/busqueda); он включает и datasets, и отчёты, которые нельзя автоматически считать машиночитаемыми данными.

## Очередь поиска по пробелам

[build_queue.py](build_queue.py) читает текущий `research/2026-09-28/geography/live-coverage.json`, field contract и существующие query seeds, записывает SHA-256 входов. На текущем снимке: **55 полей без доступного native BG входа**, **33 группы запросов**, **1 716 плановых заданий для всех 52 юрисдикций**. Доступная география — объединение основной таблицы и уже собранных extension variants. Так B17021 учитывается как доступный BG-вход для poverty; допуск формулы и данных в production проверяется отдельно. Наличие альтернативного входа само по себе не разрешает замену определения метрики.

[gap-fields.json](gap-fields.json) объясняет каждый пробел. [search-queue.json](search-queue.json) содержит jurisdiction/FIPS, поле, keyword, каталог, желаемую географию, cursor, highwater, hash и статус. Новые темы включены отдельными seeds: data centers, company revenue, net worth, groundwater, electricity. Семь food-полей исключены: `08.01/02/03/06` и `09.01/02/03`.

В `search-queue.json` хранятся плановые задания: `execution_state=not_run`, `automatic_collection_allowed=false`. Это вход для выбора тем; фактические попытки и кандидаты имеют отдельные manifests в `discovery/`. Скрипт `scheduled_discovery.py` выбирает следующие пять групп, а `discover.py` проверяет адаптеры и выполняет их для всех 52 юрисдикций. Текущий collector шести локальных datasets не изменяется этим пакетом.

Первоначальный план следующего этапа в [queue-policy.json](queue-policy.json) не является конфигурацией выполняемого runner. В нём описана будущая более глубокая пагинация:

- Поочерёдно все 52 юрисдикции; до 52 catalog requests за цикл, максимум 2 на провайдера.
- Цикл раз в 6 часов; одинаковый запрос не чаще раза в сутки.
- До 3 HTTP-попыток, timeout 30 секунд, backoff 2/8 секунд и соблюдение `Retry-After`.
- Страница до 20 кандидатов, максимум 5 страниц/100 кандидатов; курсор и незавершённость выдачи сохраняются.
- CKAN: `rows/start`; Socrata: `limit/offset` с проверкой domain; ArcGIS: `start/nextStart` с подтверждённым official org/group. Agency HTML требует отдельного адаптера.
- Найденный кандидат остаётся `needs_review`, пока не проверены единица, release, privacy, лицензия, native geography и boundary vintage. Только затем возможен отдельный allowlist сбора.

Перегенерировать план из обновлённой сводки можно командой:

```bash
python3 research/2026-09-29/nationwide-portals/build_queue.py
```

Она не обращается к сети, не запускает сервисы и не меняет live-конфигурацию.

## Выполняемый поиск и расписание

[discover.py](discover.py) скачивает **метаданные каталогов**, а не таблицы наблюдений. [scheduled_discovery.py](scheduled_discovery.py) обновляет очередь пробелов и выбирает пять тем за цикл. Первый набор — `data center`, `electricity`, `water`, `overdose`, `crime`; затем курсор проходит остальные темы. На текущем снимке это 33 группы очереди и дополнительная стартовая тема `water`, всего 34. Все 52 юрисдикции проходят каждый выбранный набор.

Фактические ограничения runner:

- Четыре параллельных запроса, максимум 600 HTTP-попыток за запуск, timeout 25 секунд, ответ до 5 MB.
- Одна страница до 10 кандидатов на тему и каталог. `next_offset` сохраняется, но продолжение со следующей страницы ещё не реализовано; ежедневный проход не обещает полный каталог.
- Максимум две попытки для временных сетевых ошибок, разрыва соединения и 429/500/502/503/504. `Retry-After` учитывается до 60 секунд; более длинный интервал откладывает запрос до следующего цикла.
- CKAN, Socrata и ArcGIS Hub проверяются фактическим JSON-ответом. Для Socrata проверяется domain каждого результата.
- Для REST directory и HTML выполняется фильтр полученного списка. В manifest это `catalog_listing_filter_jobs`; они не прибавляются к числу серверных поисковых запросов.
- ArcGIS Hub использует официальный [OGC API Records](https://developers.arcgis.com/hub/services/search/). Сам URL на домене штата не доказывает ограничение индекса этой территорией: результаты получают `needs_review_possible_global_index`, пока не проверена конфигурация org/group.
- Любой кандидат остаётся `needs_review`, `publisher_verified=false`, `native_geography=null`. Количество кандидатов не означает количество подключённых данных.

Планировщик хранит cursor, выбранные темы, входной hash и даты успешных поисков в `runtime/schedule-state.json`. Регулярный цикл — 6 часов; повтор темы — не раньше 24 часов. Курсор продвигается только после свежего manifest именно текущего запуска с совпадающими темами, hash runner и 52 юрисдикциями. Незавершённый batch сохраняет слот для повторения. Ошибка завершает процесс ненулевым кодом; первые две ошибки допускают повтор через 15 минут, следующие — через 6 часов. Timeout дочернего процесса — час с принудительным завершением и ожиданием его остановки. Два file locks предотвращают параллельные экземпляры.

```bash
python3 -u research/2026-09-29/nationwide-portals/scheduled_discovery.py
cat research/2026-09-29/nationwide-portals/runtime/schedule-state.json
cat research/2026-09-29/nationwide-portals/discovery-latest.json
```

Неизменённые HTTP-ответы, timestamps, URLs и SHA-256 находятся в `discovery/<UTC>/raw/`; объёмные raw и runtime исключены из git. Короткие manifests, provider outcomes и candidates предназначены для review. Нулевой результат означает только отсутствие совпадений в выполненном ограниченном поиске. Ошибки, неподтверждённые адаптеры и ограничение области каталога сохраняются явно.

## Географические и смысловые ограничения

52 записи реестра не означают одинаковый состав территорий во всех национальных источниках. В актуальной сводке, например, B05002 содержит 52 state-level geography, а альтернативный B05012 — 51. Покрытие PR и county equivalents проверяется по каждой таблице, release и geography IDs. Отсутствие BG в общей сводке не доказывает отсутствие отдельного местного источника.

Для этого пакета `verified_native_geography` оставлено пустым: каталог сам по себе не доказывает tract/BG. Point records требуют реального spatial join с известной версией границ. AGI не равен wealth; revenue не равна valuation; establishments не равны firms; NAICS 518210 не охватывает автоматически все дата-центры. Person-level имена и точные частные адреса не входят в план сбора.

## Полный инвентарь

| FIPS | Юрисдикция | Статус | Каталог / первичная страница |
|---|---|---|---|
| 01 | Alabama | verified_catalog | [AL](https://aldotgis.dot.state.al.us/pubgis2/rest/services/Roads) |
| 02 | Alaska | verified_catalog | [AK](https://akgeoportal.alaska.gov/) |
| 04 | Arizona | verified_catalog | [AZ](https://azgeo.az.gov/arcgis/rest/services) |
| 05 | Arkansas | verified_catalog | [AR](https://geodata.gis.arkansas.gov/) |
| 06 | California | verified_catalog | [CA](https://data.ca.gov/) |
| 08 | Colorado | verified_catalog | [CO](https://data.colorado.gov/) |
| 09 | Connecticut | verified_catalog | [CT](https://data.ct.gov/) |
| 10 | Delaware | verified_catalog | [DE](https://data.delaware.gov/) |
| 11 | District of Columbia | verified_catalog | [DC](https://opendata.dc.gov/) |
| 12 | Florida | verified_catalog | [FL](https://ags.dep.state.fl.us/arcgis/rest/services/OpenData) |
| 13 | Georgia | verified_catalog | [GA](https://portal.gio.georgia.gov/server/rest/services/Hosted) |
| 15 | Hawaii | verified_catalog | [HI](https://geoportal.hawaii.gov/) |
| 16 | Idaho | verified_catalog | [ID](https://gis-idaho.hub.arcgis.com/) |
| 17 | Illinois | verified_catalog | [IL](https://data.illinois.gov/) |
| 18 | Indiana | verified_catalog | [IN](https://www.indianamap.org/) |
| 19 | Iowa | verified_catalog | [IA](https://data.iowa.gov/) |
| 20 | Kansas | verified_catalog | [KS](https://hub.kansasgis.org/) |
| 21 | Kentucky | verified_catalog | [KY](https://opengisdata.ky.gov/) |
| 22 | Louisiana | verified_catalog | [LA](https://maps.dotd.la.gov/topo/rest/services/OpenData) |
| 23 | Maine | verified_catalog | [ME](https://mainegeolibrary-maine.hub.arcgis.com/) |
| 24 | Maryland | verified_catalog | [MD](https://opendata.maryland.gov/) |
| 25 | Massachusetts | verified_catalog | [MA](https://www.mass.gov/get-massgis-geospatial-data) |
| 26 | Michigan | verified_catalog | [MI](https://data.michigan.gov/) |
| 27 | Minnesota | verified_catalog | [MN](https://gis.data.mn.gov/) |
| 28 | Mississippi | verified_catalog | [MS](https://opendata.gis.ms.gov/) |
| 29 | Missouri | verified_catalog | [MO](https://data.mo.gov/) |
| 30 | Montana | verified_catalog | [MT](https://data.mt.gov/) |
| 31 | Nebraska | verified_catalog | [NE](https://www.nebraskamap.gov/) |
| 32 | Nevada | verified_catalog | [NV](https://gis.dot.nv.gov/rhgis/rest/services/GeoHub) |
| 33 | New Hampshire | verified_catalog | [NH](https://www.nhgeodata.unh.edu/) |
| 34 | New Jersey | verified_catalog | [NJ](https://data.nj.gov/) |
| 35 | New Mexico | verified_catalog | [NM](https://rgis.unm.edu/rgis6/?simple=True) |
| 36 | New York | verified_catalog | [NY](https://data.ny.gov/) |
| 37 | North Carolina | verified_catalog | [NC](https://www.nconemap.gov/) |
| 38 | North Dakota | verified_catalog | [ND](https://gishubdata-ndgov.hub.arcgis.com/) |
| 39 | Ohio | verified_catalog | [OH](https://maps.ohio.gov/arcgis/rest/services/Hosted) |
| 40 | Oklahoma | official_page_only | [OK](https://data.ok.gov/) |
| 41 | Oregon | verified_catalog | [OR](https://data.oregon.gov/) |
| 42 | Pennsylvania | verified_catalog | [PA](https://data.pa.gov/) |
| 44 | Rhode Island | verified_catalog | [RI](https://www.rigis.org/) |
| 45 | South Carolina | verified_catalog | [SC](https://data-scdnr.opendata.arcgis.com/) |
| 46 | South Dakota | verified_catalog | [SD](https://sdgis.sd.gov/arcgis1/rest/services/OpenData) |
| 47 | Tennessee | verified_catalog | [TN](https://geodata.tn.gov/) |
| 48 | Texas | verified_catalog | [TX](https://data.texas.gov/) |
| 49 | Utah | verified_catalog | [UT](https://gis.utah.gov/products/sgid/sgid-index/) |
| 50 | Vermont | verified_catalog | [VT](https://data.vermont.gov/) |
| 51 | Virginia | official_page_only | [VA](https://data.virginia.gov/) |
| 53 | Washington | verified_catalog | [WA](https://data.wa.gov/) |
| 54 | West Virginia | verified_catalog | [WV](https://wvgis.wvu.edu/data/data.php) |
| 55 | Wisconsin | verified_catalog | [WI](https://data-wi-dnr.opendata.arcgis.com/) |
| 56 | Wyoming | verified_catalog | [WY](https://portal.wsgs.wyo.gov/) |
| 72 | Puerto Rico | verified_catalog | [PR](https://www.estadisticas.pr.gov/busqueda) |
