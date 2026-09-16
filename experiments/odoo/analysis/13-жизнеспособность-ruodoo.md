# Жизнеспособность RuOdoo как сторонней локализации

Анализ: `scratchpad/ruodoo` (48 модулей, релиз 19.0 от 2026-09-14) против
`scratchpad/odoo` (Odoo 19.0 Community, 638 модулей в `addons/`).
Контекст решения: завод металлоконструкций, Хабаровск, оценка замены ERPNext.

Метрики пака: 54 766 строк `.py`+`.xml`+`.js`, 490 файлов `.py`, 225 новых моделей (`_name`).

---

## 1. Кто автор

### Публикация

Репозиторий — зеркало, а не место разработки:

- `release-note.md:4` — «Репозиторий: `https://git.corp.ruodoo.ru/odoo/ruodoo-project.git`» (внутренний, недоступен).
- `git remote -v` → `https://git.ruodoo.ru/ruodoo-public/public.git` (публичное зеркало).
- Вся история — **один коммит**: `5bcc8384ff0b3e3a3b6ca5fd5cb48568efbc33dd`,
  автор `CI Publish Bot <ci-publish@ruodoo.ru>`, 2026-09-14 13:47:24 +0000,
  сообщение «Public release from ruodoo-project: 19.0».

Следствия, все проверены:

- Нет истории коммитов → нельзя увидеть, кто что писал, когда и почему, нельзя сделать `git blame`, нельзя отследить регрессию.
- Нет корневых `LICENSE`, `README`, `CONTRIBUTING`, нет `.github/` и никаких CI-конфигов.
- Нет публичного issue-трекера: баг послать некуда.
- **Поле `maintainer` отсутствует у 48 из 48 модулей.** Персонально ответственного нет ни за один модуль.

### Кто стоит за кодом

Фактический автор — не «RuOdoo», а **MK.Lab / ИНФ-Центр**. Бренд `ruodoo.ru`
в `author` стоит всего у 3 модулей (`account_move_templates`,
`account_move_templates_invoice`, `translation_helper`).

Распределение по `author` в `__manifest__.py`:

| Автор | Модулей | Что это |
|---|---|---|
| MK.Lab (+ варианты `Mk.lab`, `MK.lab`, `Mk.Lab`, `MKLAB`, `Mikhail Skvortsov Lab`) | 26 | основной разработчик, сайт `inf-centre.ru` (19 модулей) |
| IT-Projects LLC, Ivan Yelizariev | 6 | `access_apps`, `access_restricted`, `access_settings_menu`, `ir_rule_protected`, `pos_debranding`, `web_debranding` |
| OCA | 5 | `base_tier_validation` (ForgeFlow), `base_user_role` (ABF OSIELL), `dms` (MuK IT/Tecnativa), `portal_debranding` (TAKOBI), `website_debranding` (Tecnativa) |
| RYDLAB | 3 | `custom_report_field`, `docx_report_generation`, `report_monetary_helpers` |
| CodeUP + MK.Lab | 1 | `l10n_ru_doc` |
| `Your Company` / `Custom` / `Tier` / нет | 4 | незаполненные шаблоны |

То есть RuOdoo — это **сборка**: ~26 своих модулей MK.Lab плюс 14 чужих
(OCA, IT-Projects, RYDLAB), переупакованных под своим брендом. Пять разных
написаний имени одного и того же автора в манифестах — показатель того, что
единого ревью манифестов нет.

### Коммерческая модель и платная поддержка

Прайс-листа или условий поддержки в репо **нет**. Но модель монетизации видна
прямо в коде — модуль `premium_client` («Премиум (витрина сервисов)»):

- `premium_client/README.md:31-38` — каталог платных услуг: «Услуги (интеграции и доработки)», «Банки, кассы, ЭДО», «WMS, логистика и ЧЗ (честный знак)», «Маркетплейсы (Ozon, Wildberries, Яндекс)», «Отраслевые», «Другое».
- Кнопка «Заказать» собирает **название компании, ИНН, email, телефон, контактное лицо** из профиля компании Odoo (`premium_client/README.md:42-48`) и POST-ит на внешний API:
  - `premium_client/wizard/premium_order_wizard.py:130` — `requests.post(url, json=payload, headers=headers, timeout=15)`
  - `premium_client/wizard/premium_order_wizard.py:121` — токен в заголовке `X-API-Key`
  - `premium_client/data/system_parameters.xml:5-14` — дефолты в продакшн-данных: URL `http://localhost:8069/newlead/`, токен `default-premium-token-2024`

