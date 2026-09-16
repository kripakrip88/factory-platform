# RuOdoo: российские и учётные модули (21 шт.) — разбор по файлам

Релиз RuOdoo 2026-09-14 под Odoo 19. База: `/scratchpad/ruodoo`, ядро Odoo 19 Community: `/scratchpad/odoo`.
Оценка с позиции завода металлоконструкций (Хабаровск), рассматривающего замену ERPNext.

---

## 0. Первое, что нужно знать (два вывода уровня «стоп»)

**0.1. Плана счетов РФ нет вообще.**
В Odoo 19 Community модуля `l10n_ru` не существует (`ls odoo/addons | grep l10n_ru` — пусто; есть `l10n_latam_base`, `l10n_latam_check`, десятки других стран, но не Россия).
В RuOdoo `account.chart.template` / `_get_ru_template_data` тоже нигде не определяются — поиск по всему репозиторию даёт только строки в `.po`-файлах переводов (`ruodoo/translation_helper/translations/ru/account.po`).
То есть: 01/10/20/26/41/43/51/60/62/68/69/76/90/99 придётся заводить руками или писать свой `l10n_ru`-шаблон. Ни бухсправок, ни регламентированной отчётности (баланс, ф.2, декларация НДС, РСВ, 6-НДФЛ) в комплекте нет и близко.

**0.2. Российские модули — платные, с проверкой лицензии в коде.**
`ruodoo/l10n_ru_base/models/res_config_settings.py:31-42`: при включении любого из
`module_l10n_ru_act_rev`, `module_l10n_ru_contract`, `module_l10n_ru_upd_xml`, `module_l10n_ru_doc`, `module_l10n_ru_attorney`, `module_l10n_ru_advance_payments`
проверяется наличие модуля в `ir.module.module`, и если его нет — `UserError("Обратитесь в тех.поддержку для получения лицензии для следующих модулей: …")`.
Там же (`res_config_settings.py:28-30`) жёсткая привязка: если `company.country_id.code != 'RU'` — включение блокируется.
Формально в манифестах лицензии LGPL-3/AGPL-3 (см. таблицу лицензий ниже), но продукт упакован как коммерческий: поставка идёт от MK.Lab / inf-centre.ru, часть модулей (напр. `premium_client`) — с проверкой подписки.

---

## 1. Лицензии и версии (факт из манифестов)

| Модуль | license | version |
|---|---|---|
| l10n_ru_base | LGPL-3 | 19.0.2025.11.11 |
| l10n_ru_doc | **AGPL-3** | 19.0.2025.11.11 |
| l10n_ru_upd_xml | не указана → LGPL-3 по умолчанию | 19.0.2025.12.11 |
| l10n_ru_act_rev | не указана | **0.1** |
| l10n_ru_advance_payments | не указана | 19.0.2025.06.06 |
| l10n_ru_attorney | не указана | **0.1** |
| l10n_ru_contract / _account / _purchase / _sale / _templates | не указана | 19.0.1.0.0 |
| account_bank_statement_1c_import | не указана | 19.0.0.1 |
| account_move_templates / _invoice | LGPL-3 | 19.0.1.0.0 |
| dadata_connector | не указана | 19.0.2025.12.03 |
| report_monetary_helpers | LGPL-3 | 19.0.2025.11.11 |
| report_weasyprint | LGPL-3 | 19.0.1.0.0 |
| docx_report | LGPL-3 | 19.0.1.0.0 |
| docx_report_generation | LGPL-3 | 19.0.2025.11.11 |
| pdf_report_from_docx | LGPL-3 | 19.0.1.0.0 |
| custom_report_field | LGPL-3 | 19.0.2025.11.11 |

`l10n_ru_doc` под AGPL-3 — значит любые ваши доработки этого модуля, если он останется частью системы, доступной по сети, формально подпадают под AGPL. Юридически это надо проговорить с поставщиком.

Авторство неоднородное: MK.Lab (основное), CodeUP (`l10n_ru_doc`), **RYDLAB** (`report_monetary_helpers`, `custom_report_field`, `docx_report_generation` — это сторонние OCA-подобные модули), «Custom» (`pdf_report_from_docx`).

Внешние Python-зависимости (`ruodoo/requirements.txt`): `pytils`, `num2words`, `docxtpl>=0.20.2`, `docxcompose`, `python-docx>=1.1.2`, `weasyprint`, `dadata==21.10.1`, `beautifulsoup4`, `lxml`, `pymorphy2`, `matplotlib`, `networkx`, `openupgradelib`, `siphashc`.

---

## 2. l10n_ru_base — «выключатель» локализации

- Назначение: единая страница настроек «Российская локализация» с чекбоксами установки остальных RU-модулей.
- Зависимости: `[]` (пустые).
- Содержимое: один файл `models/res_config_settings.py` (6 булевых `module_*` полей) + `views/res_config_settings_views.xml`. Моделей, полей документов, отчётов не добавляет.
- Побочный эффект: как описано в §0.2 — гейт лицензии и страны.

---

## 3. l10n_ru_doc — первичные печатные формы (ПОДРОБНО)

Зависимости: `base, sale, account, sale_stock, uom, l10n_ru_base, docx_report_generation`; python: `pytils`.

### 3.1. Какие формы есть в виде QWeb-шаблонов

| Форма | Файл | Строк | Абстрактная модель |
|---|---|---|---|
| Товарная накладная ТОРГ-12 | `l10n_ru_doc/report/report_bill.xml` | 758 | `report.l10n_ru_doc.report_bill` (`report/report_bill.py:5`) |
| Счёт-фактура (пост. 1137) | `report/report_invoice.xml` | 329 | `report.l10n_ru_doc.report_invoice` |
| Акт выполненных работ | `report/report_act.xml` | 203 | `report.l10n_ru_doc.report_act` |
| УПД (с печатями) | `report/report_upd.xml` | 1108 | `report.l10n_ru_doc.report_upd` (`report/report_upd.py:5`) |
| УПД без печатей | `report/report_updn.xml` | 1177 | `report.l10n_ru_doc.report_updn` (`report/report_upd.py:15`) |
| Счёт на оплату «по форме 1С» | `report/report_order.xml` (sale.order) | 336 | `report.l10n_ru_doc.report_order` |

### 3.2. ВАЖНО: из шести форм кнопка печати есть только у трёх

В `l10n_ru_doc/report/l10n_ru_doc_report.xml` активны только три `ir.actions.report`:
- строка **35** — «Счет по форме 1С» (`sale.order`, A4 portrait);
- строка **131** — «Универсальный передаточный документ(УПД)» (`account.move`, A4 landscape);
- строка **155** — «УПД без печатей».

