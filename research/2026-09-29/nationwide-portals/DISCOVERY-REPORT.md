# Выполненный поиск по 52 юрисдикциям

Финальный проход: **2026-09-29, 14:14:03–14:14:59 UTC**. Все 50 штатов, DC и PR получили фактическую попытку поиска по пяти темам: data center, electricity, water, overdose, crime.

| Что выполнено | Результат |
|---|---:|
| Юрисдикций обработано | **52** |
| Каталоги с серверным поиском | 36: 19 ArcGIS Hub, 14 Socrata, 3 CKAN |
| ArcGIS REST directory: фильтрация полученного списка | 8 |
| HTML: фильтрация ссылок полученной страницы | 8 |
| Успешных серверных поисковых страниц | **180** |
| Фильтров полученных directory/HTML списков | 80 |
| Тематических результатов: 52 × 5 | 260 |
| Неопределённых адаптеров / заблокированных заданий / ошибок поискового запроса | **0 / 0 / 0** |
| Полученных совпадений, включая повторы | 953 |
| Различных записей каталога после дедупликации | **931** |
| Новых таблиц наблюдений, скачанных самим discovery | **0** |

**931 — записи каталогов для review.** Среди них есть карты, dashboards, отчёты, нерелевантные совпадения и разные представления одних данных. Это не 931 готовая метрика и не подтверждение покрытия block group.

Сделано 268 HTTP-попыток; 17 ответов/попыток на стадии проверки альтернативных адаптеров завершились ошибкой и сохранены. Итоговый выбранный способ обработки есть у всех 52 юрисдикций. HTML-only остаются IA, MA, MT, NM, PR, UT, WV, WY; для них нужен отдельный адаптер, чтобы искать за пределами уже полученной страницы. Ведомственный directory также не означает полноту тем по всему штату.

## Проверка области ArcGIS

У всех 19 Hub-каталогов скачана конфигурация с конкретными item group filters. Она сохранена в provider artifacts и [discovery-report.json](discovery-report.json). При этом 436 совпадений ArcGIS остаются `needs_review_possible_global_index`: для автоматического допуска каждого источника ещё нужны проверка издателя, членства в области каталога и фактической географии. По глобальным ArcGIS IDs найдены 424 различные записи; одинаковых IDs, возвращённых каталогами разных юрисдикций в этом ограниченном проходе, не было. Отсутствие повторов само по себе не доказывает географическую полноту.

## Конкретный результат отбора

[reviewed-shortlist.json](reviewed-shortlist.json) содержит первичные доказательства издателя и прямые resources для пяти кандидатов:

| Источник | Доступная единица / география | Текущее состояние |
|---|---|---|
| Prince William County Data Center Buildings | BuildingStatus и исходная точка здания | **Отдельным collector скачаны все 248 записи** |
| Prince William County Data Center Projects | Полигоны проектов разных стадий | Metadata, не смешаны со зданиями |
| Virginia Department of Health overdose deaths | Число смертей по месту жительства city/county, год и drug class | CSV resource найден, observations ещё не скачаны |
| California DWR Water Balance | DAUCO, Planning Area, Hydrologic Region, statewide; water years | CSV/ZIP resources найдены, observations ещё не скачаны |
| New York DEC water withdrawals | Facility, town, county; крупные водозаборы | Socrata API найден, observations ещё не скачаны |

Фактический новый data-center dataset сохранён отдельно: [248 зданий Prince William County](../data-center-expansion/README.md). Статусы: Completed 57, Under Construction 31, Pending 68, Planned 92. Это здания, включая незавершённые; не число работающих кампусов. Исходные точки не превращались в Census BG.

Virginia [первичная страница VDH](https://www.vdh.virginia.gov/drug-overdose-data/overdose-deaths/) подтверждает residence geography, квартальные обновления и неполноту текущего года. Для CA [документ DWR](https://water.ca.gov/-/media/DWR-Website/Web-Pages/Programs/California-Water-Plan/Docs/Update2023/Supporting-Documents/Water-Portfolios-and-Balances.pdf) подтверждает метод водного баланса; текущий catalog metadata указывает WY 2002–2023. NY [официальный перечень DEC](https://dec.ny.gov/sites/default/files/2024-01/opendatacatalog.pdf) подтверждает ежегодный dataset; ограничение — объекты с большой мощностью водозабора, а не все источники водоснабжения.

## Работа по расписанию

Установлены `usa-atlas-nationwide-discovery.service` и `.timer`; исходники units находятся в [ops](../../../ops/usa-atlas-nationwide-discovery.service). Сервис запускает следующий batch через шесть часов после завершения предыдущего; тема повторяется не чаще раза в сутки. Курсор после исправляющих запусков остался `5`, следующая тема — `accidental deaths`.

Текущая очередь: **55 пробелов native BG source input**, 33 группы, 1 716 jurisdiction-topic jobs. Дополнительная стартовая тема `water` даёт 34 группы ротации. Остальные темы ещё не объявляются выполненными: фактические batch фиксируются в manifests. Семь food-полей исключены.

Один запрос сейчас читает только первую страницу, до 10 результатов. `next_offset` сохранён, автоматическое продолжение следующих страниц ещё не реализовано. Повторный daily scan не означает исчерпывающий поиск каталога.

```bash
systemctl status usa-atlas-nationwide-discovery.timer
journalctl -u usa-atlas-nationwide-discovery.service
cat research/2026-09-29/nationwide-portals/runtime/schedule-state.json
```

## Воспроизводимость и исправления

[discovery-latest.json](discovery-latest.json) указывает на последний immutable run. [discovery-report.json](discovery-report.json) содержит сводку и историю всех четырёх проходов; [candidate-index.json](candidate-index.json) — дедуплицированные метаданные без утверждения о допуске. Исходные ответы, URLs, timestamps и SHA-256 находятся в `discovery/<UTC>/raw/` на сервере, raw/runtime исключены из git.

Первый запуск выявил one-based `startindex` ArcGIS. После исправления реальные запросы заработали. Затем найдены официальные альтернативы каталогов IN/NE/OH и добавлен ограниченный повтор временных сетевых ошибок. Последний полный проход завершился без ошибок поисковых запросов. Старые неуспешные receipts сохранены; отдельные тесты не запускались.

Discovery не меняет production DB. Источник допускается к автоматической загрузке только после проверки schema, единицы, release, suppression, лицензии и географии.