Вывод: **поддержка RuOdoo — это заказные доработки и интеграции за деньги, а не
подписка на саму локализацию**. Локализация бесплатна и отдаётся «как есть» без
SLA. Это не плохо само по себе, но означает: если MK.Lab потеряет интерес к
бесплатной части, ничьих контрактных обязательств это не нарушит.

Отдельно: модуль, который отправляет ИНН и контакты компании на внешний
endpoint, в заводской системе ставить не нужно (см. §3 — он ни от кого не
зависит и выбрасывается бесследно).

---

## 2. Активность

### Changelog

`release-note.md` генерируется скриптом `scripts/generate_addons_info.py`
(которого в паке нет). Содержимое:

- **Всего 16 записей changelog на 48 модулей.**
- **36 модулей — «Нет истории изменений».** То есть у трёх четвертей пака нет ни одной зафиксированной правки.
- Все 16 записей — в окне **2026-04-07 … 2026-04-27**:
  1 × 07.04, 1 × 13.04, **7 × 15.04**, 1 × 17.04, **6 × 27.04**.
  Ни одной записи вне апреля 2026.
- Релиз опубликован 2026-09-14 → **~4,5 месяца между последней зафиксированной правкой и публичным релизом**.

Характер записей — мелкий ремонт, не развитие: «исправлен вызов `has_group`
через `env.user` вместо модели `res.users`» (`access_apps`, `access_restricted`),
«исправлена передача many2one полей как id вместо кортежа» (`dadata_connector`),
«исправлен размер и битые репорты» (`docx_report`), «исправлен путь к иконке»
(`ruodoo_demo_data`). Единственная содержательная: `mklab_forecast_mrp` —
«**[ADD]** (2026-04-13) портиров. на 19.0».

### Версии и скорость подхвата Odoo 19

Odoo в паре — `19.0` финальный: `odoo/odoo/release.py:15` →
`version_info = (19, 0, 0, FINAL, 0, '')`.

Свои дата-штампы версий в манифестах покрывают диапазон
`19.0.2025.06.06` (`l10n_ru_advance_payments`) … `19.0.2025.12.11`
(`l10n_ru_upd_xml`) — основная масса кода штампована вторым полугодием 2025.

Но «48 модулей под Odoo 19» — с оговорками. **Хвосты порта не закрыты:**

| Модуль | Версия в манифесте | Проблема |
|---|---|---|
| `ruodoo_setup_all` | `17.0.1.0.0` | **мета-модуль установки всего пака** до сих пор помечен 17.0 |
| `pos_debranding` | `17.0.1.0.0` | не портирован |
| `mklab_dms_document` | `13.20230927` | штамп эпохи Odoo 13 |
| `l10n_ru_act_rev` | `0.1` | версия не заполнена вообще |
| `l10n_ru_attorney` | `0.1` | то же |

### Забота об апгрейдах — почти нулевая

- `migrations/` есть **у 1 модуля из 48**: `base_tier_validation/migrations/18.0.2.1.0/pre-migration.py` — и это OCA-наследие, не работа RuOdoo.
- `openupgradelib` заявлен в `requirements.txt`, но используется **только в этом одном файле**.
- То есть при переходе на следующий мажор Odoo миграцию данных для 47 модулей придётся писать самому.

### Что в паке сделано хорошо

Единственный сильный сигнал качества — **тесты**: 50 файлов `test_*.py`,
7 226 строк, папка `tests/` у **29 модулей из 48** (включая `l10n_ru_doc`,
`l10n_ru_contract`, `l10n_ru_upd_xml`, `l10n_ru_advance_payments`,
`l10n_ru_attorney`). Для российской локализации это нетипично много.

Слабое место рядом: `ru.po` есть только **у 12 модулей из 48**
(`account_bank_statement_1c_import`, `base_user_role`, `custom_report_field`,
`dadata_connector`, `dms`, `docx_report_generation`, `l10n_ru_advance_payments`,
`l10n_ru_doc`, `mklab_mrp_filters`, `report_monetary_helpers`,
`translation_helper`, `web_debranding`). Модули `l10n_ru_*` написаны по-русски
в исходнике, но OCA/IT-Projects-часть (`base_tier_validation` 4 451 строка,
`dms` 8 836 строк, `access_*`) переводов не имеет → интерфейс будет частично
англоязычным, и переводить это придётся заводу.

