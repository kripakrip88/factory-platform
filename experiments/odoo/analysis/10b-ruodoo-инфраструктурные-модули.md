# RuOdoo — инфраструктурные и производственные модули (27 шт.)

База анализа: `scratchpad/ruodoo` (релиз 2026-09-14, Odoo 19), сверка с Odoo 19 Community
`scratchpad/odoo/addons` (638 модулей).
Адресат: завод металлоконструкций, Хабаровск, оценка замены ERPNext.

---

## 0. Главное в трёх пунктах

1. **Из 27 модулей заводу реально нужны 3-4**: `base_user_role` (роли),
   `base_tier_validation` (многоступенчатое согласование — но его придётся *дописывать*,
   в RuOdoo он подключён ровно к одной модели), `mklab_mrp_filters` (радиус гиба + группировка
   операций по заказу продажи — единственный модуль «про металл» во всём релизе,
   но требует правки манифеста) и опционально `dms` + `mklab_dms_document`
   (входящая/исходящая корреспонденция).
2. **Три крупных подсистемы (директивы, слои показателей, прогнозное планирование) —
   это чужие отраслевые продукты MK.Lab**: прогноз построен на дне недели и «скидке на полке»
   (FMCG/розница), смета показателей — на этапах стройки (котлован, монолит, отделка).
   Позаказному производству металлоконструкций они не подходят.
3. **Два модуля под проприетарными лицензиями** (`web_debranding` — OPL-1, 300 EUR;
   `premium_client` — OEEL-1). Оба не нужны для работы завода; `premium_client` вообще
   отправляет заявки на внешний API вендора.

---

## 1. Доступ, права, роли (5 модулей)

### `base_user_role` — роли пользователей ⭐ НУЖЕН
`base_user_role/__manifest__.py:11` — LGPL-3, автор ABF OSIELL / OCA
(`github.com/OCA/server-backend`), depends: `base`. Статус `Production/Stable`.

Что даёт (штатный Odoo этого не умеет — в ядре есть только группы):
- `res.users.role` (`base_user_role/models/role.py:12`) — роль = именованный набор групп,
  за ролью стоит собственная `res.groups` (`group_id`, строка 16). Поля `rule_ids` (строка 29) и
  `model_access_ids` (строка 36) показывают, какие `ir.rule` и ACL роль фактически приносит —
  это ровно то, чего не хватает при отладке прав.
- `res.users.role.line` (`role.py:127`) — **срок действия роли**: `date_from` / `date_to`
  (строки 141-142), `is_enabled` (143). Роль «Мастер участка на время отпуска» сама погаснет.
- Cron `Update user roles` каждые 3 часа (`base_user_role/data/ir_cron.xml:7-13`) →
  `cron_update_users()` (`role.py:111`) пересобирает группы пользователей из ролей.
- Визарды: создать роль из существующего пользователя
  (`base_user_role/wizards/create_from_user.py`), собрать роль из групп
  (`wizards/wizard_groups_into_role.py`), массово добавить людей в роль
  (`wizards/role_add_users_wizard.py`).

Для завода: прямая замена ручного возделывания групп. Аналог того, что в ERPNext
делается через Role Profile. Берём.

### `access_restricted` — урезанный админ
`access_restricted/__manifest__.py` — MIT (в манифесте `"Other OSI approved licence"`),
IT-Projects LLC, depends: `ir_rule_protected`.
Содержимое — три записи безопасности (`access_restricted/security/access_restricted_security.xml`):
- `ir.rule` «Only admin can edit admin» с `domain_force = [('id','!=',1)]` (строка 11) —
  никто кроме uid 1 не правит запись администратора;
- `ir.rule` `res.groups.restricted` (строка 16) — не-суперадмин видит на запись только те
  группы, в которых состоит сам;
- группа `group_allow_add_implied_from_settings` (строка 3).
Все правила помечены `protected = True` — см. следующий модуль.

Для завода: нужен только если директор хочет «сисадмина без доступа к чужим правам».
Для одного завода с одним админом — избыточно.

### `ir_rule_protected` — защита правил доступа
`ir_rule_protected/__manifest__.py` — MIT, depends: `[]` (ничего).
`ir_rule_protected/models.py:10` — добавляет `ir.rule.protected` (Boolean); `check_restricted()`
(строка 15) кидает `UserError` при `write`/`unlink` защищённого правила кем угодно кроме
`SUPERUSER_ID`; `ir.module.module.button_uninstall` (строка 34) запрещает удалить сам модуль.
Технический фундамент под `access_restricted`. Отдельной ценности нет.

### `access_apps` — спрятать «Приложения»
`access_apps/__manifest__.py` — MIT, depends: `access_restricted`, есть `uninstall_hook`.
`access_apps/security/access_apps_security.xml`: отключает штатный ACL
`base.access_ir_module_module_group_user` (строка 7), вводит группы
`group_allow_apps_only_from_settings` (строка 13, implied → `base.group_system`) и
`group_allow_apps` (17), закрывает меню `base.menu_management` под эту группу (строка 30).

⚠️ Побочный эффект задокументирован самим вендором: `tests/odoo-base-test.md:33-41` —
`access_apps` ломает базовые тесты Odoo `test_user_has_group` и
`test_views.test_17_attrs_groups_validation`, потому что меняет иерархию `group_system`.
Вендор пишет «ожидаемое поведение, не трогаем». Для завода, который потом будет
обновлять Odoo, это лишний риск на пустом месте.

### `access_settings_menu` — «Настройки» не-админу
`access_settings_menu/__manifest__.py` — MIT, depends: `access_restricted`.
`security/access_settings_menu_security.xml`: группа `group_show_settings_menu` (строка 4),
меню `base.menu_administration` закрывается под неё (строка 9),
`base.group_erp_manager` её подразумевает (строка 15). 11 строк XML.

---

## 2. Многоступенчатое согласование (3 модуля)

### `base_tier_validation` — движок согласования ⭐ НУЖЕН, НО ТРЕБУЕТ ДОРАБОТКИ
`base_tier_validation/__manifest__.py:7` — **AGPL-3**, ForgeFlow / OCA
(`github.com/OCA/server-ux`), версия `19.0.2025.12.03`, статус `Mature`, depends: `mail`.

#### Как устроено
Четыре модели:
| Модель | Файл | Роль |
|---|---|---|
| `tier.definition` | `models/tier_definition.py:7` | правило: кто и что согласует |
| `tier.review` | `models/tier_review.py` | конкретная «виза» на конкретном документе |
| `tier.validation` (AbstractModel) | `models/tier_validation.py:22` | миксин, который вешается на документ |
| `tier.validation.exception` | `models/tier_validation_exception.py` | какие поля можно править во время/после согласования |