**Закомментированы** (строки 47, 59, 71, 83, 95, 107, 119, 143, 167):
- «Счет-фактура» (`account_invoices_new`),
- **«Товарная накладная (ТОРГ-12)»** (`report_account_invoice_bill_new`),
- «Акт выполненных работ» (`report_account_invoice_act_new`),
- и все DOCX-двойники.

То есть заявленная в манифесте ТОРГ-12 из коробки в меню «Печать» **не появится** — шаблон есть, action’а нет. Чинится 5 минутами работы (раскомментировать или создать запись `ir.actions.report` в Настройках → Технические → Отчёты), но «из коробки» — нет. Часть DOCX-двойников переехала в модуль `docx_report` (см. §9.2), где есть УПД, УПД без печатей, Счёт 1С и Договор — **но не ТОРГ-12 и не Акт**.

### 3.3. Насколько формы полные

ТОРГ-12 (`report_bill.xml`) — полная унифицированная форма: гриф «Утверждена постановлением Госкомстата России 25.12.98 №132», ОКУД 0330212, блоки Грузоотправитель/Грузополучатель/Поставщик/Плательщик с ОКПО, «Основание (договор, заказ-наряд) номер/дата», «Транспортная накладная номер/дата», табличная часть, «Всего мест», «Масса груза (брутто) прописью», «Приложение (паспорта, сертификаты) на … листах», «Отпуск груза разрешил / Главный (старший) бухгалтер / Отпуск груза произвёл / Груз получил грузополучатель», М.П. — всё есть. Для металлоконструкций это рабочая форма.

Счёт-фактура и УПД — с дырами, помеченными самими авторами как `TO DO` (это буквальные комментарии в шаблонах):
- `report_upd.xml:739` — гр. 1а «Код вида товара» не заполняется;
- `report_upd.xml:741` — «Код ЕдИзм» (ОКЕИ) в печатной форме не подставляется;
- `report_upd.xml:751` — «Сумма акциза» — пусто;
- `report_upd.xml:753` — «Ставка НДС» — пусто (!);
- `report_upd.xml:757-758` — страна происхождения жёстко «643 / РФ»;
- `report_upd.xml:759` — «Регистрационный номер декларации на товары» — пусто;
- графа «подлежащего прослеживаемости» присутствует как заголовок (`report_upd.xml:691`), но данными не наполняется;
- `report_invoice.xml:109,124,127,213,218-224` — «Номер исправления», «К платёжно-расчётному документу», код ЕИ, акциз, страна, ГТД — все `TO DO`;
- `report_act.xml:138` — «Сумма НДС» в акте помечена `TO DO`;
- `report_order.xml:251` — то же в счёте 1С.

Для завода металлоконструкций (продукция российская, без акциза, без прослеживаемости) большинство этих дыр не критично, **кроме «Ставка НДС» в УПД** — это обязательная графа 7. Надо проверять на живом документе.

### 3.4. Что добавляет в данные

- `res.partner` (`models/res_partner.py`): `inn` (related на `vat`), `kpp`(9), `okpo`(14), `ogrn`, `facsimile` (Binary — подпись), `stamp` (Binary — печать), `type += director/accountant`.
- `res.company` (`models/res_company.py`): `inn/kpp/okpo` (related на partner), `chief_id`, `accountant_id` (res.users), `print_facsimile`, `print_stamp`, `stamp`, `print_anywhere`.
- `res.bank` / `res.partner.bank` (`models/res_bank.py`): `corr_acc`, `bank_corr_acc` + onchange подтягивает БИК и корсчёт.
- `uom.uom`: `kod` («Код единицы измерения»).
- `account.tax`: `invisiblePF` («Не видно в ПФ») — чтобы прятать технические налоги из печатных форм.
- `product.product`: `kod_tnved`.
- `account.move` (`models/account_invoice.py:6-15`): `kladov` (ответственный за передачу), `gruzopol`, `gruzootpr`, `transport`, `osnovanie`, `payment_text/payment_num/payment_date` (вычисляемые из платежей), `only_service`. Плюс методы `get_delivery_doc_name()`, `get_delivery_doc_date()` (`:70,:89`) — тянут номер/дату связанной отгрузки из `stock.picking`.
- `account.move.line` (`models/account_move_line.py`): `price_total_pf` — итог по строке **без** налогов, помеченных `invisiblePF`.
- `sale.order` (`models/sale.py`): `amount_total_words` (сумма прописью через pytils), `chief_initials`, `accountant_initials`.
- Хелпер `report_helper.py` — класс `QWebHelper` с `img()` (base64 в `<img>`), `numer()`, обёртками `pytils.numeral`/`pytils.dt` (сумма и дата прописью). Доступен в шаблонах как `helper`.
- `views/l10n_ru_doc_data.xml` — при установке форсирует установку русского языка (`base.language.install`, `overwrite=1`).

---

## 4. l10n_ru_upd_xml — УПД в XML (ПОДРОБНО, ключевой модуль для ЭДО)

Зависимости: `web, base, account, account_payment, l10n_ru_doc, l10n_ru_base, uom`; python: `lxml`.

### 4.1. Как работает

1. На форме счёта клиента появляется кнопка **«Печать УПД в xml-формате»** — `views/view_account_move.xml:9-14`, видна только при `state == 'posted'` и `move_type in ('out_invoice','out_refund')`.
2. Кнопка вызывает `account.move.print_upd()` — `models/account_move.py:25-30`.
3. Перед генерацией — валидатор `check_correct_upd()` (`models/account_move.py:32-207`, ~175 строк). Проверяет ~40 условий и выдаёт единым текстом список отсутствующих реквизитов: ИНН/КПП/ОКПО/адрес/город компании и контрагента, ФИО+должность руководителя, ФИО ИП (при ИНН из 12 цифр), ID EDI компании и контрагента, грузоотправитель/грузополучатель с полным набором, наличие связанных отгрузок, договор, ответственный за передачу и его должность, **код ОКЕИ у каждой единицы измерения**, цена и количество в каждой строке. Это, пожалуй, самая сильная часть модуля — не даст выгрузить мусор.
4. Рендер: `ir.actions.report` с новым типом `qweb-xml` (`models/ir_actions_report.py:7-9`), запись отчёта — `reports/report.xml:4` («УПД xml», модель `account.move`, шаблон `l10n_ru_upd_xml.demo_report_xml_view`).
5. Сам XML — QWeb-шаблон `reports/upd_report.xml` (343 строки), где теги ФНС записаны прямо по-русски (`<Файл>`, `<Документ>`, `<СвСчФакт>`, `<СвПрод>`, `<СвПокуп>`, `<ГрузОт>`, `<ТаблСчФакт>`, `<СведТов>`, `<ВсегоОпл>`, `<СвПродПер>`, `<Подписант>`).
6. Пост-обработка — `reports/report_report_xml_abstract.py:156-173`: pretty-print через `minidom`, затем `lxml.etree.tostring(..., encoding=ir_report.xml_encoding or "WINDOWS-1251", xml_declaration=True)`. То есть по умолчанию **windows-1251**, как и требует ФНС.
7. Выгрузка — контроллер `controllers/main.py:19-47` перехватывает `/report/xml/...`, `report_download` (`:49-91`) отдаёт файл браузером с именем из `print_report_name` = `object.edi`.