---

## 3. Лицензии

### Подсчёт по всем 48 манифестам

| Лицензия | Модулей |
|---|---|
| LGPL-3 | 21 |
| **поле `license` отсутствует** | **18** |
| `Other OSI approved licence` | 5 |
| AGPL-3 | 2 |
| **OPL-1** (проприетарная) | **1** — `web_debranding` |
| **OEEL-1** (проприетарная) | **1** — `premium_client` |

### 18 модулей без лицензии — это хуже, чем OPL-1

Odoo при загрузке молча подставляет LGPL-3 и пишет предупреждение:

```
odoo/modules/module.py:432-434
    if not manifest.get('license'):
        manifest['license'] = 'LGPL-3'
        _logger.warning("Missing `license` key in manifest for %r, defaulting to LGPL-3", module)
```

Это **дефолт загрузчика, а не передача прав правообладателем**. Юридически
модуль без явной лицензии = «все права защищены»: права на использование,
модификацию и распространение не переданы.

Кого это касается — ровно тех модулей, которые заводу нужнее всего:

`l10n_ru_act_rev`, `l10n_ru_attorney`, `l10n_ru_contract`,
`l10n_ru_contract_account`, `l10n_ru_contract_purchase`,
`l10n_ru_contract_sale`, `l10n_ru_contract_templates`, `l10n_ru_upd_xml`,
`l10n_ru_advance_payments`, `account_bank_statement_1c_import`,
`dadata_connector`, `mklab_forecast_mrp`, `mklab_mrp_filters`,
`mklab_base_indicators` (+ `_extended`, `_report`), `mklab_dms_document`,
`mklab_project_task_indicators`.

Практический риск — не иск (MK.Lab сама выложила код публично), а то, что
**при аудите, продаже бизнеса или споре предъявить нечего**. Лечится одним
письмом: попросить у MK.Lab явно проставить лицензию. Если откажутся или не
ответят — это сам по себе ответ про жизнеспособность проекта.

Плюс 5 модулей IT-Projects с `"license": "Other OSI approved licence"` —
это строка из селекшена Odoo Apps Store, а не лицензия. Конкретная лицензия
не названа → тот же неопределённый статус.

### `web_debranding` (OPL-1) — чужой платный модуль в публичном репо

`web_debranding/__manifest__.py`:

- строка 8-9: `# License MIT (...)` и `# License OPL-1 (...) for derivative work.`
- строка 14: `"license": "OPL-1"`
- строка 12: `"author": "IT-Projects LLC, Ivan Yelizariev"`
- `"support": "apps@itpp.dev"`, **`"price": 300.00, "currency": "EUR"`**

Что это значит:

- **Это платный модуль из Odoo Apps Store за 300 €**, принадлежащий IT-Projects LLC, а не RuOdoo.
- OPL-1 (Odoo Proprietary License v1.0) разрешает покупателю использовать модуль на своих серверах, но **прямо запрещает распространение, публикацию и перепродажу копий**.
- Структура лицензии двойная: базовый код под MIT, доработки IT-Projects — под OPL-1. Именно доработки и составляют модуль.
- Фактически RuOdoo **распространяет чужой платный проприетарный модуль в публичном репозитории**. Законность его наличия у завода подтверждается не файлом от RuOdoo, а покупкой у `apps@itpp.dev`.

Дополнительно: модуль осознанно работает на грани — патчит
`publisher_warranty.contract` (проверку/телеметрию Odoo Enterprise),
и сам это фиксирует в коде:
`web_debranding/models/publisher_warranty_contract.py:20` —
`# Running Odoo EE without calling super is illegal. So, make it impossible to disable in enterprise.`

### `premium_client` (OEEL-1) — незаполненный скаффолд

`premium_client/__manifest__.py`:

- строка 5: `"author": "Your Company"`
- строка 6: `"website": "https://example.com"`
- строка 7: `"license": "OEEL-1"`
- строка 13: `"data/system_parameters.xml",  # Добавить эту строку` — **отладочный комментарий, дошедший до публичного релиза**

