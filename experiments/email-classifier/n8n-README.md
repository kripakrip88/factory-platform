# n8n-воркфлоу классификатора писем — источник правды

## Где живёт воркфлоу

**`n8n-workflow.json`** в этой папке — **единственный источник правды** для
воркфлоу «Автоклассификация писем (v2, смотровой режим)»
(id `kyOWFTcrKsTYVI9Y`, инстанс `infra-n8n-1`).

Это штатный экспорт из n8n (`n8n export:workflow`). В нём — структура трубы и
**ссылки** на credential по id/имени, но **без значений секретов** (n8n хранит
credential отдельно, в экспорт воркфлоу они не попадают).

`build_n8n_workflow.py` рядом — генератор-черновик, по которому труба собиралась
изначально. После ручных правок актуальная версия — именно `n8n-workflow.json`
(экспорт из живого n8n), а не вывод генератора.

## Что делает труба (поведение — не менять без отдельного ТЗ)

Расписание (каждую минуту) → GET новых Communication из ERPNext без классификации
→ Claude (промпт v2, `claude-haiku-4-5`) → запись `custom_claude_classification` /
`custom_claude_reason` обратно через `POST /api/method/saas_theme.api.set_classification`.

- **Смотровой режим:** лиды НЕ создаёт, оценку менеджера не трогает, идемпотентна.
- Запись идёт через whitelisted-метод `set_classification` (минует валидацию
  Communication) — обычный REST PUT падал бы `InvalidEmailAddressError` (HTTP 417)
  на письмах с кривым адресом отправителя.

## Правило версионирования (важно)

**Воркфлоу правится через экспорт → git, НЕ напрямую в БД.**

Однократно (2026-06-14) write-нода патчилась прямо в postgres `workflow_entity`
для разблокировки. Это разовое аварийное исключение, оно закрыто: рабочая версия
выгружена сюда. Дальше так не делаем.

Причина — n8n 2.25 использует модель **draft/published**: активный триггер
исполняет опубликованный снимок, а не `workflow_entity.nodes`. Поэтому прямая
правка БД ненадёжна (см. `~/.claude/.../memory/project_n8n_publish.md`).

## Как восстановить воркфлоу из этого файла

### Вариант A — UI (проще)
1. n8n → Workflows → Import from File → выбрать `n8n-workflow.json`.
2. Привязать credential в нодах (см. ниже).
3. Сохранить и **Publish** (n8n 2.25 — иначе триггер не активируется).

### Вариант B — CLI
```bash
docker cp n8n-workflow.json infra-n8n-1:/tmp/wf.json
docker exec infra-n8n-1 n8n import:workflow --input=/tmp/wf.json
# import СБРАСЫВАЕТ публикацию → опубликовать и перезапустить:
docker exec infra-n8n-1 n8n publish:workflow --id=kyOWFTcrKsTYVI9Y
docker restart infra-n8n-1
# проверить лог: "1 published workflows" + "Activated workflow"
docker logs --timestamps infra-n8n-1 2>&1 | grep -iE "published workflows|Activated workflow" | tail -2
```

## Нужные credential (значения заводит Антон вручную в n8n → Credentials)

| Нода | Тип | id | Имя | Header |
|------|-----|----|----|--------|
| Новые письма из ERP / Записать классификацию в ERP | Header Auth | `pMDPaRiYDqpPl0sY` | `ERPNext API (PMK)` | `Authorization: token <api_key>:<api_secret>` |
| Claude классификация (v2) | Header Auth | `BtL7ZOdrlMiPfgK2` | `Anthropic API` | `x-api-key: <claude_key>` |

Значения секретов в git/чат/логи **не пишутся**. ERPNext api_key/secret — на
сервере (`/opt/factory-platform/.erpnext-api-creds`). Claude-ключ — у Антона.