### 4.2. Соответствие требованиям ФНС — где расходится

| Требование | Факт |
|---|---|
| `ВерсФорм` | В манифесте написано «формат 5.01», в шаблоне — **`'5.03'`** (`reports/upd_report.xml:17`). Расхождение документации и кода; 5.03 — актуальнее, но проверять нужно по действующему приказу ФНС на дату внедрения. |
| `КНД` | `1115131` — верно (`:21`). |
| `Функция` | Жёстко `'СЧФДОП'` (`:22`). Вариантов `СЧФ` / `ДОП` / `СЧФДОП` на выбор нет. |
| **`СвУчДокОбор` / `СвОЭДОтпр`** | **Отсутствуют полностью.** В структуре файла ФНС между `<Файл>` и `<Документ>` обязателен блок сведений об участниках документооборота и операторе ЭДО. Его нет → файл не пройдёт XSD-валидацию ФНС и, скорее всего, будет отвергнут оператором ЭДО. |
| `ИдФайл` | Собирается как `edi + '_0_0_0_0_0_00'` (`:16`), где `edi` = `'ON_NSCHFDOPPR_2BM-' + ID_контрагента + '_' + ID_компании + '_' + sha1(номер)` (`models/account_move.py:22-24`). Формат имени файла ФНС (`ON_NSCHFDOPPR_<ИдПол>_<ИдОтпр>_<ГГГГММДД>_<GUID>`) соблюдён лишь приблизительно: вместо даты и GUID — sha1 и строка нулей. |
| Ставка НДС | Считается текстом в `:180-205`, налог берётся из строки; при отсутствии — `'без НДС'`. Приемлемо. |
| Сумма налога | `line_tax_amount = line.price_total - line.price_subtotal` (`:208`) — арифметика «в лоб», при нескольких налогах на строке или при налоге «не видно в ПФ» даст неверное значение. |
| Цена за единицу | `ЦенаТов = price_subtotal / quantity` (`:214`) — не `price_unit`. При скидке цена «размазывается»; для металла со скидками это разойдётся с бумажным УПД. |
| Страна происхождения | `<КрНаимСтрПр>Китай</КрНаимСтрПр>` — **жёстко зашито «Китай»** (`reports/upd_report.xml:227`) для товаров с `tracking == 'serial'`. Для хабаровского завода, выпускающего металлоконструкции в РФ, это прямая ошибка в документе. |
| Прослеживаемость / ДТ | `НомСредИдентТов`/`КИЗ` заполняется только из маркировки «Честный знак» (`lot.lot_id.cz_code_id.code_without_characters`, `:233`). Блока `СвДТ`/рег. номера декларации нет. |
| Акциз | Всегда `<БезАкциз>без акциза</БезАкциз>` (`:239-241`). Для металла — норм. |
| `Подписант` | Есть (`:305-339`), `СпосПодтПолном='1'` (руководитель), ФИО парсится разбиением `name` по пробелам. |
| **Электронная подпись** | **Нет.** Ни КриптоПро, ни ГОСТ Р 34.10, ни отсоединённой подписи (`.sig`), ни `<ЭЦП>`. Поиск `подпис|ЭЦП|sign` по модулю даёт только `<Подписант>` (реквизит ФИО, не криптография). |
| XSD-валидация | Поле `xsd_schema` объявлено (`models/ir_actions_report.py:10-16`) и выведено в форму отчёта (`views/ir_actions_report_view.xml:17`), **но в коде генерации ни разу не используется** — файл не проверяется против схемы. Валидация — только «ручная» через `check_correct_upd`. |
| Куда выгружается | Только в браузер пользователя (скачивание файла). Интеграции с Диадок/СБИС/Такском нет, `ir.attachment` не создаётся, отправки по API нет. Поля `edi` у company/partner называются «ID EDI … для Diadoc», но коннектора к Диадоку в комплекте **нет**. |

**Вывод по УПД-XML:** это заготовка «сформировать файл и отнести в веб-клиент оператора ЭДО вручную». Как готовое решение ЭДО — не годится: нет `СвУчДокОбор`, нет подписи, нет отправки, нет XSD-проверки, жёсткий «Китай» в стране происхождения. Доработка — реальная, но это работа программиста на несколько дней плюс тестирование у оператора.

Дополнительно модуль добавляет: `res.partner.edi/house/office/fias_id/last_name_IP/first_name_IP/middle_name_IP` (ФИО ИП вычисляется парсингом строки «ИП Иванов Иван Иванович» — `models/res_partner.py:17-35`), `res.users.last_name/first_name/second_name` (разбор ФИО по пробелам, `models/res_users.py`), **`uom.uom.okei`** («Код ОКЕИ» — обязателен для УПД), `account.move.line.uom_okei`, `res.company.edi/chief_id`.

---

## 5. l10n_ru_act_rev — акт сверки (ПОДРОБНО)

Зависимости: `account, portal, website, contacts, l10n_ru_doc, l10n_ru_contract, l10n_ru_base`. Версия `0.1`.

- Основа — переписанный OCA-отчёт «General Ledger»: визард `general.ledger.act_revise.wizard` (`wizard/general_ledger_wizard.py:15`, 897 строк, из них ~420 закомментированы), движок `report.l10n_ru_act_rev.general_ledger` (`report/general_ledger.py:11`, 1060 строк).
- Параметры визарда (`wizard/general_ledger_wizard.py:21-80`): `date_from`/`date_to`, `target_move` («Все проведённые проводки» / «Все проводки»), `company_id`, `partner_ids`, `account_ids`, `account_journal_ids`, `cost_center_ids`, `hide_account_at_0`, `receivable_accounts_only`, `payable_accounts_only`, `foreign_currency`, `centralize`, `grouped_by` (partners/taxes).
- Печатная форма — `report/general_ledger.xml`: двусторонний **акт сверки взаимных расчётов**: «между … по договору № … от …», «Мы, нижеподписавшиеся, … составили данный акт сверки в том, что состояние взаимных расчётов по данным учёта следующее» (`:134`), две симметричные колонки «По данным <нашей компании>, руб» / «По данным <контрагента>, руб» с Дата / Документ / Дебет / Кредит, строки **Сальдо начальное → Обороты за период → Сальдо конечное**, итог «задолженность в пользу … руб. (прописью)», подписи «Директор», М.П. с двух сторон. Это полноценный привычный российский акт сверки.
- `ir.actions.report` — `report/general_ledger.xml:258` («Акт сверки», модель — визард, `qweb-pdf`, имя файла `'Акт сверки - %s' % object.get_report_filename()`).
- Портал: кнопка «Печатать акт сверки» в кабинете клиента (`views/portal_templates.xml:6-8`) + контроллер `/my/act_revise/<string:act>` (`controllers/controllers.py:7-34`). **Баг:** маршрут объявлен с параметром `<string:act>`, а метод — `def print_report(self)` без этого аргумента → при переходе будет `TypeError`. Портальная кнопка в текущем виде не работает.
- Модель `account.account` расширена (`models/account_account.py`, 7 строк) — вероятно флаг для группировки.