#### Как настраивается (без кода, из интерфейса)
В `tier.definition` (`models/tier_definition.py`):
- `model_id` (строка 26) — какой документ согласуем (список ограничен: домен берётся из
  `_get_tier_validation_model_names()`, строка 17 — **см. ниже, это и есть ограничение**);
- `review_type` (строка 32): `individual` (конкретный человек) / `group` (любой из группы) /
  `field` (лицо из поля самой записи — например, `user_id` менеджера сделки);
- `definition_domain` (строка 61) — **условие срабатывания**: например
  `[('amount_total','>',500000)]` → «КП дороже 500 тыс. согласует директор»;
- `sequence` (строка 63) + `approve_sequence` (строка 106) — строгая очередь ступеней
  (сначала технолог, потом экономист, потом директор), `approve_sequence_bypass` (строка 111) —
  автопропуск ступени, если её уже подписал тот же человек;
- уведомления: `notify_on_create` / `notify_on_pending` / `notify_on_accepted` /
  `notify_on_rejected` / `notify_on_restarted` (строки 74-97);
- `notify_reminder_delay` (строка 101) + cron «Send Tier Review Reminder»
  (`data/cron_data.xml:3-14`, раз в сутки, `model._cron_send_review_reminder()`) —
  напоминание о зависших визах;
- `has_comment` (строка 99) → обязательный комментарий при отказе
  (`wizard/comment_wizard.py`).

На документе миксин даёт кнопки и поля: `request_validation()`
(`models/tier_validation.py:768`), `validate_tier()` (625), `reject_tier()` (639),
`restart_validation()` (803), плюс вычисляемые `validation_status`, `can_review`,
`next_review`, `reviewer_ids`. Переход состояния контролируется парой
`_state_from` → `_state_to` (строки 30-32) и блокируется в `write()` (372) через
`_tier_validation_check_write_allowed` (433) — то есть документ **физически нельзя** провести
мимо согласования, а не «нежелательно».
Если у модели `_tier_validation_manual_config = False`, кнопки и блок виз внедряются в форму
автоматически через переопределённый `get_view()` (`models/tier_validation.py:876-905`) —
править XML вида не надо.

#### Годится ли для согласования КП и заказов у директора — да, но
**Механика ровно та, что нужна заводу**: «КП до 300 тыс. — сам менеджер; 300 тыс. — 1 млн —
начальник отдела; свыше — директор; при отказе обязателен комментарий; через 2 дня простоя —
напоминание». Многоступенчатость, суммовые пороги, очередь, отказ с причиной, история —
всё есть из коробки и настраивается мышкой.

**НО**: в RuOdoo движок подключён ровно к **одной** модели — `dms.document`
(`mklab_dms_document/models/tier_dms.py:6`, `_state_from = ['draft']`, `_state_to = ['done']`;
регистрация модели в списке — `mklab_dms_document/models/tier_definition.py:8-11`).
Модулей OCA `sale_tier_validation`, `purchase_tier_validation`, `account_tier_validation`
в релизе **нет** (проверено: в `scratchpad/ruodoo` таких папок не существует;
поиск `tier.validation` вне `base_tier_validation/` даёт только `mklab_dms_document`).

Значит для КП (`sale.order`) и заказов на производство (`mrp.production`) нужен свой
модуль-обвязка. Объём — десятки строк по образцу `mklab_dms_document`:
```python
class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "tier.validation"]
    _state_field = "state"; _state_from = ["draft"]; _state_to = ["sale"]
```
плюс `_get_tier_validation_model_names()` дополнить `'sale.order'`.

Что в Odoo 19 CE есть штатно, чтобы понимать, что именно мы получаем сверху:
- `sale.order` — согласования **нет** вообще (`odoo/addons/sale/models/sale_order.py:1168`
  `action_confirm()` без каких-либо проверок утверждения);
- `purchase.order` — есть примитивная двойная валидация по сумме
  (`odoo/addons/purchase/models/res_company.py:16-22`: `po_double_validation`
  `one_step`/`two_step` + `po_double_validation_amount`, применяется в
  `purchase_order.py:1255-1258`) — одна ступень, один порог, без очереди и напоминаний;
- `mrp.production` — согласования **нет** (grep `approv` по
  `odoo/addons/mrp/models/mrp_production.py` — пусто).

Итого `base_tier_validation` закрывает реальную дыру. Лицензия AGPL-3 — для внутреннего
использования на своём сервере вопросов не вызывает.

### `tier_communications` — НЕ имеет отношения к согласованию
Ловушка в названии. `tier_communications/__manifest__.py` — LGPL-3, автор MKLAB,
depends: `mail` (не `base_tier_validation`!). Категория `Discuss`.
Это надстройка над мессенджером: `tier.mailbox` (`models/tier_mailbox.py:7`, с флагами
`is_lead_inbox` / `is_ticket_inbox`, строки 19-20), `tier.channel.tag`
(`models/tier_channel_tag.py:6`), `tier.channel.email` (`models/tier_channel_email.py:10`),
правила маршрутизации `tier.routing.channel` (по контрагенту,
`models/tier_routing_channel.py:5`) и `tier.routing.mailbox` (по модели,
`models/tier_routing_mailbox.py:5`), метки сообщений `tier.mailbox.tag`,
патч сайдбара Discuss (`static/src/components/discuss_sidebar_mailboxes.js`),
визард «переложить сообщение в другой ящик» (`wizard/tier_move_to_mailbox_wizard.py`).

Для завода: не нужен. Задача «письма клиентов попадают в CRM» решается штатной
`mail.alias` + `crm` + `fetchmail` в Odoo CE.

### `tier_communications_matrix` — Matrix-мессенджер
`tier_communications_matrix/__manifest__.py` — LGPL-3, depends: `tier_communications`.
`models/res_users_matrix.py:8-16` — `tier_matrix_homeserver`, `tier_matrix_access_token`,
`tier_matrix_room_id` у пользователя; вебхук `controllers/matrix_webhook.py`.
Дефект манифеста: `views/tier_channel_matrix_views.xml` лежит в папке, но **не указан**
в `data` → не загружается.
Для завода: не нужен (у вас Telegram, не Matrix).

---

## 3. Директивы — «поручения из бизнес-событий» (2 модуля)