OEEL-1 — Odoo Enterprise Edition License, лицензия для кода Odoo Enterprise.
Применять её к собственному модулю юридически бессмысленно: RuOdoo не может
лицензировать свой код под лицензией Odoo SA. Это не осознанное решение, а
copy-paste из шаблона, который никто не заполнил. Тот факт, что такой файл
прошёл в публичный релиз, сам по себе говорит об уровне выпускного контроля.

### Можно ли работать без проприетарных? Да, полностью

Проверен граф зависимостей всех 48 манифестов:

- **`premium_client` — обратных зависимостей НЕТ**, ни один модуль на него не ссылается. Выбрасывается бесследно — и должен быть выброшен (см. §1: отправляет ИНН и контакты наружу).
- **`web_debranding`** ← от него зависит только `portal_debranding` ← от которого только `website_debranding`. Вся тройка дебрендинга отсекается одним куском. `pos_debranding` независим, тоже выбрасывается.
- **Стек `l10n_ru_*`, docx-отчёты, договоры, MRP-модули на дебрендинг не опираются вообще.**

Итог: **44 модуля из 48 работают без OPL-1/OEEL-1.** Цена отказа — логотипы и
надписи «Odoo» в интерфейсе, на портале и в POS. Для внутренней заводской
системы это косметика, не функциональность.

### Реально ограничивающая лицензия — AGPL-3, а не OPL-1

`l10n_ru_doc/__manifest__.py:45` → `'license': 'AGPL-3'`. А `l10n_ru_doc` —
это **ядро первички** (5 131 строка: ТОРГ-12, счёт по форме 1С, счёт-фактура,
акт выполненных работ, УПД), и от него зависят `l10n_ru_act_rev`,
`l10n_ru_advance_payments`, `l10n_ru_upd_xml`,
`account_bank_statement_1c_import`, `dadata_connector`.

AGPL-3 — копилефт с сетевым пунктом: если доработанная версия доступна
пользователям по сети, исходники доработок надо отдавать по запросу. Для
внутреннего ERP завода (пользователи = сотрудники) практически не жмёт. Но это
жёсткое ограничение, если завод когда-нибудь захочет продавать свою сборку
или отдавать её клиентам как сервис. `base_tier_validation` — тоже AGPL-3.

---

## 4. Технический риск: насколько глубоко лезут в Odoo

Глубоко. Это не аккуратный слой поверх API, а вмешательство во внутренности.

### Патч корневой модели ORM

`_inherit = "base"` — самый глубокий уровень вмешательства, какой бывает
в Odoo. Три модуля:

- `web_debranding/models/base.py:12`
- `dms/models/base.py:10`
- `translation_helper/models/base.py:9`

### JS-монкипатчинг: 27 вызовов `patch()` в 19 файлах

Через `@web/core/utils/patch` патчатся прототипы каркаса веб-клиента:

| Что патчится | Где |
|---|---|
| `WebClient.prototype` | `web_debranding/static/src/js/base.js:15`, `translation_helper/static/src/webclient.js:9` |
| `Dialog.prototype` | `web_debranding/static/src/js/dialog.js:14` |
| `FormController.prototype` | `docx_report/static/src/js/contract_docx_print_menu.js:33` |
| `ListController` / `KanbanController` | `dms/static/src/js/views/file_list_view.esm.js:19`, `file_kanban_view.esm.js:19` |
| `NavBar`, `NavBar.prototype`, `DropdownItem`, `FormLabel` | `translation_helper/static/src/menus/dropdown.js:14,21,40,47`, `field_translation.js:10,18` |
| mail-стор: `Store.prototype`, `Thread.prototype`, `Composer.prototype`, `Message.prototype` | `tier_communications/static/src/components/tier_mailbox_store_patch.js:11,43`, `message_composer_channels.js:16,47`, `message_channel_tag.js:15` |
| `SearchableSetting.prototype`, `ResConfigDevTool.prototype`, `TranslationDialog.prototype`, `viewHookModule`, `envModule` | `web_debranding/static/src/js/field_upgrade.js:7`, `translation_helper/static/src/settings/res_config_dev_tool.js:7`, `fields/translation_dialog.js:17`, `redefine_view_hook.js:9`, `env.js:7` |

### `t-inherit` в шаблоны ядра — 18 целей

