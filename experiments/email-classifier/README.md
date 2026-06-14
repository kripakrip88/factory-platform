# experiments/email-classifier

Разовый batch-прогон классификации ~100 уже загруженных писем через Claude
(холостой режим). Изолированный эксперимент — ничего не создаёт (ни лидов, ни
ответов), вложения не трогает. Цель: первая цифра точности на реальном потоке +
список ошибок для доводки промпта v2.

## Состав
- `prompt-v1.md` — черновой промпт (5 полок: Новая заявка / Вопрос по заказу /
  Поставщик / Спам / Прочее).
- `classify_batch.py` — bench-скрипт: читает Communication-письма ящика, пишет
  `Классификация Claude` + `Обоснование Claude` в карточку. Пейсер под лимит,
  резюмируемость (пишет в карточку сразу).
- `howto-review.md` — как менеджеру ставить Верно/Неверно.

## Поля на карточке письма (Custom Fields на Communication)
Создаются в ERP (блок «Классификация (эксперимент)»):
`custom_claude_classification`, `custom_claude_reason`, `custom_manager_verdict`,
`custom_correct_shelf` (видно только если оценка «Неверно»).

## Запуск прогона (на сервере, ключ Claude через -e — не в git/чат)
```bash
# 1) скопировать скрипт в контейнер как frappe-модуль:
docker cp classify_batch.py erp-backend-1:/home/frappe/frappe-bench/apps/frappe/frappe/_classify_batch.py
# 2) запустить со своим ключом Claude:
docker exec -e ANTHROPIC_API_KEY='sk-ant-...' -e EMAIL_ACCOUNT='PMK Park входящие (тест)' \
  erp-backend-1 bash -c 'cd /home/frappe/frappe-bench && bench --site erp.localhost execute frappe._classify_batch.execute'
# 3) после прогона удалить модуль:
docker exec erp-backend-1 rm -f /home/frappe/frappe-bench/apps/frappe/frappe/_classify_batch.py
```
Лог (stderr) обезличен — только счётчики по полкам. Тела писем уходят в Anthropic
API (требование задачи), в git/лог не пишутся.

## Приватность
- Ключ Claude — через окружение (`-e`), не в код/git/чат.
- Тела писем/ПД в git и отчёты не выносятся.
- Прогон только на сервере. Прод-стек не трогается (только Custom Fields + запись
  в карточки писем).

---

## n8n-труба автоклассификации (смотровой режим, промпт v2)

**Что делает:** каждые 15 мин берёт из ERPNext новые Communication без
классификации → Claude (промпт v2) → пишет `Классификация Claude` + `Обоснование`
обратно в карточку. НЕ создаёт лидов, оценку менеджера не трогает, идемпотентна.

Файлы:
- `build_n8n_workflow.py` — генератор воркфлоу (промпт v2 встроен).
- `n8n-classifier-workflow.json` — готовый воркфлоу (создан в n8n, id в истории).

Воркфлоу уже создан в n8n (выключен). Осталось подключить 2 credential и включить.

### Шаг 1 — ERPNext API credential
Ключ/секрет уже сгенерированы и лежат на сервере (вне git):
```bash
cat /opt/factory-platform/.erpnext-api-creds   # api_key=... api_secret=...
```
В n8n: **Credentials → New → Header Auth**:
- Name: `ERPNext API (PMK)`
- Header Name: `Authorization`
- Header Value: `token <api_key>:<api_secret>` (из файла выше, через двоеточие)

### Шаг 2 — Anthropic API credential
В n8n: **Credentials → New → Header Auth**:
- Name: `Anthropic API`
- Header Name: `x-api-key`
- Header Value: `<твой Claude API key>`

### Шаг 3 — привязать credential к узлам и включить
Открыть воркфлоу «Автоклассификация писем (v2, смотровой режим)»:
- узлам **«Новые письма из ERP»** и **«Записать классификацию в ERP»** → credential `ERPNext API (PMK)`
- узлу **«Claude классификация (v2)»** → credential `Anthropic API`
- нажать **Active** (включить).

### Проверка
Очистить классификацию у 2-3 писем (для теста) и нажать **Execute Workflow** —
у писем должна появиться `Классификация Claude` + обоснование, лиды НЕ создаются,
`Оценка менеджера` остаётся пустой.