### `directive_layer`
`directive_layer/__manifest__.py` — LGPL-3, Mk.lab, `application: True`,
depends: `base`, `web`, `base_user_role`, `project`.
Модели: `directive.directive` (`models/directive.py:16`), `directive.mixin`
(`models/directive_mixin.py:10`), `directive.origin` (`models/directive_origin.py:5` —
привязка к любой записи через `Reference`), `directive.policy`
(`models/directive_policy.py:5`), `directive.stage`, `directive.template`,
`directive.template.group`, `directive.work_type`.

Директива = поручение с полями `deadline_at`, `planned_hours` (трудоёмкость),
`load_percent`, `success_probability`, `resource_cost`, `retry_policy`, `priority`,
`executor_role_id` / `requester_role_id` (роли из `base_user_role`),
две независимые стадии `executor_stage_id` / `requester_stage_id` и «светофоры»
`executor_traffic_light` / `resource_traffic_light` (`models/directive.py:32-125`).
Плюс OWL-компонент «доска исполнителя»
(`static/src/components/executor_board/executor_board.js`).

`directive.policy` — генератор: `event` = `on_create` / `on_write` / `on_stage` / `on_cron` /
`on_callback` (`models/directive_policy.py:22-33`), `mode` = `create_once` / `create_each_time`,
условие `trigger_field` + `trigger_value_int` (строки 55-60), проверка в
`_policy_should_fire()` (строка 63).

⚠️ Инженерный запах: `on_callback` реализован обезьяньим патчем методов модели в
`_register_hook()` / `_directive_register_callback_wrappers()`
(`models/directive_mixin.py:261-330`), причём с прямым SQL-запросом к
`information_schema.tables` для проверки, существует ли таблица `directive_policy`
(строка 278). Это работает, но хрупко при обновлениях.

### `directive_test`
`directive_test/__manifest__.py` — LGPL-3, depends: `sale`, `mail`, `account`,
`account_payment`, `mrp`, `project`, `directive_layer`, `base_user_role`, `stock`.
Навешивает `directive.mixin` на семь моделей: `sale.order`
(`models/sale_order.py:6`), `account.move`, `account.payment`, `mrp.workorder`
(`models/mrp_workorder.py:6`), `mrp.production` (строка 46), `stock.picking`,
`project.task`.
Это **демонстрация, не продукт**: в `models/mrp_workorder.py:20` домен спецификации
генерации — `[("name","ilike","резка")]`, метод `action_iot_signal()` (строка 23)
постит в чат выдуманную телеметрию станка («Температура шпинделя 59°C»),
`models/sale_order.py:22` `action_wms_response()` рапортует про ячейку `ZONE-A-ROW-5`,
а в `models/mrp_workorder.py` в коде прямо стоит комментарий `# КОСТЫЛЬ`.

Для завода: идея (автопоручение мастеру при переходе операции в «готово к работе») здравая,
но в Odoo 19 CE это же делается штатной **Automation / server actions** (`base_automation`)
без отдельного слоя моделей. Ставить `directive_layer` ради этого — взять на баланс
4000+ строк чужого фреймворка. **Не рекомендую.**

---

## 4. Документооборот (2 модуля)

### `dms` — OCA Document Management System ⭐ УСЛОВНО НУЖЕН
`dms/__manifest__.py:6` — **LGPL-3**, MuK IT / Tecnativa / OCA (`github.com/OCA/dms`),
версия `19.0.2025.12.03`, `application: True`, depends: `mail`, `http_routing`,
`onboarding`, `portal`, `base`, `web`. 18 МБ (в основном иконки типов файлов).

Модели:
- `dms.storage` (`dms/models/storage.py:15`) — хранилище, `save_type` (строка 19),
  `model_ids` (строка 73 — к каким моделям привязано),
  `inherit_access_from_parent_record` (74), `include_message_attachments` (81);
- `dms.directory` (`dms/models/directory.py:27`) — дерево папок (`parent_id`, `parent_path`),
  права через `group_ids` / `complete_group_ids` (строки 93-100) с наследованием
  `inherit_group_ids` (195), счётчики файлов/размера, **`alias_process`** (строка 197) —
  папка может принимать вложения с email-алиаса (`directory.py:624`);
- `dms.file` (`dms/models/dms_file.py:27`) — файл: `content` / `content_file` / `content_binary`,
  `checksum` SHA-1 (строка 112), `extension`, `mimetype`, `size`/`human_size`,
  `res_model`/`res_id`/`attachment_id` (189-195), блокировка `locked_by` / `is_locked` (614-616),
  миграция хранилища `require_migration` (130);
- `dms.category`, `dms.tag`, `dms.access.groups`.
- Визарды: `wizard.dms.share` (`dms/wizards/wizard_dms_share.py:8` — выдать ссылку в портал),
  `wizard.dms.file.move`. Портальный шаблон `template/portal.xml`.
- `mail.thread._process_attachments_for_post` переопределён (`dms/models/mail_thread.py:10`) —
  вложения из чата записи автоматически раскладываются в DMS.

### `mklab_dms_document` — реестр входящих/исходящих
`mklab_dms_document/__manifest__.py` — **лицензия в манифесте НЕ указана** (поле `license`
отсутствует вообще), автор MK.Lab, depends: `base`, `dms`, `utm`, `base_tier_validation`.
⚠️ `'version': '13.20230927'` — манифест не приведён к схеме 19.0.x, версия помечена как 13.

Модель `dms.document` (`mklab_dms_document/models/document.py:68`,
наследует `portal.mixin`, `mail.thread`, `mail.activity.mixin`, `utm.mixin`):
`type_document` = `incoming` / `outgoing` / `internal` (строка 129), `name` — номер
(для исходящих из нумератора, `get_number()` строка 116), `partner_id`, `date`,
`text` (HTML), `incoming_file` (PDF) / `incoming_file_other` + `incoming_file_type` (134-136),
`file` → `dms.file` (139), произвольная привязка `link_model` + `res_id` (140-141),
`print_head` (143), `state` = `draft` / `done` («Записано в хранилище», 144),
иерархия `parent_id` / `child_ids` / `subordinate_ids` (145-147).
Шаблоны текста: `dms.template` (`document.py:62`) + визард выбора `dms.choise_template` (47).
Рендер шаблонов — Jinja2 `SandboxedEnvironment` с mako-подобными разделителями
`<% %>` / `${}` (`document.py:14-44`).
Согласование: `dms.document` наследует `tier.validation`
(`models/tier_dms.py:6`, `draft` → `done`) — единственное место в релизе, где движок виз
реально подключён.