`web.ListRenderer`, `web.KanbanRenderer`, `web.KanbanView.Buttons` (×2),
`web.ListView.Buttons`, `web.NavBar.SectionsMenu`,
`web.NavBar.SectionsMenu.Dropdown.MenuSlot`, `web.FormLabel`,
`web.DropdownItem`, `web.BinaryField`, `web.SearchableSetting`,
`mail.Message`, `mail.Composer`, `point_of_sale.Navbar`.

Это именно те части, которые Odoo переписывает каждый мажор.

### 271 xpath, часть — по хрупким узлам

Самые переопределяемые формы ядра: `base.view_users_form` (5),
`base.view_partner_form` (5), `account.view_move_form` (5),
`project.view_task_form2` (4), `base.act_report_xml_view` (4),
`base_setup.res_config_settings_view_form` (4), `sale.view_order_form` (3).

Пример хрупкости: `web_debranding/models/res_config_settings.py:56` жёстко
ищет `"//div[div[field[@widget='upgrade_boolean']]]"` — сломается от любой
перевёрстки этого блока настроек.

### Переопределение приватных методов ядра

| Метод | Частота / где |
|---|---|
| `_get_report_values` | 9 раз |
| `_print_report` | 6 раз |
| `_run_wkhtmltopdf` | `report_weasyprint/models/ir_actions_report_weasy.py:36` — **подменяет движок PDF целиком** |
| `_post_pdf` | `docx_report_generation/models/ir_actions_report.py:210`, `pdf_report_from_docx/models/ir_actions_report.py:138` |
| `_get_pdf_from_office` | `docx_report_generation/models/ir_actions_report.py:455`, `pdf_report_from_docx/...:192` |
| `_render_qweb_pdf` | `l10n_ru_act_rev/controllers/controllers.py:86`, `mklab_dms_document/models/document.py:77` |
| `_to_store_defaults` | `tier_communications/models/mail_message.py:18-20`, `tier_channel_tag.py:25` |

### Импорты непубличного API

`from odoo.addons.web.controllers.utils` (2), `odoo.addons.web.controllers.report` (2),
`odoo.addons.web.controllers.binary`, `odoo.addons.mail.tools.discuss` (3),
`odoo.addons.base.models.ir_model`, `odoo.addons.portal.controllers.portal`,
`from odoo.release`, `from odoo.modules.module`, а также
**`from odoo.osv.expression` (3 раза)** — в Odoo 18+ это уже вытесняется
`odoo.fields.Domain`.

### Прямой SQL — 8 мест

`directive_layer/models/directive_mixin.py`, `dms/models/dms_file.py`,
`base_tier_validation/models/tier_validation.py`,
`translation_helper/models/translation_service.py`,
`translation_helper/wizards/translation_helper_wizard.py`,
`web_debranding/controllers/main.py`. Ломается от смены схемы БД.

### Что вероятнее всего сломается на Odoo 20 (по убыванию)

1. **Весь JS-слой.** 27 `patch()` по прототипам OWL + 18 `t-inherit` в шаблоны `web`/`mail`. Odoo переписывает веб-клиент и Discuss каждый мажор. `translation_helper` (11 патчей: WebClient, NavBar, FormLabel, DropdownItem, view_hook, env) и `tier_communications` (mail Store/Thread/Composer/Message) — кандидаты на **полную переделку**, а не правку.
2. **Отчётный конвейер — и это самое болезненное для завода.** `_run_wkhtmltopdf` в Odoo 19 ещё жив (`odoo/odoo/addons/base/models/ir_actions_report.py:41,514`), но Odoo уходит от wkhtmltopdf. В момент замены движка встанут `report_weasyprint`, `docx_report_generation`, `pdf_report_from_docx` — а с ними **вся печать первички: ТОРГ-12, счета, УПД, акты, договоры**.
3. **`_to_store_defaults`** — mail-стор переименовывается почти каждый релиз.
4. **271 xpath** по формам `res.users`/`res.partner`/`account.move`/`sale.order` — типовой «тихий» падёж миграции: модуль не ставится с `Element ... cannot be located`.
5. **`_inherit = "base"` × 3** — при изменении контракта базовой модели отваливаются сразу три модуля, включая `dms` (8 836 строк, крупнейший в паке).
6. **Отсутствие `migrations/` у 47 из 48** — апгрейд данных писать самому.

