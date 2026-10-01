# Аудит покрытия 81 поля — 29 сентября 2026

**Шесть локальных наборов — отдельная региональная очередь, а не весь сбор и не шесть штатов.** Два набора относятся к California, два к Washington DC, один к Loudoun County в Virginia, один к New York: **4 юрисдикции, из них 3 штата и DC**. Всего сохранено 70 443 строки источников. В США 50 штатов; максимальные **52 state-level единицы ACS = 50 штатов + DC + Puerto Rico**.

## Что завершено и что ещё нет

| Область | Подтверждённый результат | Что это не доказывает |
|---|---|---|
| Исходная production БД | 49 206 438 строк, 9 источников по сохранённому SQL fingerprint | Fingerprint не содержит counts по отдельным полям/географиям; наличие провайдера не подтверждает полноту каждого его поля |
| Новый ACS/CDC сбор | Исходные данные для **26 из 74** не-food полей: 23 ACS + 3 CDC | Не все формулы выполнены; CDC tract — отдельная crude variant; admission/UI не завершены |
| Национальный BG-слой | **19 полей** имеют исходные native BG estimates либо эквивалентные counts: 18 основного ACS + poverty B17021 | Это исходные показатели/числители/знаменатели, а не 19 полностью готовых UI-метрик; качество, MOE и формулы сохраняют значение |
| Остальные поля без подтверждённого национального BG | **55 из 74** | Для части источников BG не публикуется; это не означает, что по ним совсем нет данных |
| Дополнительные федеральные файлы | 6 bulk jobs IRS/BEA/EPA/SUSB, source tables сохранены | Число файлов не равно числу тем или штатов; не все строки совместимы с действующим контрактом |
| Локальные файлы | 6 наборов в CA/DC/VA/NY | Не национальное покрытие; локальные кандидаты не подменяют FBI/IRS/ACS определения |

Каталог содержит **81 поле; 7 food-полей исключены; 74 в области задачи**. Новая полная матрица: [coverage.csv](coverage.csv), [coverage.json](coverage.json). У каждого поля отдельно указаны старый провайдер в БД, новый национальный статус, фактические native counts, региональные кандидаты, определение/доступ и состояние admission. Неизвестные per-field counts старой БД оставлены `null`.

Основной ACS/CDC run сохранил **71 514 287** исходных записей, extensions отдельно **1 085 473**, всего **72 599 760**. Эти числа нельзя прибавлять к production rows как новые уникальные наблюдения: есть пересекающиеся версии, переменные и географии; загрузки в production не было.

## Фактическая география

- Обычные ACS-таблицы: 242 297 BG, 85 382 tracts, 3 222 counties, 32 330 places и 52 state-level единицы. Покрытие зависит от таблицы; B19301 имеет 242 069 BG. Counts означают наличие исходной записи, а не обязательно числовое значение без suppression/missing.
- Poverty B17021 даёт 242 297 BG; исходные poverty counts совпали с B17001 на всех 177 208 общих county/tract E/M-парах. Долю ещё нужно вычислять с соответствующей неопределённостью.
- Foreign-born, birthplace, citizenship и entry-period из выбранных B050xx заканчиваются на tract: 85 382 для B05002, 84 401 для B05001/B05005/B05006. Альтернатива B05012 тоже не даёт BG. Ограничение подтверждено official table list и фактическими payloads.
- CDC: 83 522 tracts, три health measures, 2023 data year, crude prevalence и CI. Это не county age-adjusted серия.
- IRS county 2023: 3 143 counties и 51 итог штата/DC. County `000` — итог штата. ZIP не ZCTA.
- BEA MARPP: 387 MSA плюс US и US nonmetropolitan total, 2008–2024. Filter обязан включать **TableName=MARPP и LineCode=1**: MAIRPD с тем же LineCode — другой индекс.
- EPA: измерения monitor/site, а не сплошной county/tract/BG слой. Source содержит также Mexico с кодом 80; 53 source state codes нельзя называть 53 штатами.

У шести полей есть дополнительные федеральные таблицы: RPP, AGI, capital gains, dividends, PM2.5, ozone. Это отдельно от 26 ACS/CDC-полей. Для AGI присутствует `A00100`, но отсутствует контрактный `N00100`; `N1` не подменён автоматически. Для capital gains/dividends нужные названия колонок присутствуют, однако release/geography изменены с ZIP 2022 на county/state 2023. SUSB annual receipts ≥$1m/≥$1bn — новые company topics вне исходных 81 полей, не стоимость компании и не millionaire wealth.

## Остаток работы по 74 полям

Помимо 26 ACS/CDC и шести полей с федеральными source tables:

- **11 полей** связаны с уже присутствующими в старой БД провайдерами, но новый сбор по ним не выполнен: unemployment, восемь FBI crime/trend fields, electricity, fitness.
- **19 полей** ожидают источника/доступа/адаптера: salary, 12 mortality topics, 6 homelessness topics.
- **7 полей** требуют точного определения: employment growth, homicide, high-income returns, taxes, gasoline, health insurance cost, parks.
- **3 поля** требуют дальнейшего источника/определения: life expectancy, consumer debt, student debt.
- **2 wealth-поля** имеют только национальный контекст UBS; точный малый географический уровень и условия регулярного использования не подтверждены. IRS wealth ≥$11.4m не заменяет millionaires ≥$1m.

Таким образом, общая ревизия затронула весь каталог, но фактический новый сбор ещё не завершён для всех 74 полей. Региональные DC crime, NY tax и CA water не повышают национальную готовность по одному совпадению темы.

## Почему gap-intake показывает 56 вместо 55

`collect_local.py:439` читает `extension_variants[].available_native_levels`, а producer `snapshot_live.py` первоначально сохранял уровни альтернативы только в `extension_variants[].geography_counts`. Поэтому B17021 poverty с реальными BG ошибочно оставался в очереди пробелов. Это несовпадение схемы данных, а не отсутствие скачанных poverty BG.

Исправление выполняется на стороне producer: root добавляет `available_native_levels` к alternatives в snapshot. Работающий collector, его config и watchdog pins не меняются. Текущее наличие producer fix фиксируется как `producer_schema_fixed` в JSON; следующему штатному циклу intake достаточно прочитать обновлённый snapshot, чтобы получить 55 вместо 56. Формулы и admission это не выполняет.

## Источники и воспроизводимость

Аудит читает существующие contracts, live coverage, manifests и `/srv/usa-atlas/maintenance/20260928-compact/source-fingerprint.json`. В [coverage.json](coverage.json) сохранены paths/SHA-256 прочитанных evidence-файлов. Source tables IRS/BEA/EPA дополнительно прочитаны для подсчётов и соответствия колонок. Это аудит существующих материалов, а не повторная проверка всех больших payload hashes.

```bash
python3 research/2026-09-29/coverage-audit/build_audit.py
```

Этим audit-агентом изменены только файлы нового audit-каталога. SQL-запросы/записи, внешние загрузки, тесты и изменения работающего collector не выполнялись. Отдельное изменение producer выполняет root.