### Заменяет ли это Enterprise-модуль `documents`?
В Odoo 19 Community модуля `documents` **нет** (проверено: `scratchpad/odoo/addons/documents`
отсутствует, как и `documents_project`). То есть без Enterprise альтернативы у вас всё равно нет,
и `dms` — единственный вариант.

Но **паритета с Enterprise `documents` нет**:
| Возможность | Enterprise `documents` | OCA `dms` |
|---|---|---|
| Папки/рабочие области с правами | да | да (`dms.directory` + `group_ids`) |
| Теги, категории | да | да (`dms.tag`, `dms.category`) |
| Приём почты в папку | да | да (`alias_process`) |
| Публикация в портал / ссылка наружу | да | да (`wizard.dms.share`) |
| **Правила-автоматизации над файлами** (workflow actions) | да | **нет** |
| **Версионирование файлов** | да | **нет** (grep `version` по `dms/models/*.py` — ничего) |
| **OCR / распознавание** | да | **нет** |
| Разделение PDF, интеграция с Sign, Spreadsheet | да | нет |

Для завода: `dms` + `mklab_dms_document` закрывают журнал входящей/исходящей корреспонденции
(письма, ТУ, акты, претензии) с нумерацией, шаблонами и визированием — это ощутимо больше,
чем есть сейчас в ERPNext «из коробки». Но хранение КМД-чертежей с версиями (Рев.0 → Рев.1)
модуль **не** решает: версионирования нет, придётся вести ревизии вручную через имя файла.

---

## 5. Слои показателей (4 модуля) — чужая отрасль

### `mklab_base_indicators`
`mklab_base_indicators/__manifest__.py` — **лицензия не указана**, MK.Lab,
версия `19.0.2025.11.17`, depends: `base`.
Гиперграф показателей: `hg.node` (`models/hg_node.py:6` — вершина = ссылка на любую запись
через `res_model`/`res_id`), `hg.index` (`models/hg_index.py:6` — показатель с
`internal_code_id`, `external_code`, `current_value`), `hg.value`
(`models/hg_value.py:6` — `value_float_plan` / `value_float_actual`, `date_due`, `formula`),
`hg.link` (`models/hg_link.py:6` — источник → множество приёмников),
миксин `hg.hg_mixin` (`models/hg_mixin.py:5`).

### `mklab_project_task_indicators`
Лицензия не указана, depends: `base`, `mklab_base_indicators`, `project`.
Одна строка сути: `project.task` наследует `hg.hg_mixin`
(`mklab_project_task_indicators/models/project_task.py:6`) + печатная форма
(`reports/template.xml`).

### `mklab_base_indicators_extended` — «Смета»
Лицензия не указана, depends: `base`, `mklab_project_task_indicators`.
`hg.templates` / `hg.templates.line` (`models/hg_templates.py:6,13`) — шаблон сметы
(показатель + плановая дата + плановая сумма), `estimate.wizard`
(`wizard/estimate_wizard.py:5`) разворачивает шаблон в задачу.
**Ключевое — демо-данные**: `data/data.xml:5-38` заводит показатели
«Работы по проектированию», «Подготовка котлована», «Фундамент», «Монолитные работы»,
«Отделочные работы», «Инженерные работы». Это стоимостная смета **строительного объекта**
по этапам СМР, а не калькуляция металлоизделия (масса × цена стали + нормо-часы +
покрытие + маржа).

### `mklab_base_indicators_report`
Лицензия не указана, depends: `base`, `mklab_base_indicators_extended`.
Визард-отчёт «Показатели по узлам» (`wizard/report_wizard.xml`), рисует граф связей задач.
⚠️ `models/hg_index.py:2-3` — `import networkx as nx` и `import matplotlib.pyplot as plt`,
при этом в `__manifest__.py` блока `external_dependencies` **нет** → при отсутствии
библиотек модуль упадёт на импорте, а не выдаст понятную ошибку установки.
(В корневом `requirements.txt` `networkx` и `matplotlib` присутствуют.)

Для завода: механика «план/факт по узлам с формулами» теоретически применима к
сметам объектов (если завод делает не только отгрузку, но и монтаж). Но это отдельная
методология на `project.task`, никак не связанная с `mrp.production` / `mrp.bom` /
себестоимостью Odoo. Внедрять — значит вести вторую, параллельную систему учёта стоимости.
**Не рекомендую на старте.**

---

## 6. Производство (2 модуля)

### `mklab_forecast_mrp` — прогноз продаж → заказы на производство ❌ НЕ ДЛЯ ПОЗАКАЗНОГО
`mklab_forecast_mrp/__manifest__.py` — **лицензия не указана**,
автор «Mikhail Skvortsov Lab», версия `19.0.1.0.0`, depends: `base`, `sale`, `mrp`.

Что делает фактически (`models/forecast.py`, 236 строк):
- `mklab.forecast` (строка 11) — прогноз **на конкретную дату** (`start_date`), с полями
  `expected_growth` («Ожидаемый рост продаж при акции, %», строка 25), `is_promo`,
  `state` draft/active;
- `mklab.forecastline` (строка 104) — строка по товару: `forecast_value` (план),
  `order_value` (факт в заказах), `invoice_value` (факт отгружено), `bom_id`, `mrp_order_id`;
- **алгоритм прогноза** — `get_forecast_values()` (строка 156): берёт заказы продаж
  за **последние 84 дня** (строка 158) **с тем же днём недели**
  (`('dayofweek','=',weekday)`, строка 166), нормирует на прошедшие акции
  (`mklab.marketaction`, коэффициент `expected_growth` по строке акции),
  суммирует и **делит на 12** (строка 235) → средняя продажа этого товара в такой день недели;
- `dayofweek` — новое store-поле на `sale.order`
  (`models/sale_order.py:11-25`);
- `create_mrp()` (строка 84) — по строкам с `forecast_value > 0` создаёт `mrp.production`
  с `product_qty = forecast_value`, `date_start = дата прогноза`;
- `find_available_bom()` (`models/product.py:17`) — берёт **первую** спецификацию, все компоненты
  которой есть на складе (`bom_available()`, `models/mrp.py:14` — сравнение с `qty_available`);
- `mklab.marketaction` / `mklab.productline` / `mklab.partnerline` — реестр акций;
- `discount.py` (111 строк) — анализ роста продаж от пары скидок.
- README прямо говорит: «наша скидка + **скидка на полке**»
  (`mklab_forecast_mrp/README.md`).

**Применимость к позаказному производству металлоконструкций — нулевая.**
Причины конкретные:
1. Прогноз строится на **дне недели** за 12 недель. У завода МК заказ — это объект
   на 200 тонн, который бывает раз в квартал. «Средняя продажа балки по вторникам» —
   бессмысленная величина.