### Дефекты, видимые уже сейчас, до Odoo 20

- **`mklab_mrp_filters` не установится на Odoo 19 Community.** `mklab_mrp_filters/__manifest__.py:4` → `'depends': ['mrp_workorder', 'sale_mrp']`. Модуль `mrp_workorder` — **Odoo Enterprise**, в Community его нет: в `odoo/addons/` есть `mrp`, `mrp_account`, `mrp_landed_costs`, `mrp_product_expiry`, `mrp_repair`, `mrp_subcontracting*`, но **`mrp_workorder` отсутствует**. Это ровно производственный модуль — то, за чем завод и приходит. Из двух производственных модулей пака на CE доступен только один (`mklab_forecast_mrp`).
- **Ссылка на несуществующий модуль `gotenberg`.** `docx_report_generation/models/ir_actions_report.py:19` → `from odoo.addons.gotenberg.service.utils import (...)`. Модуля `gotenberg` нет ни в паке (48 папок), ни в Odoo 19 CE, и в `depends` он не объявлен. `pdf_report_from_docx` при этом ожидает внешний сервис Gotenberg по `gotenberg.server.url` (дефолт `http://localhost:3000`, `pdf_report_from_docx/models/ir_actions_report.py:25`) — ещё один контейнер в стек.
- **Нарушение конвенций Odoo в схеме БД.** `l10n_ru_doc/views/tax.xml:9` добавляет в `account.tax` поле `invisiblePF` — camelCase в именах полей Odoo не принят. Мелочь, но показатель уровня ревью.
- **Конфиг-заглушки в продакшн-данных.** `premium_client/data/system_parameters.xml:5-14` — `http://localhost:8069/newlead/`, токен `default-premium-token-2024`.

---

## 5. Что если заглохнет

48 модулей нельзя рассматривать как один объект. Пак чётко делится на три
части, и это меняет ответ.

### Критично — тащить придётся, альтернативы нет

| Модуль | Строк | Что даёт |
|---|---|---|
| `l10n_ru_doc` | 5 131 | ТОРГ-12, счёт по форме 1С, счёт-фактура, акт выполненных работ, УПД (+ УПД без печатей) |
| `l10n_ru_contract` | 4 654 | договоры, виды договоров, печать |
| `l10n_ru_act_rev` | 2 704 | акт сверки |
| `l10n_ru_upd_xml` | 1 495 | УПД в XML, формат 5.01 (для ЭДО) |
| `docx_report` | 1 613 | docx-шаблоны |
| `l10n_ru_contract_sale` | 1 468 | договоры под продажи |
| `l10n_ru_contract_account` | 1 013 | договоры под счета |
| `docx_report_generation` | 858 | печать отчётов из docx-шаблонов |
| `l10n_ru_attorney` | 695 | доверенность на получение ТМЦ |
| `custom_report_field` | 439 | вычисляемые поля для отчётов |
| `report_monetary_helpers` | 178 | суммы прописью |
| `l10n_ru_base` | 143 | базовые настройки локализации |
| `report_weasyprint` | 108 | нужен `l10n_ru_contract` |
| `l10n_ru_contract_purchase` / `_templates` | 75 / 71 | договоры закупки, привязка docx |

**Итого нужное заводу ядро: ~20 тыс. строк.** Ключевое: в этом ядре
**один JS-патч** (`docx_report/static/src/js/contract_docx_print_menu.js:33`),
нет `_inherit = "base"`, нет прямого SQL, нет `_to_store_defaults`. Привязка
идёт к `_get_report_values`, QWeb и `docxtpl` — вещам куда более стабильным,
чем веб-клиент. Плюс у большинства этих модулей есть тесты.

Поддерживать это одним разработчиком **реально**: раз в год при апгрейде Odoo
пересобрать xpath и проверить QWeb/docx-шаблоны. Печатные формы меняются от
законодательства, а не от Odoo.

### Бросить сразу, без потерь для завода

