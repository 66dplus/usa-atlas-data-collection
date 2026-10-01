# Реальный снимок поисковых трендов США

**Получен официальный Google Trends RSS:** 2026-09-29, 14:38:53 UTC; HTTP 200; 21 405 байт; 10 запросов. Источник: [US Trending Now RSS](https://trends.google.com/trending/rss?geo=US). Исходный XML сохранён без изменений, вместе с HTTP receipt и SHA-256.

Это наблюдение за текущими всплесками интереса. Оно не измеряет весь американский поисковый спрос и не позволяет ранжировать наши темы по месячному объёму.

## Что действительно прислал источник

| Поле | Фактическое значение |
|---|---|
| География запроса | `geo=US` |
| Название RSS channel | `Daily Search Trends` |
| Число items / различных query titles | 10 / 10 |
| `pubDate` в этих items | 2026-09-29 13:10–14:20 UTC |
| Исходные `ht:approx_traffic` | 500+: 3 items; 1000+: 4; 2000+: 2; 5000+: 1 |
| `lastBuildDate` / channel `pubDate` | Источник не передал |
| Границы окна измерения traffic | Источник не передал |

Примеры полученных значений: `america.gov` — `1000+`, `wnba playoffs bracket` — `500+`, `midterm elections` — `1000+`. Значения сохранены в том виде, в котором их передал Google.

Google описывает Trending Now как выборку растущих трендов; traffic представлен интервалами, а один тренд может объединять связанные запросы. [Официальное описание](https://support.google.com/trends/answer/3076011?hl=en) также подтверждает RSS export. Название канала `Daily Search Trends` и default 24-hour window интерфейса не дают основания приписать этому RSS точный суточный период: в самом ответе его границы отсутствуют. `pubDate` не считается границей окна объёма.

## Сопоставление с нашими темами

Прочитаны существующие 20 тем и 81 keyword seed из `research/2026-09-28/demand/`; hashes обоих входов сохранены. Проверены нормализованные точные совпадения с seeds и отдельный консервативный словарь фраз по темам. Результат: **0 точных совпадений, 0 lexical candidates**. Словарь находится в снимке и доступен для review.

Это означает только отсутствие таких совпадений среди этих десяти строк. Нельзя присвоить нашим темам нулевой спрос, место в рейтинге или количество searches/month. Поля `monthly_searches` и `demand_rank` у всех 20 тем остаются `null`. Имена компаний или упоминание события не превращаются автоматически в спрос на наши geographic datasets. Корреляции не вычислялись.

## Попытка сравнить четыре темы за год

В **2026-09-29 14:48:05 UTC** выполнен один публичный unauthenticated запрос Google Trends Explore: `data center`, `electricity rates`, `water shortage`, `overdose`; `geo=US`, `today 12-m`, all categories, web search. Источник вернул **HTTP 429**. Параметры, оригинальный ответ и его SHA-256 сохранены в [manifest](explore-latest.json) и [receipt](explore-attempts/20260929T144805Z/receipts.json).

Данные interest-over-time 0–100 не получены. После 429 запрос не повторялся, авторизация, прокси и обход ограничений не использовались. [try_explore.py](try_explore.py) делает максимум два запроса: публичное описание сравнения и, только при успехе, timeseries с возвращённым самим сервисом query token. В этой попытке выполнен только первый запрос. [Открыть то же сравнение в интерфейсе](https://trends.google.com/trends/explore?geo=US&q=data%20center,electricity%20rates,water%20shortage,overdose&date=today%2012-m).

## Что остаётся получить

| Источник | Что измеряет | Состояние |
|---|---|---|
| Public US RSS | Текущие избранные тренды и traffic buckets | **Снимок реально собран** |
| Google Trends Explore / официальный API | Относительный интерес по заданным ключам и регионам | Public Explore сравнение4тем вернуло HTTP429; сопоставимый export по81seed не получен; [API всё ещё описан как alpha с заявкой на доступ](https://developers.google.com/search/apis/trends) |
| Google Ads historical metrics | Приблизительные monthly searches и среднее за 12 месяцев | Авторизованный запрос не выполнялся; нужен предоставленный API-доступ или официальный экспорт |

[Google Trends API](https://developers.google.com/search/blog/2025/07/trends-api) возвращает search interest, а не абсолютное количество запросов. Для месячных объёмов официальный путь — [GenerateKeywordHistoricalMetrics](https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics), с сохранением US geography, языка и close variants. Нужен авторизованный доступ; публичный RSS не заменяет его. По [актуальной документации Google Ads](https://developers.google.com/google-ads/api/docs/api-policy/developer-token), управление API access перенесено в Google Cloud, прежние developer tokens отменены с 2026-09-09. В этом задании аккаунты не подключались и заявки не подавались.

## Файлы и повторение

[latest.json](latest.json) — manifest. Снимок `snapshots/20260929T143853Z/` содержит:

- [оригинальный XML](snapshots/20260929T143853Z/google-trends-us.xml)
- [CSV](snapshots/20260929T143853Z/trends.normalized.csv) и [JSON](snapshots/20260929T143853Z/trends.normalized.json)
- [HTTP receipt](snapshots/20260929T143853Z/receipts.json)
- [сопоставление 20 тем](snapshots/20260929T143853Z/topic-comparison.json)
- [manifest с hashes](snapshots/20260929T143853Z/manifest.json)

SHA-256 XML: `ef2af1f998e98ae4b6f28aceaaf8054777fc5b1c587db6fd91fcf6d1d2bb5be8`.

[collect_trends_rss.py](collect_trends_rss.py) — stdlib collector: один публичный endpoint, максимум две попытки, timeout 30 секунд, до 2 MB, file lock. Нормализация не скачивает связанные новостные статьи. Для повторного снимка:

```bash
python3 research/2026-09-29/demand-signals/collect_trends_rss.py
```

Расписание не устанавливалось; действующие collectors и DB не изменялись. Отдельные тесты не запускались. RSS даёт наблюдаемый сигнал, но задача измерения устойчивого спроса на выбранные 20 тем остаётся открытой.
