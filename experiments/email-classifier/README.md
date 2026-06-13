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
