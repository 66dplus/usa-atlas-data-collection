# Региональное расширение: Texas, Colorado, Washington

**29 сентября 2026: три новых официальных набора реально собраны, 3/3 complete.** Сохранено **4 889 нормализованных строк**, raw/normalized gzip текущего датированного запуска занимают **147 169 байт**. Это три новые региональные темы/источника, не дополнительные 4 889 готовых production observations. В БД они не загружены.

Основной актуальный запуск: [latest.json](latest.json) → [runs/2026-09-29/collection-summary.json](runs/2026-09-29/collection-summary.json). [quality-summary.json](quality-summary.json) — дополнительная проверка именно этого датированного снимка: все raw/normalized SHA-256 сверены. Первоначальные файлы в корне каталога сохраняют первый успешный сбор; это те же три набора, их не следует считать ещё тремя datasets.

| Официальный источник | Сохранено | География и дата | Значение и ограничения |
|---|---:|---|---|
| TX TWDB reservoir conditions | 122 строки | 122 reservoir gauge points, 2026-09-29 | Storage/capacity в acre-feet, elevation в ft, percent full. Texas water network включает Elephant Butte в New Mexico и трансграничные водохранилища; точки не являются county/BG или территориями водоснабжения |
| CO DWR well applications/permits | 1 239 агрегатов | County × текущий статус; источник обновлён 2026-09-29 | Сумма групп **651 771 source records**. **64 county names**, плюс UNKNOWN — 23 записи и null county — 2 399. Разрешения/заявки не равны работающим скважинам или запасам воды |
| WA DOL electric vehicle population | 3 528 агрегатов | **1 770 census tracts 2020**, все 39 county labels; регистрации на **2026-08-31** | **298 916** WA registrations: 241 125 BEV + 57 791 PHEV. Это число автомобилей, не расход электроэнергии, станции зарядки или ёмкость сети |

Вместе с прежними шестью региональными наборами это **9 разных наборов** в CA/DC/VA/NY/TX/CO/WA — **7 юрисдикций**, причём VA ранее был представлен только Loudoun County. Это расширение, а не охват всех 50 штатов. BG не создавались: новый наиболее детальный Census-уровень здесь — WA tract. Новые water/EV темы не закрывают автоматически пробелы исходного каталога из 81 поля.

## Первичные источники

