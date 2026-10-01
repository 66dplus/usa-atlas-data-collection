# Новые темы и заполнение существующих: результат на 2026-09-28

Сохранено **120 строк агрегатов** из первичных источников: 53 строки IRS о состояниях от $11.4 млн, 63 строки о зданиях дата-центров Loudoun County по стадиям и территориям, 2 национальные оценки энергопотребления и 2 национальные оценки числа миллионеров/миллиардеров UBS. Это исследовательские CSV, не допущенные в production. `millionaires` и `billionaires` уже присутствуют в исходном каталоге как незаполненные темы; данные компаний и дата-центров — расширение каталога.

**Компании пока трактуются как фирмы с годовой выручкой/receipts ≥$1 млн и ≥$1 млрд.** Это рабочее предположение, ожидающее уточнения пользователя. Стоимость компании/капитализация — отдельная метрика. Пищевые темы не добавлялись.

## Что реально собрано

| Набор | Период | Детализация и охват | Строки | Что означают числа |
|---|---|---|---:|---|
| [IRS wealth](normalized/irs-wealth-2019.csv) | 2019 | 50 штатов + DC + total + other areas | 53 | Оценка взрослых с **net worth ≥$11.4 млн**, их совокупное состояние; Alaska и Rhode Island suppressed |
| [Loudoun data centers](normalized/loudoun-datacenters-2026-03-01.csv) | 2026-03-01 | Один county, 8 местных избирательных округов + county total, 7 стадий/итогов | 63 | Количество **зданий** и площадь; стадии строительства и согласования разделены |
| [LBNL electricity](normalized/lbnl-energy-2024.csv) | 2024 | США | 2 | 192 TWh и 4.7% всей электроэнергии страны; модельная оценка |
| [UBS wealth](normalized/ubs-national-wealth.csv) | конец 2025 / 2025-04-04 | США | 2 | 23,627,000 взрослых долларовых миллионеров / 924 миллиардера; оценки издателя |