**Оборотно-сальдовая ведомость (ОСВ) — НЕТ.** Поиск «Оборотно» по всему репозиторию RuOdoo — ноль совпадений. Отдельной формы ОСВ (ни сводной, ни по счёту) нет ни здесь, ни в других 48 модулях. Есть только стандартные отчёты Odoo (Trial Balance / General Ledger), которые по виду и составу колонок на российскую ОСВ не похожи.

---

## 6. l10n_ru_advance_payments — авансовые счета

Зависимости: `account, sale, l10n_ru_contract, l10n_ru_doc, l10n_latam_check`; python: `pytils`. (`l10n_latam_check` — стандартный модуль Odoo 19, есть в `odoo/addons/l10n_latam_check`.)

- Новые модели: **`order.prepaid`** (`models/order_prepaid.py:4`) — «Авансовые платежи», с mail.thread; и `order.prepaid.line` (`models/order_prepaid_line.py:5`).
- Поля `order.prepaid`: `partner_id`, `sale_order_id`, `advance_type` (Исходящий/Входящий), `invoice_date`, `invoice_date_due`, `payment_terms`, `state`, `currency_id`, `partner_bank_id`, `amount`, `amount_sum_line`, `amount_residual`, `all_total`, `payment_state` (Не оплачен/…), `payment_line_ids` (`account.payment`), `payment_amount`, `prepaid_line`.
- Строка: `product_id`, `account_id`, `quantity`, `product_uom_id`, `price_unit`, `tax_ids`, `analytic_distribution`, `sale_ids` (связь со строками заказа), `price_subtotal`, `price_total`.
- Визард `wizard/account_payment_register_prepaid.py` — регистрация платежа по авансовому счёту.
- Отчёты (`report/order_prepaid.xml:18,32`): «Счет по форме 1С» и «Счет» для модели `order.prepaid`.
- Смысл: отдельный документ «счёт на аванс», не являющийся `account.move`, чтобы не плодить черновики счетов в бухгалтерии. Для завода с предоплатой 50/50 — потенциально полезно, но это **параллельный контур**, не связанный с НДС с авансов (сч. 76.АВ) — никаких проводок по авансовому НДС модуль не делает.

---

## 7. l10n_ru_attorney — доверенность на получение ТМЦ

Зависимости: `base, account, sale, purchase, hr, l10n_ru_base`. Версия `0.1`.

- Модель **`base.consent`** (`models/base_consent.py:8`): `name` (автонумерация через `ir.sequence` код `base.consent`, последовательность объявлена в `views/base_consent_views.xml:53`), `date_from` («Дата выдачи»), `date_to` («Действительна по», по умолчанию +180 дней), `partner_id` (обязательно), `employee_id` → `hr.employee` (обязательно), `purchaseorder_id` → `purchase.order` (домен по партнёру), `company_id`.
- `hr.employee` += `inn`, `pass_kem` («Кем выдан паспорт»), `pass_date`.
- `purchase.order` += `consent_id`.
- Печать: `report/consent_report.xml` — «Доверенность», `qweb-pdf`, A4 portrait, содержит дату выдачи, срок действия, наименование и адрес предприятия, таблицу «Наименование товаров (работ, услуг) / Ед. изм. / Количество», подписи «Руководитель предприятия» и «Гл. бухгалтер».
- **Это не унифицированная форма М-2/М-2а**: нет отрывного корешка, нет «образец подписи лица, получившего доверенность», нет паспортных данных в бланке (поля на сотруднике есть, в шаблоне не выведены). Поиск «М-2 / корешок / образец подписи» по модулю — ноль совпадений. Для склада металла форма «в свободном виде» обычно проходит, но банк/перевозчик могут потребовать М-2.
- Из коробки печать спрятана: в описании манифеста прямо сказано «Меню Настройки → Техническое → Отчёты, находим l10n_ru_attorney и добавляем в меню Печать».

---

## 8. Блок «Договоры» (5 модулей)

### 8.1. l10n_ru_contract — ядро
Зависимости: `base, mail, l10n_ru_base, report_weasyprint`; python: `weasyprint`.

Модель **`partner.contract.customer`** (`models/partner_contract_customer.py:7`, наследует `mail.thread`, `mail.activity.mixin`, `mail.render.mixin`):
`name` («Номер»), `date_start`/`date_end`, `partner_id`, `partner_type` (селекция), `company_id`, `profile_id` → `contract.profile` («Вид договора», обязательно), `state` (черновик/на согласовании/подтверждён), `stamp` («Печать и подпись»), `signed` («Договор подписан»), `lines_ids` → `contract.line` («Пункты договора»: `sequence`, `name` «Номер пункта», `punct` — HTML-текст), `is_template` + `copy_from` (шаблоны договоров), `director_name_partner`, `director_name_company`, `contract_header` (Html) + `contract_header_template_id` + `use_custom_contract_header`, `possible_partner_ids`.
Методы: `action_set_on_approval`, `action_confirm`, `action_reset_to_draft`, `copy_it`, `generate_contract_header`, `_render_header_qweb` (`models/partner_contract_customer.py:141`).

Другие модели: `contract.profile` («Вид договора»), `contract.day` («День» — для графиков доставки/отгрузки), `contract.allowed.profiles` (какие виды договоров можно держать одновременно), `contract.line`.
`res.partner` += `ogrn`, `okpo`, `inn`, `kpp`, `passport`, `pol` («Пол»), `contract_count`, `type += director`.
`res.company` += `inn/kpp/okpo` (related), `chief_id`, `stamp`.
Огромный файл `models/dop_field.py` (≥309 строк) — сборка «представления» контрагента с банковскими реквизитами для подстановки в текст договора.