2. Нет привязки к заказу клиента: `create_mrp()` создаёт `mrp.production` **без**
   `sale_line_id` — то есть производство «на склад», а не под заказ. Позаказное
   производство в Odoo делается ровно наоборот: маршрут MTO + `sale_mrp`
   (в CE есть, `odoo/addons/sale_mrp`), который сам плодит MO из подтверждённой сделки.
3. Продукт должен быть заранее заведён с флагом `is_forecast_ok`
   (`models/product.py:9`) и постоянной BOM. У завода МК изделие обычно **новое**
   на каждый заказ (по КМД), постоянной номенклатуры с историей продаж нет.
4. Понятийный аппарат — «маркетинговая акция», «скидка на полке», «ожидаемый рост» —
   это FMCG/розница/пищёвка.

Единственное, что можно было бы позаимствовать, — идея `bom_available()` (подбор
спецификации по наличию на складе), но в Odoo для этого есть штатный расчёт
доступности компонентов MO.

### `mklab_mrp_filters` — единственный «заводской» модуль в релизе ⭐ НУЖЕН (с правкой)
`mklab_mrp_filters/__manifest__.py` — **лицензия не указана**, Mk.Lab,
версия `19.0.23.10.2025`, depends: **`mrp_workorder`** (Enterprise!) + `sale_mrp`.
Весь модуль — 8 файлов, два python-файла по 10-30 строк, два XML вида.

Что добавляет:
- `mrp.routing.workcenter.bending_radius` («Bending Radius»,
  `models/mrp_routing_workcenter.py:7`) — **радиус гиба на операции маршрута**;
- на `mrp.workorder` (`models/mrp_workorder.py`):
  - `bending_radius` (related от операции, store),
  - `product_sources_id` / `production_sources_id` — **корневое изделие и корневой MO**,
    вычисляется рекурсивным подъёмом по многоуровневой BOM
    (`_get_sources_while()`, строка 34, через `production._get_sources()`),
  - `sale_order_id` — заказ продажи, вытащенный из корневого MO через `sale_line_id`
    (строка 31),
  - `sale_date` — дата заказа продажи (related, store),
  - `material_ids` — Many2many комплектующих из `move_raw_ids` (строка 20);
- в форму/список/поиск операций (`views/mrp_workorder.xml`) добавлены группировки:
  **по заказу продажи, по исполнителю, по корневому изделию, по корневому MO,
  по радиусу гиба, по дате заказа, по материалу**.

Это ровно то, что нужно цеху: «покажи все операции гибки R=25 по объекту такому-то»,
«все операции по заказу №123 через все уровни BOM».

#### Что потеряется, если не ставить (и надо ли вообще терять)
`mrp_workorder` — модуль **Enterprise** («Shop Floor» / планшетный режим оператора).
Проверено: в `scratchpad/odoo/addons` его **нет** (как нет `quality`, `quality_control`,
`mrp_mps`, `mrp_plm`, `approvals`). Значит на Community модуль в текущем виде
**не установится вообще** — без `mrp_workorder` ни одна его строка не заработает.

Но дальше хорошая новость — зависимость почти фиктивная. Проверил построчно:
- модель `mrp.workorder` **есть в Community** (`odoo/addons/mrp/models/mrp_workorder.py:16`);
- метод `mrp.production._get_sources()`, на котором держится вся рекурсия, —
  **есть в Community** (`odoo/addons/mrp/models/mrp_production.py:1523`);
- все четыре наследуемых вида есть в Community `mrp`:
  `mrp_routing_workcenter_form_view` (`odoo/addons/mrp/views/mrp_routing_views.xml`),
  `mrp_production_workorder_form_view_inherit`, `mrp_production_workorder_tree_view`,
  `view_mrp_production_workorder_form_view_filter`
  (все три — `odoo/addons/mrp/views/mrp_workorder_views.xml`);
- xpath `//sheet/group[2]/group[2]/field[@name='production_id']` из
  `mklab_mrp_filters/views/mrp_workorder.xml` в структуру Community-вида **попадает**.

Единственная настоящая привязка к Enterprise — поле **`user_id`** на `mrp.workorder`:
в поисковом виде (`mklab_mrp_filters/views/mrp_workorder.xml`, `<field name="user_id"/>`
и фильтр `Executor` с `group_by: user_id`), а в Community `mrp.workorder` такого поля
**нет** (есть только `working_user_ids` и `last_working_user_id`,
`odoo/addons/mrp/models/mrp_workorder.py:122-123`; определения `user_id = fields...` нет).

**Вывод:** порт на Community — правка двух мест: в манифесте
`'depends': ['mrp', 'sale_mrp']` вместо `['mrp_workorder','sale_mrp']`, и убрать/заменить
`user_id` на `last_working_user_id` в поисковом виде. Потеряется при этом **только**
группировка «по исполнителю» в её Enterprise-виде — всё остальное (радиус гиба,
корневое изделие, корневой MO, заказ продажи, материалы) работает.

Отдельно: `mrp_workorder` как Enterprise-модуль сам по себе даёт планшетный
Shop-Floor-интерфейс оператора (шаги операции, чек-листы, штрихкоды). Этого на Community
не будет вообще — и это, вероятно, более весомая потеря для цеха, чем сам
`mklab_mrp_filters`. Но она к данному модулю не относится.

---

## 7. Дебрендинг (4 модуля) + витрина вендора

### `web_debranding` — ⚠️ ПРОПРИЕТАРНЫЙ
`web_debranding/__manifest__.py:14` — **`license: "OPL-1"`**, `"price": 300.00`,
`"currency": "EUR"`, IT-Projects LLC, версия `19.0.3.0.0`, depends: `base_setup`, `web`,
`mail`, `mail_bot`, `base`; `external_dependencies: python: ["lxml"]`; есть `uninstall_hook`.
В шапке файла — двойная формулировка: «License MIT ... License OPL-1 for derivative work».
Фактически в поле `license` стоит OPL-1 (Odoo Proprietary License), и указана цена.

Что делает: переопределяет `ir.config_parameter` (метод `get_debranding_parameters`),
`ir.actions`, `ir.http`, `ir.model`, `ir.module.module.search`
(`web_debranding/models/ir_module_module.py:8` — фильтрует выдачу модулей),
`ir.ui.view`, `ir.translation`, `res.company`, `res.users`,
`res.config.settings.fields_view_get` (`models/res_config_settings.py:13`),
плюс JS: `base.js`, `dialog.js`, `field_upgrade.js`, `user_menu_items.js`, `translation.js`.
Переименовывает бота (`web_debranding/data.xml:13-16`: `base.partner_root` → «Bot»,
`bot@example.com`) и глушит «звонок домой»: `publisher_warranty.contract.update_notification`
(`models/publisher_warranty_contract.py:18-30`) не вызывает super, **но только если
это Community** — при Enterprise (`version_info[5] == "e"`) super вызывается принудительно,
с комментарием в коде «Running Odoo EE without calling super is illegal».