`premium_client` (539 — витрина услуг + отправка ИНН наружу),
`web_debranding` (923) + `portal_debranding` (100) + `website_debranding` (95) +
`pos_debranding` (114) — косметика и лицензионный риск;
`dms` (8 836) + `mklab_dms_document` (938) — документооборот, дублируется
вложениями Odoo; `base_tier_validation` (4 451) — согласования, в Odoo есть
свои правила; `tier_communications` (1 906) + `tier_communications_matrix` (375) —
своя почта/Matrix, заводу не нужно и это самый хрупкий JS;
`directive_layer` (1 969) + `directive_test` (501) — специфика MK.Lab;
`ruodoo_demo_data` (1 995); `translation_helper` (1 673) — при русском
интерфейсе из `.po` не нужен, а это 11 патчей веб-клиента;
`base_user_role` (1 361); `mklab_base_indicators` (979) + `_extended` (501) +
`_report` (260) + `mklab_project_task_indicators` (382) — сметы по задачам
проектов, не производство; `account_move_templates` (640) + `_invoice` (265);
`access_restricted` (444) + `access_apps` (206) + `access_settings_menu` (76) +
`ir_rule_protected` (147); `pdf_report_from_docx` (248) — требует внешний
Gotenberg; `tests` (30); `ruodoo_setup_all` (35).

**Отбрасывается ~30 тыс. строк — больше половины пака.** И вместе с ними
уходит почти весь глубокий монкипатчинг: `dms`, `translation_helper`,
`tier_communications`, `web_debranding` дают 18 из 19 файлов с `patch()`.

### Спорное — полезно, но не бесплатно

- `account_bank_statement_1c_import` (601) — импорт выписок 1С. Для завода ценно, зависит от `l10n_ru_doc`.
- `dadata_connector` (770) — автозаполнение контрагента по ИНН из DaData. Удобно, но зависит от внешнего платного API (`dadata==21.10.1`) и без него не работает.
- `mklab_forecast_mrp` (766) — прогноз и план производства по продажам, подбор BOM по наличию на складе. Единственный производственный модуль, доступный на CE.
- `mklab_mrp_filters` (124) — **на Community не встанет** (нужен Enterprise `mrp_workorder`).

### Ответ на вопрос

Поддерживать **все 48** силами одного разработчика — нереально: 54,7 тыс. строк,
27 JS-патчей, 271 xpath, три патча ORM-базы, ноль миграций.

Поддерживать **нужное заводу ядро из ~14 модулей / ~20 тыс. строк** — реально
и это обычная работа. Стратегия, если RuOdoo заглохнет: форкнуть эти 14
модулей в свой Git с нормальной историей, выбросить остальные 34, зафиксировать
версию Odoo и **не гнаться за мажорами** (Odoo LTS-подобный цикл позволяет
сидеть на релизе 2-3 года).

---

## 6. Сравнение риска: RuOdoo против «писать самому»

База сравнения — не «идеальная поддерживаемая локализация». Её для России нет
ни у кого, и это надо проговорить фактами.

### Российской локализации нет даже в самом Odoo

- В `odoo/addons/` — **231 модуль `l10n_*`**. Между `l10n_ro*` и `l10n_rs*` Россия **отсутствует**: есть `l10n_re`, `l10n_ro`, `l10n_ro_cpv_code`, `l10n_ro_edi`, `l10n_ro_edi_stock`, `l10n_ro_edi_stock_batch`, `l10n_rs`, `l10n_rs_edi`, `l10n_rw` — `l10n_ru` нет.
- По всему дереву Odoo: `find odoo -type d -name 'l10n_ru*'` → **пусто**.
- **RuOdoo плана счетов тоже не даёт**: `grep -rl 'chart_template\|account.chart.template'` по всем 48 модулям → **ни одного совпадения**.
- И при этом **документация пака ссылается на несуществующий модуль**: `ruodoo_demo_data/README.md:68` — «Установить российскую локализацию: `l10n_ru` (активирует RUB, создаёт план счетов)». Такого модуля нет ни в Odoo 19 CE, ни в паке. Демо-данные написаны в расчёте на то, чего нет.

Это надо понимать точно: **RuOdoo — это печатные формы и договоры, а не
бухгалтерия по РСБУ.** Проверено grep-ом по всему паку — **0 упоминаний**:
Диадок, СБИС, Контур, ФСБУ, маркировка/Честный знак, ЕГАИС, Меркурий,
зарплата/payroll, ФНС, СЗВ, РСВ, 6-НДФЛ, ОКОФ, Росстат. «ЭДО» встречается
3 раза — и то как подпись к кнопке (`l10n_ru_base/views/res_config_settings_views.xml:32`,
«Формирование УПД для ЭДО») и как категория в витрине услуг `premium_client`.

