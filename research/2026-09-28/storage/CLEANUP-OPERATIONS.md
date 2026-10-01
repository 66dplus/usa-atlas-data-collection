# Очистка USA Atlas: выполняемый процесс и восстановление

Обновлено 2026-09-28. Пользователь разрешил реальную очистку БД и отдельных ненужных файлов. Работу выполняет `database/cleanup_storage.py`. Все команды ниже относятся только к `usa-atlas-postgres` / `usa_atlas`. Соседний Supabase не используется.

## Что уже выполнено

- Найден существующий контейнер PG16.14 и production schema. Рабочая БД не создавалась заново.
- Реально измерены 63 944 301 591 байт БД и 63 936 045 056 байт `observation`.
- На 63 331 реальных строках всех девяти источников проверено восстановление старых 13 колонок: `EXCEPT ALL` в обе стороны вернул ноль. Пробная модель использовала integer dictionary IDs; production использует bigint. Размер пробы не является прогнозом окончательной экономии.
- Отдельно на disposable PG16 выполнена цепочка v1 schema → production shadow DDL → indexes/FKs → cutover → v2. Физический catalog hash точно совпал с опубликованным v2 pin. [Результат](compact-v1-v2-cutover-rehearsal.json).
- Новый `finish_ingest` проверен на disposable PG: запись двух строк, переиспользование словарей, полный provenance, очистка staging. [Результат](compact-v2-admission-check.json).
- Удалено 7 plain Census metadata JSON, 1 750 405 байт. Их gzip-копии побайтно эквивалентны после распаковки; `cached_payload()` выбирает gzip, manifest не ссылается на plain. Сохранены все gzip и все sidecars. [Результат](plain-duplicate-cleanup.json).

## Текущий процесс

Начальный PID — `1636747`, запуск `2026-09-28T18:48:39Z`. PID не следует считать вечным идентификатором: проверять PID-файл и команду процесса перед управлением.

```bash
cat /srv/usa-atlas/maintenance/20260928-compact/progress.json
cat /srv/usa-atlas/maintenance/20260928-compact/process.pid
tail -n 10 /srv/usa-atlas/maintenance/20260928-compact/process.log
```

Процесс запущен отдельной сессией, переживает закрытие терминала. Он не зарегистрирован как автоматически перезапускаемая служба. Пример unit предоставлен в [usa-atlas-storage-cleanup.service](usa-atlas-storage-cleanup.service); одновременно с текущим процессом его запускать не следует. `Restart=no` намеренно оставляет ошибку для разбора.

`progress.json` сообщает фазы, свободный диск и текущий источник/диапазон. Во время одной большой операции время фазы не обновляется каждую секунду. `backup_running` означает именно работающий `pg_dump`, а не завершённый backup; наличие файла само по себе не подтверждает его готовность. `failed` сохраняет безопасный код ошибки; подробный stderr остаётся в private-файле с mode 600, не в Git и не в пользовательском отчёте.

План без изменения БД:

```bash
python3 database/cleanup_storage.py compact
```

Явный запуск, когда другой maintenance-процесс отсутствует:

```bash
python3 database/cleanup_storage.py compact --apply
```

Повтор после завершения отвечает `already_compact_no_changes`. Второй одновременный процесс блокируется файловым lock. Повтор `files --apply` после удаления семи файлов возвращает no-op и сохраняет исходный акт удаления.

## Что делает компактизация