53 строки IRS содержат 51 числовую оценку и 2 пропуска. Пустые значения не равны нулю. Таблица содержит 49 числовых строк штатов/DC, общий итог и other areas. Последние две строки нельзя суммировать со штатами. [IRS, Table 6, PDF p.31](https://www.irs.gov/pub/irs-soi/soi-a-inpw-id2402.pdf).

В Loudoun зафиксировано 233 здания built/under construction. Это не число уже работающих дата-центров. Отдельно: 51 здание с одобренным site plan без building permit, 58 в review site plan, 7 в одобренных legislative applications без активного site plan. Их subtotal — 116; общий итог вместе с built/construction — 349. Еще 56 зданий в рассматриваемых legislative applications. Итоги перекрывают компоненты: суммировать все 7 статусов нельзя. PDF составлен 2026-08-28, но описывает состояние на 2026-03-01. [Официальная таблица county](https://www.loudoun.gov/DocumentCenter/View/222160).

Для LBNL использован **2025 Update, опубликованный 2026-06-18**. Название отчета не является годом наблюдения. Учитываются данные за 2024; прогнозы 2025–2030 в CSV отсутствуют. Cryptocurrency mining исключен. Отчет пересматривает прошлые оценки, поэтому нельзя бесшумно соединять его с выпуском 2024. [DOE/LBNL, DOI 10.71468/P1RP4F](https://www.energy.gov/documents/united-states-data-center-energy-usage-report-2025-update).

UBS дает настоящую метрику богатства на национальном уровне: активы, включая жилье и частные пенсионные накопления, минус долги. Число миллионеров в исходной таблице — **23,627 тысяч**, поэтому нормализованное число округлено до тысяч. UBS предупреждает о пересмотрах методологии между выпусками. Оценка 924 миллиардера относится к 2025-04-04; новый отчет 2026 сообщает для США только «более 1000» в тексте, поэтому 924 нельзя показывать как текущий итог 2026. Это негосударственные оценки, а открытая лицензия на исходные массивы не установлена. Сохранены два факта с атрибуцией, без копии отчетов и без персональных записей. [UBS Global Wealth Report](https://www.ubs.com/global/en/wealthmanagement/insights/global-wealth-report.html), [UBS Billionaire Ambitions](https://www.ubs.com/us/en/wealth-management/our-solutions/private-wealth-management/insights/billionaires-ambition-report.html).

## Доступность запрошенных показателей

| Тема | Статус | Максимум, подтвержденный этим ресерчем | Следующий конкретный шаг |
|---|---|---|---|
| Миллионеры по net worth ≥$1m | `collected`, национальная оценка издателя; для малых территорий `source_needed` | Nation (UBS); IRS ≥$11.4m — другая метрика на state | Выбрать допустимый источник/условия регулярного обновления для national; искать лицензируемые county данные отдельно |
| Миллиардеры по net worth ≥$1bn | `collected`, национальный snapshot 2025; для малых территорий `source_needed` | Nation (UBS) | Сохранять дату оценки; не переносить данные владельцев в адресные карты |
| Фирмы с receipts ≥$1m | `blocked` | ABS Company Summary содержит county receipts-size table | Получить AB2300CSA03, проверить фактические labels размеров и загрузить all-demographics total с flags/RSE |
| Фирмы с receipts ≥$1bn | `blocked` | SUSB 2022, national large-receipts workbook | Скачать XLSX, подтвердить границы классов и firms column; только затем вычислять threshold sum |
| Количество дата-центров | `collected`, **только Loudoun County** | County + local election district; GIS возможен для последующего пространственного join | Скачать официальный GIS, определить buildings/campus и operational status, проверить идентификаторы, присоединить Census tract/BG |

Не найденный источник не равен доказательству отсутствия данных. `source_needed` означает, что точный пригодный источник/метод не подтвержден в этом проходе. [Машинные статусы](topic-availability.json) отдельно описывают охват, а [sources.json](sources.json) — географию, период, единицу, знаменатель, идентификаторы, обновления, доступ и ограничения каждого источника.

## Источники для следующего сбора

**IRS.** [Personal Wealth](https://www.irs.gov/statistics/soi-tax-stats-personal-wealth-statistics) использует estate-multiplier estimation; последний подтвержденный год таблиц — 2019. Порог wealth меняется между выпусками и здесь равен $11.4m. [Historic Table 2](https://www.irs.gov/statistics/soi-tax-stats-historic-table-2) предлагает state income за 2023: годовой AGI ≥$1m — полезная самостоятельная метрика, но доход декларации не равен состоянию человека. [County income 2023](https://www.irs.gov/statistics/soi-tax-stats-county-data-2023) доступен отдельно; класс $1m+ для county в этом проходе не подтвержден. Top-coded доходы нельзя разложить на более высокие интервалы. Совместная декларация также не равна одному человеку.

**Census ABS/SUSB.** Подтверждена [метадата AB2300CSA03, 2023](https://api.census.gov/data/2023/abscs/groups/AB2300CSA03.html). Нужны `FIRMPDEMP`, `FIRMPDEMP_F`, `FIRMPDEMP_S`, `FIRMPDEMP_S_F`, `RCPSZFI` и `RCPSZFI_LABEL`. Не переносить коды из другого ABS module: границы могут различаться; некоторые документы с похожими именами описывают `absmcb`, а нужен `abscs`. В flagged cells API может показывать 0 вместо оценки, поэтому flags обязательны. Для национального total использовать опубликованный all-sector/all-demographics итог, а не сумму пересекающихся групп. ABS охватывает employer firms, не весь nonemployer business universe.

[SUSB 2022](https://www.census.gov/data/tables/2022/econ/susb/2022-susb-annual.html) предлагает два national receipts-size XLSX, один с большими классами до $2.5bn+. Ссылки county на той же странице относятся к **employment-size**, а не подтверждают county revenue-size. `firms` и `establishments` — разные единицы. Annual publication SUSB не гарантирует ежегодную доступность receipts-size: проверять конкретный vintage. Скачать и проверить workbook пока не удалось; готового числа миллиардных фирм здесь нет.

**SEC.** [Company Facts и Submissions](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) позволяют строить отдельный слой SEC filers по годовому revenue и business address. Нужны CIK, accession, fiscal interval, reporting unit и политика restatements. Одно revenue concept не покроет все фирмы; extensions, финансовые компании, иностранные эмитенты и фонды требуют явных правил. Business/HQ address не описывает размещение операций. Это неполный слой публичной отчетности; стоимость частной компании и полный реестр фирм он не заменяет. API обновляется с filings, bulk ZIP — nightly.

**Дата-центры.** [Официальная страница Loudoun](https://www.loudoun.gov/DataCenters) ссылается на карту существующих и предлагаемых зданий. [Virginia DEQ permits](https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers) — дополнительный источник для проверки статуса, но один объект может иметь несколько разрешений; разрешение не доказывает эксплуатацию. [CBP](https://www.census.gov/programs-surveys/cbp/about.html), NAICS 518210 — только отраслевой proxy: код включает смежную деятельность и не гарантирует включение внутренних дата-центров иных отраслей. Называть его число establishments количеством физических дата-центров нельзя.

[Data.gov keyword discovery](https://catalog.data.gov/?keyword=data+center) в этом проходе показал DCOI plans федеральных агентств и тематические data repositories. Это каталог для обнаружения источников, не найденный полный реестр коммерческих дата-центров. [SCF](https://www.federalreserve.gov/econres/scfindex.htm) может дать взвешенную национальную оценку семей с заданным wealth, но не малые географии; богатейшие Forbes 400 исключены из sampling, поэтому SCF не подходит для подсчета всех миллиардеров.

## География, обновления и сопоставления

Сохранять `source_release` отдельно от observation period и retrieval date, оригинальные suppression/quality flags и стабильный provider ID. FIPS хранить строками с ведущими нулями. В CSV national использует `geo_type=nation`, `geo_id=US`. IRS total и other areas — специальные provider aggregates. Местным избирательным округам даны явно синтетические ID `LOUDOUN:2026-03-01:*`; это не Census GEOID и не общий production geo contract. Отдельная миграция понадобится, если такие географии будут допущены в БД.

Для будущего слоя дата-центров до tract/BG нужен официальный объект с координатой/геометрией и проверенным ID. Сначала выбрать единицу (здание или campus), дату и статус; затем пространственно соединить с Census boundaries одного vintage. В текущем сборе нет точек, Census tract или block-group наблюдений; downscaling по населению не выполнялся.

Пары для отдельного анализа: дата-центры ↔ цена электроэнергии/utility service territory; дата-центры ↔ водозабор/стресс водосборного бассейна; богатство ↔ жилье/доходы; фирмы с высокой выручкой ↔ занятость/зарплата. У electricity tariff география часто utility, у воды — watershed, а не county. Присоединение требует документированной связи территорий; count alone не измеряет MW или водопотребление. Национальная оценка LBNL не пригодна для county correlation. Корреляции на этих 120 строках не вычислялись.

## Воспроизведение и ограничения получения

```bash
python3 research/2026-09-28/new-topics/normalize.py
```

Скрипт восстанавливает CSV и [collection-manifest.json](collection-manifest.json), проверяет точное покрытие IRS и пропуски, уникальность 63 Loudoun keys, суммы районов и компоненты subtotal. Использует только стандартную библиотеку и локальные файлы. Production schema, catalog и manifest не меняет.

Прямой `urllib` запрос из sandbox завершился `Temporary failure in name resolution`; web tool читает PDF/HTML, но отверг IRS CSV и Census XLSX как неподдерживаемые типы. Конкретные попытки и URL сохранены в [access-attempts.json](raw/access-attempts.json). Поэтому `raw/` содержит **извлеченный текст/ручную транскрипцию числовых фактов**, не исходные bytes PDF/XLSX. SHA-256 в manifest относится именно к сохраненным локальным файлам. Автоматический скачиватель и hashes оригинальных provider files остаются обязательным шагом перед регулярным production ingestion.

Сохранять весь текст публикаций в наблюдениях не требуется: достаточно source/release ID, ссылки в источнике, даты, quality и hash артефакта. Данные и provenance этого исследовательского пакета небольшие; они пригодны для review определения метрик и следующего реального сбора, а не для заявления о полной общенациональной карте.