Отчёты, реально загружаемые манифестом: `report/report_contract_simple.xml:3` — «Договор (WeasyPrint)» и `report/report_contract.xml:19` — «Договор».

**Мёртвый код (не импортируется в `models/__init__.py`)**: `contract_customer.py` (дубль модели `partner.contract.customer`, 460+ строк), `contract_customer_report_templates.py`, `crutch_fields_header.py`, `invoice_saleorder.py`, `sale_make_invoice_advance.py`, `account_move.py`, `sale_order.py`, `purchase_order.py`. Также `report/report_contract_docx.xml` (ссылается на `action_report_contract_with_format`, которого в живой модели нет) и `report_contract_order*.xml` / `report_contract_invoice.xml` в манифест не включены. Модуль явно пережил рефакторинг, и старые файлы оставили лежать — при доработке легко напороться.

### 8.2. l10n_ru_contract_account
Зависимости: `l10n_ru_contract, account`.
- `contract.profile` += `payable_account_id`, `receivable_account_id`, `max_receivable_id` («Максимальная деб. задолженность»), `payment_term_id`, `journal_id` — все `required=True`.
- `account.move` += `mt_contract_id` («Номер договора»), `sf_number` («Номер с/ф»), `osnovanie`, `sec_partner_id`, `stamp` (related от договора).
- `partner.contract.customer` += `sec_partner_id`, `accountant_id`, `buh_code`, `payment_term_id`.
- Отчёт `report/report_contract_invoice.xml:581` — «Договор со спецификацией» по счёту.

### 8.3. l10n_ru_contract_sale
Зависимости: `l10n_ru_contract_account, sale, sale_management`.
- `sale.order` += `mt_contract_id`, `sec_partner_id`, `stamp`.
- `partner.contract.customer` += `sale_order_id`, `manager_id`, `team_id`.
- Наследует `sale.advance.payment.inv`.
- Отчёты: «Договор со спецификацией» (`report/report_contract_order.xml:583`) и **«Спецификация»** (`report/report_contract_order1.xml:395`). Для завода металлоконструкций спецификация к договору — это почти всегда обязательный документ, здесь она есть.

### 8.4. l10n_ru_contract_purchase
Зависимости: `l10n_ru_contract_account, purchase`. Один файл: `purchase.order` += `mt_contract_id`, `sec_partner_id`. Отчётов нет.

### 8.5. l10n_ru_contract_templates
Зависимости: `web, l10n_ru_contract, docx_report`. Подмешивает `docx.template.mixin` в `partner.contract.customer` и `contract.profile` (`models/*.py:5-6`) → у договора и у вида договора появляется поле `docx_template_id`, то есть **договор можно печатать по вашему Word-шаблону**.

---

## 9. Движок отчётов: Word-бланки без программиста (ПОДРОБНО)

Это, пожалуй, самая ценная для завода часть всей группы.

### 9.1. docx_report_generation (RYDLAB) — базовый механизм
Зависимости: `base, web, custom_report_field`; python: `docxcompose, docxtpl, bs4`.

- Добавляет в `ir.actions.report` типы **`docx-docx`** и **`docx-pdf`** (`models/ir_actions_report.py:40-43`) и поле `report_docx_template` (Binary — сам .docx).
- Рендер: `_render_docx_template()` → `DocxTemplate(template_file); doc.render(values)` (`models/ir_actions_report.py:438-439`) — то есть **docxtpl, т.е. Jinja2 внутри Word-файла**.
- Как это выглядит на практике (из `docx_report_generation/README.md:34-47`):
  1. Бухгалтер/технолог рисует бланк в Word (или LibreOffice) — со своей шапкой, рамками, логотипом, любым форматированием; всё форматирование сохраняется в результате;
  2. В местах подстановки пишет `{{ docs.partner_id.name }}`, `{{ docs.amount_total }}` — доступ к записи Odoo через переменную `docs`, с обращением к полям и методам как в Python;
  3. Заходит в Настройки → Технические → Отчёты, создаёт запись, тип «DOCX» или «DOCX(PDF)», прикладывает файл — «Имя шаблона» заполнять не нужно;
  4. В меню «Печать» нужной модели появляется новый пункт.
- В контексте шаблона доступны хелперы `number2words` / `currency2words` / `format_number` из `report_monetary_helpers` и «кастомные поля» из `custom_report_field`.
- Множественная печать: склейка нескольких документов в один .docx через `docxcompose` (`_merge_docx`, `:350`).
- PDF: через внешний сервис **Gotenberg** (`_get_pdf_from_office`, `:455`), по умолчанию `localhost:8808`, интеграция через опциональный модуль `gotenberg` — если его нет или сервис недоступен, отчёты выдаются только в .docx (`models/ir_actions_report.py:19-27`). Сам модуль `gotenberg` в поставке RuOdoo **отсутствует**.
- Авторы честно пишут в манифесте: «This is the beta version, bugs may be present» и «одновременное создание нескольких отчётов не поддерживается».

### 9.2. docx_report (MK.Lab) — надстройка с удобным UI
Зависимости: `base, account, sale, l10n_ru_contract`.

- Новая модель **`docx.template`** (`models/docx_template.py:22`, «DOCX-шаблон договора») — фактически «конструктор печатных форм»: `report_id`, `docx_model_id` (какая модель), `available_field_ids` (вычисляемый список доступных полей — подсказка для автора шаблона, `:116`), `filename_pattern`, `docx_output_type`, `global_template`, `report_docx_template` + `report_docx_template_filename`, `hint_model_id`.
- Методы `action_bind_to_actions` / `action_bind_all_to_actions` / `action_unbind_from_actions` (`:86-108`) — сами создают/удаляют `ir.actions.report`, то есть шаблон привязывается к меню «Печать» кнопкой, без правки XML.
- **`action_validate_docx_template()`** (`:169-330`) — проверяет шаблон: вытаскивает все `{{ ... }}` и `{% for %}`, разбирает цепочки полей по `ir.model.fields`, идёт по реляциям и сообщает об опечатках ДО печати. Это ровно то, что нужно непрограммисту.
- `docx.custom.field` (`models/docx_custom_field.py:5`): `technical_name`, `name`, `value_python` — своё вычисляемое значение на Python для подстановки в бланк.
- `ir.model.fields.docx_type_label` (`models/ir_model_fields.py`) — человекочитаемый тип поля («many2one (res.partner)», «selection (a, b)») в подсказке.
- `docx.template.mixin` — поле `docx_template_id` на объекте (используется `l10n_ru_contract_templates`).
- Готовые Word-шаблоны в комплекте (`data/docx_template.xml`): «Контракт с клиентом» (`static/src/docx/contract.docx`, модель `partner.contract.customer`), «УПД DOCX», «УПД без печатей DOCX» (`account.move`), «Счет по форме 1С DOCX» (`sale.order`). **ТОРГ-12 и Акт среди DOCX-шаблонов отсутствуют** (в `l10n_ru_doc/static/src/docx/` их .docx лежат, но записи `docx.template` для них не создаются).
- Права (`security/ir.model.access.csv`): обычный пользователь — только чтение; создавать/менять шаблоны может только `base.group_system` (админ). То есть «бухгалтер сам сделает бланк» — только если ему дадут админские права.