1. Берёт process lock, оба loader lock (checkout и production admission), PostgreSQL advisory lock и SHARE locks исходных таблиц. Чтение исходной таблицы остаётся доступным; запись/ingest на время обслуживания ждут освобождения locks.
2. Создаёт полный custom-format `pg_dump` только schema `usa_atlas`, включая все её данные. Путь: `/srv/usa-atlas/maintenance/20260928-compact/usa-atlas-before-compact.dump`. Затем полностью читает архив через `pg_restore --file=/dev/null` и сохраняет SHA-256/байты в `backup.json`. Это проверка целостности архива, не утверждение о выполненном полном восстановлении 49 млн строк.
3. Строит `source_resource`, `methodology` и `observation_data`, оставляя исходную `observation` доступной. В словарях сохраняются полные URL и методики. Остальные поля сохраняются без изменения.
4. Копирует каждый ingest одной транзакцией с обязательным сравнением числа вставленных строк. После копирования создаёт PK, индексы и валидирует все FK. Начальный budget: до 30 GiB новых relations, 4 GiB backup, 16 GiB sort, 12 GiB WAL; это консервативные допуски, а не измеренные итоговые размеры. Перед стартом требуется 74 GiB свободного места; рабочий floor 12 GiB.
5. Сравнивает полные counts и контрольные суммы всех 13 исходных полей по каждому источнику. Дополнительно делает **точное сравнение каждой строки** по исходному PK, с восстановлением URL/методики и `ROW IS DISTINCT FROM` остальных колонок. Проверка разбита на 102 диапазона `geo_id`; новый PK уникален, counts равны, каждый исходный ключ должен присутствовать и совпадать. Это не выборочная проверка. Результат — `exact-validation.json`.
6. Проверяет hashes staged code в `/srv/usa-atlas/compact-20260928-staged-code/staging-manifest.json`. Под loader locks устанавливает совместимые production schema/loader, сохраняя v1-файлы для отката. Собственные append/locking guards production loader сохранены.
7. В одной короткой транзакции переключает `observation` в совместимый view, устанавливает новый writer и прежние имена индексов, удаляет старую физическую таблицу и меняет schema pin. До COMMIT проверяет полный catalog hash. При несовпадении транзакция откатывается, v1 deployment files восстанавливаются.
8. После COMMIT измеряет итоговые relations и сохраняет `result.json`, а также копии результата/audit в этом каталоге. Только `phase=complete` и соответствующий результат подтверждают завершение и реально освобождённые байты.

Итоговые файлы процесса:

| Файл в `/srv/usa-atlas/maintenance/20260928-compact/` | Назначение |
|---|---|
| `progress.json`, `process.log`, `process.pid` | Ход и идентификация процесса |
| `backup.json`, `usa-atlas-before-compact.dump` | Проверенный исходный архив |
| `source-fingerprint.json`, `compact-fingerprint.json` | Полные контрольные суммы всех исходных полей |
| `copied-sources.json` | Завершённые порции копирования |
| `exact-validation.json` | Прогресс точного сравнения всех строк |
| `result.json`, `postgres-after-cleanup.json` | Успешное завершение и измерение размера |
| `*.private.log`, `catalog-mismatch.json` | Диагностика, не публиковать без проверки |

## Восстановление после сбоя

Автоматический повтор отключён. До cutover исходные данные остаются в прежней таблице; незавершённая транзакция копирования отдельного ingest откатывается PostgreSQL. Падение соединения с lock-сессией освобождает PostgreSQL locks и откатывает незафиксированный cutover.

Сначала проверить `progress.json`, жив ли записанный PID, и присутствуют ли maintenance/pg_dump сессии **именно в `usa_atlas`**. Не удалять файлы и не запускать второй процесс, пока первый ещё работает. Проверять существование view/table `usa_atlas.observation`, потому что сбой отчётности после COMMIT отличается от сбоя самой миграции.

**Если оборвался backup:** `backup.json` ещё отсутствует, файл `.dump` существует. Повтор намеренно остановится с `incomplete_backup_present_restore_or_review_manually`. После подтверждения отсутствия работающего процесса переместить незавершённый архив, сохранив его для разбора:

```bash
python3 - <<'PY'
from pathlib import Path
from datetime import datetime, timezone
s = Path('/srv/usa-atlas/maintenance/20260928-compact')
assert not (s / 'backup.json').exists(), 'Существует запись проверенного backup: сначала проверить её'
p = s / 'usa-atlas-before-compact.dump'
target = p.with_name(p.name + '.incomplete-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
assert not target.exists()
p.rename(target)
print('Незавершённый архив сохранён; основной путь свободен для нового pg_dump.')
PY
python3 database/cleanup_storage.py compact --apply
```

Этот фрагмент выполняется **только после проверки отсутствия живого процесса**; он не убивает процессы и не удаляет backup. Незавершённый архив можно удалить позже, когда новый backup полностью проверен. Если `backup.json` существует, сначала проверить SHA-256: не подменять и не переименовывать уже подтверждённый архив вслепую.