- Texas: [официальная страница TWDB](https://www.twdb.texas.gov/surfacewater/conditions/index.asp), [документация выгрузок](https://waterdatafortexas.org/reservoirs/download), [текущий JSON](https://waterdatafortexas.org/reservoirs/recent-conditions.json). Сохранены полный bounded JSON, публикационные даты, source tags и gauge coordinates. Независимое live количество reservoirs не проверено; 122 — число уникальных IDs в полученном ответе.
- Colorado: [официальный DWR data portal](https://dwr.colorado.gov/services/data-information), [DWR Well Application Permit](https://data.colorado.gov/Water/DWR-Well-Application-Permit/wumm-7awb). Проверены название и owner `Division of Water Resources`. Сервера запрошены только county/status counts; контакты, домашние адреса, permit IDs и индивидуальные точки не выгружались.
- Washington: [Electric Vehicle Population Data](https://data.wa.gov/Transportation/Electric-Vehicle-Population-Data/f6w7-q2d2). Проверены owner `Department of Licensing`, metadata description поля 2020 GEOID и период. Фильтр `state='WA'` исключает out-of-state registrations. API вернул только tract/county/type counts; VIN, vehicle ID и точки автомобилей не загружены.

## Проверки и качество

Для CO/WA сумма агрегатов совпала с `count(*)` до и после выгрузки; `rowsUpdatedAt` не изменился. Проверены уникальность групп, integer counts, отсутствие усечения по лимиту и формат WA GEOID: 11 цифр с префиксом 53. Это контроль согласованности, а не транзакционная гарантия провайдера.

В CO `UNKNOWN` сохранён как буквальный source label; это **не 65-й county**. Нормализованное `geography_status=observed` у этой строки означает наличие исходной метки; отдельный quality summary отмечает её как неизвестную географию. Null county также сохранены. FIPS по названиям не угадывались, vintage county boundaries не подтверждён.

В TX два reservoir records не имеют conservation storage/capacity, volume и percent full; у девяти отсутствует area. Null не превращены в 0. Gauge point — точка измерения, а flood-control flag нельзя использовать как доказательство water-supply availability. Storage разных Texas/shared reservoirs нельзя автоматически суммировать без проверки прав и методологии.

В WA отсутствующих tract IDs в полученных агрегатах нет; это не означает, что каждый tract имеет EV. Отсутствующие группы не заполнены нулями. Электромобили могут использоваться как отдельный показатель потенциального спроса при исследовании сети, но не как измерение потребления или мощности.

Лицензия WA — ODbL, сохранена в metadata; требования attribution/share-alike нужно учесть перед product admission. Для CO metadata не содержит отдельной license declaration; публичная доступность не выдаётся за согласование всех условий повторного использования. Все три manifest имеют `production_admission=needs_review`.

## Повторный запуск и расписание

Из корня data-репозитория:

```bash
# Команда для отдельного systemd service/timer: создаёт новый UTC-date run.
python3 -u research/2026-09-29/regional-expansion/refresh_regional.py

# Состояние, указатель на текущие manifest и лог.
cat research/2026-09-29/regional-expansion/latest.json

# Повтор конкретного дня: завершённые datasets проверяются по SHA и пропускаются.
python3 -u research/2026-09-29/regional-expansion/refresh_regional.py --date 2026-09-29
```

`refresh_regional.py` использует `runs/YYYY-MM-DD/`: **на следующий UTC-день скачивает заново**, в тот же день продолжает незавершённое и переиспользует проверенный completed cache. Это ежедневный snapshot, не бесконечно свежий cache. Для внутридневного отдельного snapshot можно явно задать новый каталог через `collect_regional.py --out <new-directory>`. Старые runs сохраняются; retention отдельно не настроен.

Глобальный `flock` в `runtime/refresh.lock` сериализует refresh; ещё один lock внутри каждого run защищает collector. Обёртка записывает PID, start/finish, code hashes, status, exit code и log path в `latest.json`. На child execution лимит 1 500 секунд. HTTP request: timeout 45 секунд, до трёх попыток только для transient network/HTTP 408/429/5xx; лимит ответа 32 MiB, максимум 20 000 aggregate rows. Достижение row limit приводит к failure, не к fake complete. Невременные HTTP/schema/revision/count ошибки не замалчиваются.

Code/plan SHA связаны с checkpoint. При изменении кода нужен новый run-каталог; работающий старый collector/watchdog не изменялся. Самостоятельный `collect_regional.py` с неизменным `--out` **не обновляет** complete cache — для расписания предназначена обёртка с датой.

## Контракт для мониторинга

Успех требует одновременно:

1. `latest.json.status == "complete"`, `exit_code == 0`, актуальный `date` и `finished_at`.
2. Файл по `latest.json.summary` имеет `status == "complete"`, ровно три jobs, каждый `status == "complete"`.
3. В каждом job: `rows`, `checks`, путь `manifest`. Manifest содержит `bindings`, `normalized.{path,rows,bytes,sha256,body_sha256}`, `requests[]` с URL/headers/retrieved_at/body/gzip hashes, `limitations` и admission status.

Ошибка возвращает ненулевой exit, `partial_failed` у collector либо `failed` у wrapper. Вся история загрузок и logs остаётся доступной. Текущее завершение: 2026-09-29 13:53 UTC, 3/3 complete; постоянный timer устанавливает root отдельно.

SHA-256 кода:

```text
collect_regional.py 5717d31caeff7e941ac174c0f1ce2e4c7cfa7edf355b91a870a551d3c43593c0
refresh_regional.py 28f8842975b169b63a1ceb17756b3a272c543f7b9cf2459400623035b76603c0
```

Raw responses, normalized payloads, locks и logs лежат в `runtime/`, игнорируются Git и в корне, и внутри dated runs. Небольшие sources/manifests/summary/samples сохраняются для review. Food, production DB и pinned collectors/config не менялись. Тесты не запускались; проверки выше выполнены во время реального сбора и аудита артефактов.