### 9.3. pdf_report_from_docx — DOCX → PDF через Gotenberg
Зависимости: `base, docx_report`; python: `requests`.
- Добавляет `docx.template.docx_output_type += 'pdf'` (`models/docx_template.py`).
- URL сервиса берётся из системного параметра `gotenberg.server.url`, по умолчанию `http://localhost:3000`; конвертация — `POST {url}/forms/libreoffice/convert`; health-check `GET {url}/health` с таймаутом 3 с; поддержка basic-auth через параметры `gotenberg.server.username/password` (`models/ir_actions_report.py:23-46,192-202`).
- В комплекте готовый `pdf_report_from_docx/docker-compose.yml` с `gotenberg/gotenberg:8` на порту 3000 — то есть нужен **ещё один контейнер рядом с Odoo**.

### 9.4. custom_report_field (RYDLAB)
Зависимости: `base, web, report_monetary_helpers`.
- Модель `custom.report.field` (`models/custom_report_field.py:13`): `ir_actions_report_id`, `name`, `technical_name`, `default_value` (Text — Python-код, исполняется через `safe_eval(..., mode="exec")`, `:101`), `description`, `required`, `visible`, `sequence`.
- Визард `custom_report_field_values_wizard` — перед печатью показывает поля, значения можно проверить/поправить вручную.
- Практический смысл: «номер спецификации», «срок изготовления», «основание» — то, чего в данных нет, вводится или считается в момент печати.

### 9.5. report_monetary_helpers — сумма прописью (да)
Зависимости: `base`; python: `num2words`. Лицензия LGPL-3, автор RYDLAB.
- Переопределяет `ir.actions.report._get_rendering_context()` (`models/ir_actions_report.py:15-24`) и добавляет во **все** отчёты три функции: `number2words(...)`, `currency2words(...)`, `format_number(...)`.
- `currency2words` (`utils/num2words.py:23-40`): язык по умолчанию `ru`, валюта по умолчанию `RUB`, результат вида «Сто двадцать три рубля, 45 копеек» (целая часть с заглавной, копейки двумя цифрами).
- `format_number` (`utils/format_number.py:29+`): округление, разделитель дробной части (по умолчанию запятая), разбивка по три разряда пробелом.
- Поддержка 25 языков. Плюс независимо от этого модуля в `l10n_ru_doc/report_helper.py` есть собственная сумма прописью через `pytils.numeral` — в системе два параллельных механизма прописи.

### 9.6. report_weasyprint
Зависимости: `base, web`; python: `weasyprint`.
- Поле `ir.actions.report.use_weasyprint` (`models/ir_actions_report_weasy.py:18`) — на каждый отчёт отдельно.
- Подменяет `_run_wkhtmltopdf()` (`:36`) на `weasyprint.HTML(...).write_pdf(font_config=...)` (`:73-76`).
- Зачем: wkhtmltopdf — мёртвый проект, плохо тянет CSS и русские шрифты; WeasyPrint рендерит современный CSS. От него зависит печать договора (`l10n_ru_contract` → «Договор (WeasyPrint)»).

---

## 10. account_bank_statement_1c_import — импорт выписки из 1С (ПОДРОБНО)

Зависимости: `account, l10n_ru_doc`. Версия `19.0.0.1` (нулевая, «Нет истории изменений» в release-note).

### Что понимает
Формат **1CClientBankExchange** — текстовый обмен «1С:Бухгалтерия ↔ Клиент банка»:
- файл только `.txt` (`wizard/invoice_import_wizard.py:25-27` — иначе `UserError("Only TXT files are allowed")`);
- кодировка жёстко **cp1251** (`:30`);
- разбор — примитивный: `file_content.split('СекцияДокумент')`, затем шапка `split('СекцияРасчСчет')`, а каждая секция парсится построчно по `ключ=значение` (`:69-75`).

Читаемые ключи:
- шапка выписки: `РасчСчет`, `ДатаНачала`, `НачальныйОстаток`, `КонечныйОстаток` → создаётся `account.bank.statement` с добавленным полем `date_from` (`models/account_bank_statement.py:6`, `wizard:78-86`);
- документ: `Номер`, `Дата`, `Сумма`, `НазначениеПлатежа`, `ПлательщикИНН/КПП/Счет/БИК/Корсчет/Банк1`, `Получатель…` те же (`:108-140`).

Логика: сравнивает ИНН плательщика/получателя с `journal.company_id.vat` и на этом определяет знак суммы (`:122-124` — расход делает отрицательным). Журнал выбирается как первый `account.journal` с `type='bank'` и новым флагом **`use_in_bank_statement`** (`models/account_journal.py:6`). Контрагента ищет по паре ИНН+КПП, **не найдя — создаёт нового** `res.partner` (`:160-166`); так же автосоздаёт `res.bank` по БИК+корсчёту (`:169-175`) и `res.partner.bank` (`:177-183`). Дубли строк отсекает по (дата, сумма, назначение, номер) (`:150-157`).

### Чего НЕ умеет / где сломается
- **Нет проверки заголовка `1CClientBankExchange` и `ВерсияФормата`** — любой txt с похожими ключами будет проглочен.
- **Практический баг:** выписка создаётся с `date_from = ДатаНачала` (начало периода), а каждая строка ищет выписку по `date_from == дата транзакции` (`:110-116`). Для любой операции не в первый день периода → `UserError("Statement not found for journal … on date …")`. То есть на реальной месячной выписке импорт упадёт почти сразу. Нужна правка перед использованием.
- Не читает: `ДатаСписано`/`ДатаПоступило` (использует `Дата` — дату документа, а не проводки), реквизиты бюджетных платежей (`ПоказательТипа`, `ПоказательКБК`, `ОКАТО`, `ПоказательОснования`, `ПоказательПериод` — то есть налоги/взносы приедут без КБК), `ВидПлатежа`, `Очередность`, `НазначениеПлатежа1..6`, НДС из назначения, валютные реквизиты.
- **Нет автосопоставления** (reconcile) с счетами/инвойсами — импортируются только строки выписки, разносить их по документам оператор будет вручную.
- **Нет обратной выгрузки** — платёжные поручения из Odoo в банк/1С не экспортируются. Односторонний импорт.
- Журнал ищется `limit=1` без фильтра по компании и по валюте — при нескольких расчётных счетах попадёт в случайный.
- Нет мультивалютности; нет логирования (все `_logger` закомментированы), любая ошибка оборачивается в `UserError("Error Import: …")` — отладка вслепую.

