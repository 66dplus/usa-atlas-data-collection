# Дата-центры: Prince William County, Virginia

**Реально скачано 2026-09-29, 14:11:03–14:11:08 UTC:** полный снимок 248 записей зданий из официального слоя округа. Это новое локальное покрытие, отдельно от ранее собранного Loudoun County.

| Исходный BuildingStatus | Зданий |
|---|---:|
| Completed | 57 |
| Under Construction | 31 |
| Pending | 68 |
| Planned | 92 |
| **Всего** | **248** |

## Что означает число

Единица — **запись здания**, а не компания, кампус или отдельный оператор. `Completed` сохранён как статус источника и сам по себе не доказывает работу дата-центра. Запланированные здания не прибавляются к числу работающих объектов. Слой проектов `/MapServer/10` в эту выгрузку не включён.

Источник — [Data Center Buildings, layer 9](https://gisweb.pwcva.gov/arcgis/rest/services/Planning/Build_Out_Analysis/MapServer/9), опубликованный Prince William County. [Planning Office](https://www.pwcva.gov/department/planning-office/build-out-analysis/) подтверждает официальный GIS-портал и описание зданий/кампусов на разных стадиях. Каталог штата предоставил [ссылку на dataset](https://data.virginia.gov/dataset/data-center-buildings), после чего проверен прямой county service.

География — **248 исходных точек EPSG:4326**, охват по описанию источника — Prince William County, Virginia. Census tract/BG не присвоены, spatial join не выполнен. Это не покрытие всех дата-центров Virginia или США. Диапазон координат выгрузки: longitude −77.654160…−77.316219, latitude 38.587844…38.852876.

## Проверки при реальном сборе

- `source_count_before = source_count_after = 248`.
- 248 уникальных OBJECTID и 248 уникальных GlobalID; состав source IDs совпал до и после выгрузки.
- Три страницы по спискам OBJECTID, размер до 100; ни пропусков, ни дубликатов, ни `exceededTransferLimit`.
- Восемь успешных HTTP-запросов. Для каждого сохранены URL, время, исходный ответ и SHA-256.
- Поля BuildingStatus и PermitStatus сохранены без переименования значений; домены находятся в manifest.
- Максимальная LastEditDate в полученных строках: 2026-09-25 15:39:14 UTC.

Проверка количества и ID подтверждает состав выгрузки; ArcGIS не предоставляет здесь транзакционный снимок. Изменение атрибутов во время нескольких запросов полностью исключить нельзя.

Первый запуск `runs/20260929T140908Z` получил metadata, затем timeout count-запроса. Ошибка и receipt сохранены. После добавления ограниченного повтора сетевых ошибок второй запуск `runs/20260929T141103Z` завершён успешно. Проверки количества и ID не ослаблялись. Отдельные тесты не запускались.

## Файлы и обновление

[latest.json](latest.json) содержит актуальный manifest, количества, статусы, ссылки, hash collector и hash каждого результата. Успешный снимок:

- [manifest](runs/20260929T141103Z/manifest.json)
- [нормализованные записи](runs/20260929T141103Z/buildings.normalized.json)
- [GeoJSON](runs/20260929T141103Z/buildings.geojson)
- [HTTP receipts](runs/20260929T141103Z/receipts.json)
- `runs/20260929T141103Z/raw/` — исходные JSON-ответы в gzip.

[collect_pwc.py](collect_pwc.py) читает только public-facility IDs, статусы, даты, площади и геометрию. Имена, адреса, авторы редактирования не запрашиваются. Для регулярного сравнения используется GlobalID; OBJECTID хранится как идентификатор конкретного service. Максимум 20 000 записей, 100 ID на страницу, timeout 60 секунд и максимум две попытки для временных сетевых ошибок и 429/5xx. Lock предотвращает одновременные запуски.

```bash
python3 -u research/2026-09-29/data-center-expansion/collect_pwc.py
cat research/2026-09-29/data-center-expansion/latest.json
```

Официальная страница описывает квартальные и событийные обновления. Снимки сохраняются по времени получения, не заменяя историю. Данные остаются research artifact: production admission и проверка условий повторной публикации ещё не выполнены.

## Установленное расписание

`usa-atlas-pwc-refresh.service` и `usa-atlas-pwc-refresh.timer` включены на сервере. Обновление — каждое воскресенье в 03:45 UTC; ближайший запуск после этого снимка — 2026-10-04. [Service](../../../ops/usa-atlas-pwc-refresh.service) и [timer](../../../ops/usa-atlas-pwc-refresh.timer) сохранены в репозитории. Code pins, проверка свободного места и состояние последней выгрузки контролируются watchdog.

```bash
systemctl status usa-atlas-pwc-refresh.timer
journalctl -u usa-atlas-pwc-refresh.service
```