### `portal_debranding`
`portal_debranding/__manifest__.py` — LGPL-3, TAKOBI / OCA (`github.com/OCA/server-brand`),
depends: `portal`, **`web_debranding`**. Два XML: `views/portal_templates.xml`,
`views/web_login_debrand.xml`. Убирает «Powered by Odoo» из портала и со страницы входа.

### `website_debranding`
`website_debranding/__manifest__.py` — LGPL-3, Tecnativa / OCA, depends: `website`,
**`portal_debranding`**, `post_init_hook`. Один шаблон `templates/disable_odoo.xml`.

### `pos_debranding`
`pos_debranding/__manifest__.py` — MIT, версия **`17.0.1.0.0`** (не приведена к 19.0 —
модуль, похоже, не обновлялся), depends: `point_of_sale`. Убирает брендинг из кассы.

### Можно ли обойтись без OPL-1 модулей?
**Да, и нужно.**
- Цепочка зависимостей жёсткая: `website_debranding` → `portal_debranding` → `web_debranding`
  (OPL-1). То есть **любой** дебрендинг портала/сайта в этом релизе тянет за собой
  платный проприетарный модуль. Отдельно LGPL-часть не поставить.
- Заводу в Хабаровске дебрендинг не нужен **вообще**: система внутренняя, снаружи её видят
  максимум подрядчики через портал. Логотип и название компании в интерфейсе штатно меняются
  в `Settings → Companies` без всякого дебрендинга.
- Единственный практический смысл `web_debranding` — отключить отправку статистики
  в Odoo S.A. (`publisher_warranty`). Это делается одной строкой в `odoo.conf`
  (`publisher_warranty_url = ` пустой) или отключением крона
  `Update Notification`, без покупки модуля за 300 EUR.
- `pos_debranding` не нужен по факту отсутствия кассы у завода МК.

**Рекомендация: не ставить ни один из четырёх.** Заодно это снимает риск
лицензионного спора — OPL-1 запрещает перераспространение и модификацию без покупки.

### `premium_client` — ⚠️ ПРОПРИЕТАРНЫЙ + внешний вызов
`premium_client/__manifest__.py` — **`license: "OEEL-1"`** (Odoo Enterprise Edition License!),
`author: "Your Company"`, `website: "https://example.com"` (заглушки не заполнены),
`application: True`, depends: `base`, `web`.
`premium.service` (`models/premium_service.py:7`) — канбан карточек услуг вендора;
`premium.order.wizard` (`wizard/premium_order_wizard.py:18`) собирает заявку
(название компании, ИНН, email, телефон/телеграм, контактное лицо) и
`action_submit()` (строка 93) **отправляет её POST-запросом наружу** на
`premium.project_api_url` + `/newlead/` с заголовком `X-API-Key`, 3 попытки, timeout 15 с.
В payload уходит в том числе `"source_db": self.env.cr.dbname`
(`wizard/premium_order_wizard.py:87`).
Дефолты в `data/system_parameters.xml:5-12`: URL `http://localhost:8069/newlead/`,
токен `default-premium-token-2024`.

Для завода: это витрина платных доработок MK.Lab, то есть канал продаж вендора внутри
вашей ERP. Функциональной ценности — ноль, лицензия OEEL-1 (проприетарная Enterprise),
плюс исходящий запрос с именем вашей БД. **Не ставить.**

---

## 8. Сервисные модули (4 модуля)

### `ruodoo_setup_all` — это НЕ мастер установки
`ruodoo_setup_all/__manifest__.py` — LGPL-3, версия **`17.0.1.0.0`** (не обновлена до 19.0),
MK.Lab. Весь модуль — **3 файла**: `__init__.py`, `__manifest__.py`, иконка.
Это **мета-модуль-пустышка**: вся его суть — список `depends` из 12 модулей
(`account_bank_statement_1c_import`, `base_tier_validation`, `base_user_role`, `l10n_ru_doc`,
`l10n_ru_act_rev`, `l10n_ru_advance_payments`, `l10n_ru_attorney`, `l10n_ru_contract`,
`l10n_ru_upd_xml`, `translation_helper`, `crm`, `project`, `point_of_sale`),
которые Odoo подтянет автоматически при его установке.
Плюс `post_init_hook` (`ruodoo_setup_all/__init__.py:1-10`) — ровно 7 строк: загрузить
`ru_RU` и поставить его админу. Никакого мастера, никаких вопросов, никакой настройки
компании/плана счетов/налогов.

⚠️ Обратите внимание: в зависимостях сидит `point_of_sale` — заводу МК касса не нужна,
а модуль установится и притащит свои таблицы. Ставить `ruodoo_setup_all` «чтобы всё сразу»
— значит принять решение вендора о наборе модулей. Лучше ставить нужное точечно.

### `ruodoo_demo_data` — демо-данные
`ruodoo_demo_data/__manifest__.py` — LGPL-3, MK.Lab, версия `19.0.1.0.0`.
Depends: 19 модулей (`base`, `base_setup`, `account`, `crm`, `project`, `sale`,
`base_user_role`, `docx_report`, шесть `l10n_ru_*`, три `mklab_*indicators`,
`mklab_dms_document`, `dms`).
Загружает ~25 XML в строгом порядке: контрагенты с ИНН/КПП/ОГРН/ОКПО, банки, пользователи,
роли, ЕИ, продукты, сотрудники, профили и договоры, `account.move`, заказы на закупку,
доверенности, авансовые счета, заказы продажи, стадии и сделки CRM, проекты и задачи,
показатели (`hg_index_code` / `hg_node` / `hg_index` / `hg_templates`),
DMS (группы доступа → категории → теги → хранилища → директории → файлы → шаблоны →
документы), шаблоны DOCX.
Заметьте: **`data`, не `demo`** — то есть данные ставятся при обычной установке модуля,
не только с флагом `--without-demo=false`.

Для завода: полезно **однократно на тестовом стенде**, чтобы посмотреть, как всё связано.
В рабочую базу — категорически нет, потом не вычистить.