---

## 11. account_move_templates + account_move_templates_invoice

**account_move_templates** (MK.Lab/RuOdoo, LGPL-3, зависит только от `account`):
- `account.move.template` (`models/account_move_template.py:14`): `name`, `description`, `tag_ids` → `account.move.template.tag` (признаки/теги с цветом), `line_ids`.
- `account.move.template.line` (`:51`): `account_id`, `move_type` (дебет/кредит), **`percent`** (распределение в процентах), `line_type` (продуктовая строка / строка оплаты).
- Контроли: `_check_balance()` (`:29`) — шаблон должен балансироваться; `_check_percent()` (`:88`).
- Визард `account_move_template_wizard.py` — применить шаблон и получить проводку.
- Смысл: типовые операции («начисление амортизации», «закрытие 20 → 43», «распределение косвенных») одним кликом. Для завода — полезно при ручных бухсправках, но **не заменяет план счетов** (§0.1): счета в шаблоне надо сначала создать.

**account_move_templates_invoice** (зависит от `account, account_move_templates`):
- `account.move` += `journal_template_id` (`models/account_move.py:19`).
- **Переопределяет `action_post()`** (`:127`): при включённом системном параметре `account_move_templates_invoice.use_journal_templates_for_invoices` (галка в настройках, `models/res_config_settings.py:7`) при проведении счёта счета в продуктовых строках подменяются на счета из шаблона, создаются строки payment_term с датами погашения.
- Риск: `:139-141` — если параметр включён, а у документа шаблон не выбран, проведение падает `UserError`. Вмешательство в `action_post` бухгалтерского документа — самое чувствительное место в Odoo; включать только после серьёзного теста.

---

## 12. dadata_connector — заполнение контрагента по ИНН (ПОДРОБНО)

Зависимости: `base, web, contacts, account, l10n_ru_doc`; python: **`dadata==21.10.1`** (жёсткий пин).

### Как работает
- В форму контакта поле `vat` автоматически получает виджет `dadata_search` (`models/res_partner.py:29-35` — переопределён `_get_view`, без правки XML-вида).
- Рядом с ИНН появляется кнопка поиска; JS (`static/src/views/fields/search/search_field.js:24-32`) вызывает `res.partner.get_legal_entity_data(vat)`.
- Python (`models/res_partner.py:37-67`): `Dadata(token).find_by_id("party", vat, branch_type="MAIN")` — то есть **справочник организаций «Поиск по ИНН», только головная организация** (филиалы не берутся).
- Результат показывается в визарде `res.partner.auto_data.wizard` (`wizard/res_partner_auto_data_wizard.py`) с вопросом «Set these details for the current contact?» и цветовой индикацией статуса: активна — зелёный, ликвидируется/ликвидирована/банкротство/реорганизация — красный (`README.md:52-58`). После «Да» JS пишет поля в запись и сохраняет.

### Что тянет
Из ответа DaData (`models/res_partner.py:86-164`): ИНН, **КПП** (только для юрлиц), **ОГРН**, **ОКПО**, ОКВЭД, код ОПФ (маппинг на тип в словаре `okopf`, `:7-22`), краткое наименование с ОПФ (для юрлица) либо ФИО (для ИП), серия/номер и дата свидетельства ФНС, страна/регион (по `region_iso_code`)/город/улица+дом+квартира/индекс, и **руководитель** — ФИО + должность, который создаётся отдельным дочерним контактом-сотрудником (`search_field.js:57-60`, `_checkManagerExists`).

**Важная оговорка:** часть полей в коде записывается под именами, которых в Odoo не существует — `arceat` (ОКВЭД, `:100`), `company_form` (`:101`), `sp_register_number`/`sp_register_date` (`:103-107`). JS явно фильтрует: «Only update fields that exist in the current record's field definitions» (`search_field.js:38-47`), поэтому падения не будет, но **ОКВЭД, ОПФ и дата регистрации молча не сохранятся** — их некуда писать. Чтобы они доехали, нужно добавить поля в `res.partner`.

### Ключ DaData
Нужен токен: Настройки → Интеграции → «DaData token» (`models/res_config_settings.py:7-10`, системный параметр `dadata_connector.dadata_token`). Без токена — `ValidationError` с подсказкой где взять (`models/res_partner.py:78-82`).
Платный ли: по README (`dadata_connector/README.md:29`) — «Бесплатный план включает 10 000 запросов в день». Для завода этого хватает с многократным запасом; регистрация на dadata.ru обязательна, но платить не нужно. При неверном токене — `ValidationError("Failed to connect to DaData server. The token in the settings may be incorrect.")` (`:41-47`).

---

## 13. Чего в этих 21 модуле НЕТ (проверено поиском, не догадка)

- **План счетов РФ** — нет (§0.1).
- **Регламентированная отчётность** (баланс, ф.2, декларация НДС, книги покупок/продаж, счёт-фактура журнал) — нет.
- **Оборотно-сальдовая ведомость** — нет («Оборотно» не встречается ни в одном файле RuOdoo).
- **Электронная подпись / КриптоПро / ГОСТ** — нет.
- **Коннектор к оператору ЭДО** (Диадок, СБИС, Такском) — нет, хотя поля называются «ID EDI … для Diadoc».
- **УКД (корректировочный УПД), КСФ в XML** — нет, только `Функция='СЧФДОП'`.
- **XSD-валидация выгрузки** — поле есть, проверка не выполняется.
- **Экспорт платёжных поручений в банк/1С** — нет (импорт односторонний).
- **Кадры/зарплата по РФ, НДФЛ, взносы** — нет.
- **Унифицированные М-2/М-4/М-11/М-15, МХ-1, ОС-1** — нет; из «госкомстатовских» форм есть только ТОРГ-12.
- **Модуль `gotenberg`**, на который опирается конвертация DOCX→PDF в `docx_report_generation` — в поставке отсутствует (есть альтернативный путь через `pdf_report_from_docx`).

---

## 14. Итоговая таблица: модуль → что даёт заводу → критичность