**Если backup проверен, но процесс оборвался до привязки baseline:** будущие запуски требуют, чтобы `backup.json.source_fingerprint_sha256` совпадал с SHA-256 существующего `source-fingerprint.json`. Отсутствие fingerprint, отсутствие привязки или несовпадение останавливает повтор с `backup_reuse_requires_bound_source_fingerprint`. Нельзя взять прежний backup и после перезапуска незаметно привязать к нему уже изменившуюся БД. Даже при корректной привязке runner заново сравнивает полный fingerprint действующей исходной таблицы с сохранённым.

После подтверждения отсутствия активного maintenance/pg_dump процесса сохранить **вместе** dump и metadata, освободив пути для нового backup. Если существует непривязанный fingerprint, сохранить и его, чтобы новый запуск не унаследовал неполный checkpoint:

```bash
python3 - <<'PY'
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json
s = Path('/srv/usa-atlas/maintenance/20260928-compact')
metadata = s / 'backup.json'
info = json.loads(metadata.read_text())
fingerprint = s / 'source-fingerprint.json'
bound = (fingerprint.exists() and
         info.get('source_fingerprint_sha256') == hashlib.sha256(fingerprint.read_bytes()).hexdigest())
assert not bound, 'Checkpoint привязан: это другой случай, сначала разобрать ошибку'
archive = s / ('unbound-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
archive.mkdir(mode=0o700)
for name in ('usa-atlas-before-compact.dump', 'backup.json', 'source-fingerprint.json'):
    path = s / name
    if path.exists():
        path.rename(archive / name)
print('Непривязанный checkpoint сохранён; новый запуск создаст свежий backup.')
PY
python3 database/cleanup_storage.py compact --apply
```

Эта процедура также требует предварительной проверки отсутствия живого процесса. Текущий непрерывный запуск PID 1636747 был запущен до усиления recovery-проверки: он держит исходные таблицы под locks от backup до сравнения и продолжает работу без перезапуска. Изменение относится к будущим запускам. Его старый `backup.json` без новой привязки нельзя автоматически переиспользовать после прерывания.

**Если оборвались shadow copy / проверки:** проверить baseline hash и свободный диск. Runner способен переиспользовать проверенный backup, словари и полностью завершённые ingest; частичный размер source или изменившийся original fingerprint вызывает остановку. Первоначальный запас 74 GiB повторно обязателен: при недостатке места нельзя обходить guard. Под контролем оператора удалить только однозначно идентифицированные shadow objects после подтверждения, что исходная `observation` всё ещё таблица и проверенный backup существует; затем повторить build. Не выдавать такую частичную очистку за завершение миграции.

**Если cutover откатился:** исходная таблица сохранена; runner восстанавливает production `schema.sql.v1`/`load.py.v1`. После аварийного завершения ОС проверить согласованность файлов и БД вручную по staged hashes: переключение двух файлов и БД не является одной общей файловой транзакцией. Под loader locks привести deployment к фактической версии БД перед новым ingest.

**Если COMMIT прошёл, но отчёт не записан:** view `observation`, физическая `observation_data` и v2 catalog hash подтверждают факт переключения. Повторная команда делает no-op. Выполнить audit, проверить counts и schema pins, затем восстановить отчёт; старую таблицу заново не создавать.

Для полного отката после успешного COMMIT сначала восстановить проверенный dump в отдельную изолированную USA Atlas restore-среду, проверить counts/ключи/provenance и только затем планировать замену работающей БД с v1 deployment. Готовой команды уничтожения действующей БД здесь намеренно нет. Большой backup сохраняется до подтверждения успешного обновления и чтения UI.

## Повторный аудит

```bash
python3 database/audit_storage.py --postgres-container > /tmp/usa-atlas-storage-audit.json
```

SQL поддерживает старую таблицу и новый view: `TABLESAMPLE` применяется к реальной `observation_data`, затем подключаются словари. Аудит не выполняет очистку. Он не показывает secrets, row values или URLs; connection identity фиксирована на относящемся к проекту контейнере.