### `translation_helper` — помощь с переводами
`translation_helper/__manifest__.py` — **LGPL-3**, MK.Lab / RuOdoo (`ruodoo.ru`),
версия `19.0.1.0.1`, depends: `web`, `external_dependencies: python: ["siphashc", "polib"]`.

Что делает (по коду):
- `translation.service` (`models/translation_service.py:28`) — принимает из UI
  `resModel` / `field.name` и контекст (строки 33-34), т.е. перевод привязан к конкретному
  полю конкретной модели;
- переопределяет `base` (`models/base.py:9`), `ir.http`, `ir.qweb`, `ir.model.fields`,
  `ir.module.module`, `res.config.settings`;
- `translation.helper.wizard` (`wizards/translation_helper_wizard.py:18`) — **пишет переводы
  прямо в PO-файлы модулей на диске** через `polib`: читает существующий
  (`polib.pofile(local_po_file)`, строка 92, с перебором кандидатов, строка 101),
  формирует новый `polib.POFile()` (116) и `polib.POEntry` (129);
- JS-компоненты (`static/src/**/*`) — перевод поля из контекстного меню в режиме разработчика;
- заявлены глоссарии и «память переводов» (описание в манифесте).

⚠️ Расхождение: `polib` объявлен в `external_dependencies` модуля, но в корневом
`scratchpad/ruodoo/requirements.txt` его **нет** (там есть `siphashc`, но не `polib`).
При деплое по requirements модуль не установится.

Для завода: **потенциально самая практичная утилита в этой группе.** Ровно та боль, которую
вы уже прошли в ERPNext — ~14k строк кастомных переводов и заводской глоссарий. Здесь
правка идёт в PO-файлы (версионируемые в git), а не в таблицу БД, что сильно лучше для
воспроизводимости. Но: инструмент **ручного** перевода, автоперевода нет; пишет в файлы
модулей — значит своей папке аддонов нужны права на запись, а при обновлении апстрима
переводы надо будет мержить.

### `tests` — не модуль, а отчёт
`tests/__manifest__.py` — LGPL-3, «DOB Tests», Mk.Lab, версия `19.0.1.0.0`.
Внутри **всего два файла**: манифест и `odoo-base-test.md`. Никакого кода тестов нет —
манифест только перечисляет 20 зависимостей (все кастомные модули), чтобы одним
`-i tests` поднять их все и прогнать тесты Odoo.

`tests/odoo-base-test.md` — отчёт вендора о прогоне `--test-tags base`:
**«Module base: 23 failures, 26 errors of 979 tests»** (`odoo-base-test.md:14`).
Разбор честный и полезный для оценки зрелости:
- исправлено вендором: `access_restricted` падал на `ImportError`, т.к. в Odoo 19 удалили
  `name_selection_groups` из `res_users` (`odoo-base-test.md:22-28`);
- «ожидаемо»: `access_apps` меняет иерархию `group_system` → ломает `test_user_has_group`
  и `test_views` (строки 33-45); множественные `_inherit` от `access_restricted`,
  `base_user_role`, `web_debranding`, `base_tier_validation`, `access_settings_menu`,
  `l10n_ru_doc`, `l10n_ru_upd_xml` ломают `test_ir_model.test_inherit` (строки 49-53);
- «окружение»: `test_cli` (17 ошибок, нет TTY в Docker), `test_translate` (9, нет языков),
  `test_test_retry` (8, намеренные), `test_profiler` (2), `test_acl` + `test_res_partner_merge`
  (из-за `hr`).

Читается как: **функциональных регрессий в ядре вендор не нашёл**, но модули доступа
осознанно ломают базовые тесты Odoo, и это принято как норма. Для проекта, который вы
собираетесь потом обновлять между версиями Odoo, это флаг: `access_apps` лучше не ставить.

---

## 9. Итоговая таблица: модуль → нужен заводу → почему