| Модуль | Что даёт заводу металлоконструкций | Критичность |
|---|---|---|
| **l10n_ru_base** | Страница настроек и включение остальных RU-модулей; гейт лицензии/страны | **Обязателен** (от него зависят все RU-модули) |
| **l10n_ru_doc** | ИНН/КПП/ОКПО/ОГРН, корсчёт+БИК, факсимиле и печать, ОКЕИ-код у ЕИ, ТНВЭД, «Не видно в ПФ» у налогов, поля УПД на счёте (грузоотправитель/грузополучатель/ответственный/транспорт/основание), сумма прописью; шаблоны ТОРГ-12, СФ, Акт, УПД, УПД без печатей, Счёт 1С. **Но действующие кнопки печати есть только у Счёта 1С и двух УПД — ТОРГ-12/СФ/Акт закомментированы (`report/l10n_ru_doc_report.xml:83,59,107`)** | **Обязателен** (без него нет ни одного российского реквизита), но требует доводки печатных форм в первый же день |
| **l10n_ru_upd_xml** | Кнопка «Печать УПД в xml-формате», сильный валидатор реквизитов (~40 проверок), кодировка windows-1251, ОКЕИ на ЕИ. НО: нет `СвУчДокОбор`, нет подписи, нет отправки оператору, страна происхождения зашита «Китай», ставка НДС/сумма налога считаются упрощённо | **Полезен как заготовка.** Для реального ЭДО — доработка обязательна; если ЭДО не планируется в первый год — можно не ставить |
| **l10n_ru_act_rev** | Настоящий двусторонний акт сверки (сальдо начальное/обороты/сальдо конечное, «задолженность в пользу», прописью, подписи, М.П.), визард с периодом и режимом проводок. Портальная кнопка сломана (`controllers/controllers.py:8`). ОСВ нет | **Обязателен** — акт сверки требуют все контрагенты и налоговая; альтернативы в Odoo нет |
| **l10n_ru_contract** | Реестр договоров с нумерацией, видами, статусами, пунктами-конструктором (HTML), шаблонами договоров, кредитным лимитом, печатью договора. Много мёртвого кода | **Обязателен** для завода: договор + спецификация — основа продажи металлоконструкций |
| **l10n_ru_contract_account** | Привязка договора к счёту (`mt_contract_id`), счета Дт/Кт и условия оплаты на виде договора, «Максимальная деб. задолженность», «Договор со спецификацией» по счёту | **Обязателен** (без него договор не связан с бухгалтерией) |
| **l10n_ru_contract_sale** | Договор на заказе продаж, менеджер/команда, печать «Договор со спецификацией» и **«Спецификация»** | **Обязателен** — спецификация к договору по металлу нужна почти всегда |
| **l10n_ru_contract_purchase** | Договор на заказе закупки (два поля, отчётов нет) | Полезен (закупка металла у поставщиков) |
| **l10n_ru_contract_templates** | Печать договора по вашему Word-шаблону (`docx_template_id` на договоре и виде договора) | Полезен (сильно, если юрист хочет править договор сам) |
| **l10n_ru_advance_payments** | Отдельный документ «Авансовый счёт» (`order.prepaid`) с оплатами и остатком, счёт 1С по нему. Проводок по НДС с авансов не делает | Полезен (схема 50/50 у завода типична), но не обязателен |
| **l10n_ru_attorney** | Доверенность на получение ТМЦ (`base.consent`), привязка к сотруднику и заказу закупки, паспортные данные сотрудника. Не форма М-2, печать надо доставать из Технических настроек | Полезен, при самовывозе металла — практично |
| **account_bank_statement_1c_import** | Импорт выписки 1CClientBankExchange (txt/cp1251), автосоздание контрагента/банка/счёта по ИНН+КПП. **Есть блокирующий баг поиска выписки по дате (`wizard:110-116`)**, нет КБК, нет автосопоставления, нет обратной выгрузки | Полезен после правки бага; иначе — не работоспособен |
| **account_move_templates** | Шаблоны типовых проводок с процентным распределением, теги, контроль баланса | Полезен (бухсправки, распределение косвенных) |
| **account_move_templates_invoice** | Автоподмена счетов при проведении счёта по шаблону. Лезет в `action_post()` | **Не нужен на старте** — высокий риск, включать только после теста |
| **dadata_connector** | Кнопка у ИНН: подтягивает наименование, КПП, ОГРН, ОКПО, адрес, руководителя; предупреждает о ликвидации/банкротстве контрагента. ОКВЭД/ОПФ/дата регистрации молча теряются. Ключ DaData бесплатный (10 000 запросов/день) | **Обязателен по соотношению польза/цена** — экономит ручной ввод и снимает риск работы с ликвидируемым контрагентом |
| **docx_report_generation** | Движок: типы отчётов DOCX и DOCX(PDF), рендер Word-шаблонов через docxtpl (Jinja2), склейка нескольких документов, PDF через Gotenberg. Автор помечает как beta | **Обязателен** — это и есть «свои формы в Word без программиста» |
| **docx_report** | Удобная надстройка: модель `docx.template`, привязка к меню «Печать» кнопкой, **валидатор шаблона** с разбором `{{ }}` по полям модели, подсказка доступных полей, кастомные поля, готовые .docx (Договор, УПД, УПД без печатей, Счёт 1С). Создание шаблонов — только админу | **Обязателен** вместе с предыдущим |
| **pdf_report_from_docx** | DOCX → PDF через Gotenberg (`gotenberg/gotenberg:8`, свой docker-compose, health-check, basic-auth) | **Обязателен, если нужен PDF** из Word-бланков; требует ещё один контейнер |
| **custom_report_field** | Поля «на лету» для печатных форм с Python-выражением + визард проверки значений перед печатью | Полезен |
| **report_monetary_helpers** | **Да, сумма прописью**: `currency2words(amount, lang="ru", currency="RUB")` → «Сто двадцать три рубля, 45 копеек», плюс `number2words` и `format_number` (пробелы по три разряда, запятая). Доступно во всех отчётах | **Обязателен** — прописью требуется в счёте, УПД, акте, договоре |
| **report_weasyprint** | PDF через WeasyPrint вместо мёртвого wkhtmltopdf, включается на каждый отчёт отдельно; нужен для печати договора | **Обязателен** (зависимость `l10n_ru_contract`) |

### Минимальный рабочий набор для завода
`l10n_ru_base` + `l10n_ru_doc` + `l10n_ru_contract` + `l10n_ru_contract_account` + `l10n_ru_contract_sale` + `l10n_ru_act_rev` + `report_monetary_helpers` + `report_weasyprint` + `custom_report_field` + `docx_report_generation` + `docx_report` (+ `pdf_report_from_docx` если нужен PDF) + `dadata_connector`.
Отдельными задачами: план счетов РФ с нуля, раскомментировать/пересоздать ТОРГ-12 и Акт, починить дату в импорте выписок, решить вопрос ЭДО (доработка `l10n_ru_upd_xml` либо внешний сервис оператора).