### Предметно: что даётся готовым, а что пишется с нуля

| Что нужно заводу | RuOdoo | ERPNext / Carbon |
|---|---|---|
| ТОРГ-12, счёт по форме 1С, счёт-фактура, акт, УПД | `l10n_ru_doc`, 5 131 стр + 6 docx-шаблонов, с тестами | писать с нуля |
| Договоры + виды + печать (продажи/закупки) | `l10n_ru_contract*`, ~7 300 стр | писать с нуля |
| Акт сверки | `l10n_ru_act_rev`, 2 704 стр | писать с нуля |
| УПД в XML 5.01 (для ЭДО) | `l10n_ru_upd_xml`, 1 495 стр | писать с нуля |
| Доверенность на ТМЦ | `l10n_ru_attorney`, 695 стр | писать с нуля |
| Суммы прописью в RUB | `report_monetary_helpers` + `pytils`/`num2words` | писать с нуля |
| DOCX-шаблоны отчётов (бухгалтер правит в Word) | `docx_report_generation` + `docxtpl` | нет — только HTML/Jinja-print |
| Импорт банковских выписок 1С | `account_bank_statement_1c_import`, 601 стр | писать с нуля |
| Контрагент по ИНН (DaData) | `dadata_connector`, 770 стр | писать с нуля |
| Прогноз/план производства | `mklab_forecast_mrp`, 766 стр | писать с нуля |
| Русский план счетов / РСБУ-отчётность | **нет** | **нет** |
| ФСБУ, ЭДО-операторы, маркировка/ЧЗ, ЕГАИС, ЗУП/6-НДФЛ/РСВ, Росстат | **нет** | **нет** |

### Вывод

Риск RuOdoo надо формулировать честно и узко: это **не «система встанет»**, а
**«при мажорном апгрейде Odoo половина пака потребует ремонта, и починить её
будет некому»** — потому что `maintainer` не указан ни у одного модуля из 48,
публичного issue-трекера нет, история сквошена в один коммит бота, а changelog
насчитывает 16 записей за один апрель 2026 на 48 модулей.

Это риск **стоимости обслуживания**, и он управляем ровно тем же способом, каким
Антон уже управляет ERPNext: взять 14 модулей первички и договоров (~20 тыс.
строк, один JS-патч), выбросить остальные 34 (~30 тыс. строк, включая 18 из 19
файлов с монкипатчингом), держать форк в своём Git, зафиксировать версию Odoo.

В сравнении с ERPNext/Carbon арифметика такая: **на ~20 тыс. строк меньше
собственного кода при том же остаточном риске «поддерживаем сами»**. Причём
это именно та работа, которую Антон сейчас и делает руками в ERPNext — свои
переводы (~14 тыс. строк), своя тема `saas_theme`, свой CRM 2.0, свои отчёты
доборки. RuOdoo отдаёт готовым тот пласт, который в ERPNext пришлось бы писать
следующим.

**Контр-аргумент, который надо назвать прямо:** в ERPNext локализация пишется
**под свой контроль** — не будет сюрприза «модуль патчит `base` и
`WebClient.prototype`, а автора не найти». RuOdoo меняет «писать самому» на
«поддерживать чужой код, который лезет в приватные внутренности». Для
20-тысячного ядра печатных форм — обмен выгодный. Для полного пака из 48
модулей — нет.

**Условия, при которых опираться на RuOdoo допустимо:**

1. Ставить только ядро первички и договоров (~14 модулей), а не `ruodoo_setup_all` (который к тому же помечен версией `17.0.1.0.0`).
2. Не ставить `premium_client` (отправляет ИНН и контакты на внешний endpoint) и не ставить дебрендинг (`web_debranding` — чужой платный OPL-1 модуль за 300 €).
3. Запросить у MK.Lab явную лицензию на 18 модулей, где поля `license` нет — в первую очередь на `l10n_ru_contract*` и `l10n_ru_upd_xml`. Отсутствие ответа — сигнал сам по себе.
4. Форк в своём Git с первого дня. Публичное зеркало с одним коммитом бота — не основа для эксплуатации.
5. Бухгалтерию по РСБУ в план не закладывать: её здесь нет и не будет. Если она останется в 1С — риск RuOdoo сжимается до печатных форм, то есть до самой стабильной части пака.