| Модуль | Лицензия | Нужен? | Почему |
|---|---|---|---|
| `base_user_role` | LGPL-3 (OCA) | **ДА** | Роли вместо ручных групп, срок действия роли (`date_from`/`date_to`), cron пересборки. Прямой аналог Role Profile из ERPNext, в ядре Odoo такого нет |
| `base_tier_validation` | AGPL-3 (OCA) | **ДА, + своя обвязка** | Единственный способ получить многоступенчатое согласование КП/заказов: пороги по сумме (`definition_domain`), очередь ступеней (`approve_sequence`), отказ с комментарием, напоминания по крону. В CE у `sale.order` согласования нет вовсе. Но в релизе подключён только к `dms.document` — под `sale.order`/`mrp.production` нужен модуль ~30 строк |
| `mklab_mrp_filters` | не указана | **ДА, после порта** | Радиус гиба на операции + группировка операций по заказу продажи и корневому изделию через многоуровневую BOM. Единственный модуль релиза «про металл». Требует замены `depends: mrp_workorder` (Enterprise) на `mrp` и удаления поля `user_id` из поискового вида |
| `dms` | LGPL-3 (OCA) | **УСЛОВНО** | Enterprise-модуля `documents` в CE нет, альтернативы тоже. Папки с правами, приём почты в папку (`alias_process`), выдача в портал, блокировка файла. Но **нет версионирования, OCR и правил-автоматизаций** — для ревизий КМД не годится |
| `mklab_dms_document` | **не указана** | **УСЛОВНО** | Журнал входящих/исходящих/внутренних с нумератором, шаблонами (Jinja2), иерархией и визированием через `tier.validation`. Полезно для корреспонденции. Минусы: версия манифеста `13.20230927`, лицензия не заявлена |
| `translation_helper` | LGPL-3 | **СКОРЕЕ ДА** | Правка переводов прямо в PO-файлы модулей (`polib`) — версионируется в git, в отличие от ERPNext-подхода через таблицу БД. Минус: `polib` отсутствует в `requirements.txt`; автоперевода нет |
| `tests` (отчёт) | LGPL-3 | **прочитать один раз** | Кода нет, только `odoo-base-test.md`: 23 failures / 26 errors из 979 базовых тестов, причины разобраны. Полезен как оценка зрелости и как предупреждение про `access_apps` |
| `ruodoo_demo_data` | LGPL-3 | **только стенд** | Демо через `data` (не `demo`) → ставится в обычную базу и не вычищается. Годится, чтобы один раз посмотреть связи на тестовом сервере |
| `access_settings_menu` | MIT | НЕТ | 11 строк XML: открыть меню «Настройки» не-админу. Решается назначением `base.group_erp_manager` |
| `access_restricted` | MIT | НЕТ | Сценарий «сисадмин без доступа к правам». У завода с одним админом-директором такой задачи нет |
| `ir_rule_protected` | MIT | НЕТ | Технический фундамент под `access_restricted`, самостоятельной ценности нет |
| `access_apps` | MIT | **НЕТ (риск)** | Спрятать «Приложения». По собственному отчёту вендора (`tests/odoo-base-test.md:33-45`) ломает базовые тесты Odoo, меняя иерархию `group_system`. Лишний риск при будущих обновлениях |
| `tier_communications` | LGPL-3 | НЕТ | Несмотря на имя — **не** про согласование, а про почтовые ящики и маршрутизацию в Discuss. Задача «письма клиентов → CRM» решается штатными `mail.alias` + `fetchmail` |
| `tier_communications_matrix` | LGPL-3 | НЕТ | Интеграция с Matrix. У завода Telegram. Плюс дефект манифеста: `views/tier_channel_matrix_views.xml` не подключён |
| `directive_layer` | LGPL-3 | НЕТ | 8 моделей чужого фреймворка поручений (стадии, светофоры, роли, политики). То же в CE делается `base_automation` без нового слоя. Плюс обезьяний патч методов в `_register_hook()` и SQL к `information_schema` |
| `directive_test` | LGPL-3 | НЕТ | Демонстрация: домен `[("name","ilike","резка")]`, фейковая телеметрия шпинделя, ячейка `ZONE-A-ROW-5`, комментарий `# КОСТЫЛЬ` в коде |
| `mklab_base_indicators` | **не указана** | НЕТ | Гиперграф показателей план/факт. Не связан с `mrp.bom` и себестоимостью Odoo — это вторая, параллельная система учёта стоимости |
| `mklab_project_task_indicators` | **не указана** | НЕТ | Одна строка: `project.task` + миксин показателей. Без базового слоя смысла нет |
| `mklab_base_indicators_extended` | **не указана** | НЕТ | «Смета» с демо-показателями стройки: котлован, фундамент, монолит, отделка (`data/data.xml:5-38`). Не калькуляция металлоизделия |
| `mklab_base_indicators_report` | **не указана** | НЕТ | Отчёт-граф. `networkx`/`matplotlib` импортируются в `models/hg_index.py:2-3`, но в манифесте нет `external_dependencies` → упадёт на импорте |
| `mklab_forecast_mrp` | **не указана** | **НЕТ (чужая отрасль)** | Прогноз по **дню недели** за 84 дня / 12, «маркетинговые акции», «скидка на полке». MO создаётся **без** `sale_line_id`, т.е. на склад, а не под заказ. Требует постоянной номенклатуры с историей — у завода МК изделие новое на каждый КМД. Позаказное производство в CE делается MTO + `sale_mrp` |
| `web_debranding` | **OPL-1, 300 EUR** | **НЕТ** | Проприетарный и платный. Логотип/название компании меняются штатно в `Settings → Companies`; отправку статистики в Odoo S.A. глушат пустым `publisher_warranty_url` в `odoo.conf` |
| `portal_debranding` | LGPL-3 (OCA) | НЕТ | Сам LGPL, но `depends: web_debranding` — тянет OPL-1. Заводу дебрендинг портала не нужен |
| `website_debranding` | LGPL-3 (OCA) | НЕТ | Через `portal_debranding` тоже тянет OPL-1. Сайта у завода в Odoo не планируется (есть pmkpark.ru на Bitrix) |
| `pos_debranding` | MIT | НЕТ | Касса заводу МК не нужна. Плюс версия манифеста `17.0.1.0.0` — модуль не обновлён |
| `premium_client` | **OEEL-1** | **НЕТ** | Витрина платных доработок MK.Lab внутри вашей ERP. `action_submit()` POST-ит наружу заявку с `"source_db"` — именем вашей базы. Проприетарная лицензия, ноль функциональной ценности |
| `ruodoo_setup_all` | LGPL-3 | НЕТ | Не мастер установки, а мета-пустышка из 3 файлов: список `depends` + 7 строк хука «поставить админу `ru_RU`». В зависимостях сидит `point_of_sale`. Ставить нужное точечно |

**Свод: из 27 модулей — 3 берём уверенно (`base_user_role`, `base_tier_validation`,
`mklab_mrp_filters` после порта), 3 условно (`dms`, `mklab_dms_document`,
`translation_helper`), 1 читаем как отчёт (`tests`), 1 только на стенд (`ruodoo_demo_data`),
19 не берём.**

---

## 10. Что из этого следует для решения «Odoo vs ERPNext»

1. **Согласование КП директором** — единственная по-настоящему сильная карта этой группы.
   `base_tier_validation` даёт настраиваемые из интерфейса пороги, очередь ступеней и
   напоминания. Но подключать к `sale.order` придётся самим (~30 строк).
   Заложите это в оценку работ, а не считайте «есть из коробки».
2. **`mklab_mrp_filters` — индикатор, что вендор видел настоящий цех**: радиус гиба
   на операции и подъём до корневого изделия через многоуровневую BOM — это не придумаешь
   в офисе. Но модуль требует Enterprise-зависимости, которая на 95% фиктивна. Стоит
   уточнить у вендора, будет ли официальный Community-вариант.
3. **Лицензионная гигиена**: из 27 модулей у **8 поле `license` в манифесте не заполнено
   вообще** (все `mklab_*` кроме indicators_report — там тоже нет, `mklab_dms_document`,
   `mklab_forecast_mrp`, `mklab_mrp_filters`). Это надо закрыть письменно с вендором
   до внедрения. Два модуля прямо проприетарные (OPL-1, OEEL-1) — оба можно и нужно
   не ставить.
4. **Три подсистемы — не ваша отрасль.** Прогноз по дням недели со «скидкой на полке»,
   смета по этапам стройки, слой поручений с телеметрией шпинделя — это переиспользованные
   наработки MK.Lab из ритейла, стройки и демо. Не покупайтесь на «а ещё тут есть
   планирование производства»: к позаказному производству металлоконструкций оно
   не применимо ни одной строкой.
5. **Enterprise-дыры в производстве, которые эта локализация НЕ закрывает** (проверено
   по `odoo/addons`: отсутствуют `mrp_workorder`, `quality`, `quality_control`, `mrp_mps`,
   `mrp_plm`, `documents`, `approvals`): нет планшетного Shop Floor для оператора,
   нет контроля качества, нет MPS, нет управления версиями чертежей.
   `dms` версионирования тоже не даёт. Для завода МК с КМД-документацией
   (Рев.0 → Рев.1 → Рев.2) это самая серьёзная незакрытая зона.
