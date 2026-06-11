"""
Настройка формы Lead через Customize Form API.

Использует тот же API что и ERPNext Customize Form UI — атомарно сохраняет
всю конфигурацию формы за один вызов, гарантируя корректный порядок полей.

Запуск:
    # 1. Скопировать файл в контейнер
    docker cp services/erp/setup/lead_form_setup.py erp-backend-1:/tmp/lead_form_setup.py

    # 2. Выполнить
    docker exec erp-backend-1 bash -c '
      cd /home/frappe/frappe-bench/sites && source ../env/bin/activate && python3 -c "
        import frappe
        frappe.init(site=\"erp.localhost\", sites_path=\".\")
        frappe.connect()
        exec(open(\"/tmp/lead_form_setup.py\").read())
        execute()
        frappe.destroy()
      "'

    # 3. Сбросить кэш (обязательно)
    docker exec erp-backend-1 bench --site erp.localhost clear-cache

Целевой макет:
    ┌──────────────────────────────────────────────┐
    │  Серия              │  Владелец Лида          │
    │                     │  Статус *               │
    ├──────────────────────────────────────────────┤
    │  [Контакт]                                   │
    │  ФИО *              │  Email                  │
    │  Должность          │  Мобильный телефон      │
    │                     │  Телефон                │
    ├──────────────────────────────────────────────┤
    │  [Организация и запрос]                      │
    │  Наименование *     │  Источник               │
    │  Объём (тонн)       │  Город                  │
    │  Дата поставки      │  Регион                 │
    │  Наличие чертежей   │                         │
    │  AI-комментарий     │                         │
    │  Примечание         │                         │
    └──────────────────────────────────────────────┘

Client Script (синхронизация кастомных полей со стандартными):
    frappe.ui.form.on('Lead', {
        mw_full_name: function(frm) { frm.set_value('first_name', frm.doc.mw_full_name); },
        mw_job_title: function(frm) { frm.set_value('job_title',  frm.doc.mw_job_title);  }
    });
"""

import frappe

# ─── Поля которые скрываем ─────────────────────────────────────────────────────
HIDE = {
    # Личные данные
    'salutation', 'gender', 'middle_name', 'last_name', 'lead_name',
    'first_name',   # заменён кастомным mw_full_name
    'job_title',    # заменён кастомным mw_job_title
    # Тип / статус
    'type', 'customer', 'request_type',
    # Контакты — лишние
    'phone_ext', 'whatsapp_no', 'website',
    # Организация — нерелевантные
    'annual_revenue', 'no_of_employees', 'industry', 'market_segment', 'fax',
    # UTM — заменён mw_source
    'utm_source', 'utm_campaign', 'utm_medium', 'utm_content', 'utm_analytics_section',
    # Адрес — заменён кастомными mw_city / mw_state
    'address_section', 'city', 'state', 'country', 'territory',
    # Сертификация
    'qualification_tab', 'qualified_by', 'qualified_on', 'qualification_status',
    # Доп. информация
    'other_info_tab', 'language', 'unsubscribed', 'blog_subscriber', 'disabled',
    # Наша компания
    'company',
    # Лишние стандартные Column Break — ломают сетку
    'col_break123',       # TOP: пустая средняя колонка
    'column_break_20',    # Contact: лишний разрыв
    'column_break_16',    # Contact: лишний разрыв перед phone
    'column_break_28',    # Org: пустой разрыв
    'column_break_31',    # Org: пустой разрыв
}

# ─── Переименования стандартных секций ────────────────────────────────────────
SECTION_LABELS = {
    'contact_info_tab':     'Контакт',
    'organization_section': 'Организация и запрос',
}

# ─── Кастомные поля — в порядке insert_after ──────────────────────────────────
CUSTOM_FIELDS = [
    # ── Блок «Контакт» ────────────────────────────────────────────────────────
    dict(fieldname='mw_full_name',  fieldtype='Data',         label='ФИО',
         reqd=1, insert_after='contact_info_tab', is_custom_field=1),
    dict(fieldname='mw_job_title',  fieldtype='Data',         label='Должность',
         insert_after='mw_full_name', is_custom_field=1),
    dict(fieldname='mw_cb_contact', fieldtype='Column Break', label='',
         insert_after='mw_job_title', is_custom_field=1),
    # После col break: email_id, mobile_no, phone — стандартные, встают в col2

    # ── Блок «Организация и запрос» — левая колонка ───────────────────────────
    dict(fieldname='mw_estimated_volume',      fieldtype='Float',
         label='Объём (тонн)',            insert_after='company_name',          is_custom_field=1),
    dict(fieldname='mw_desired_delivery_date', fieldtype='Date',
         label='Желаемая дата поставки',  insert_after='mw_estimated_volume',   is_custom_field=1),
    dict(fieldname='mw_drawing_status',        fieldtype='Select',
         label='Наличие чертежей',
         options='\nЕсть готовые\nНужна разработка\nЧастично',
         insert_after='mw_desired_delivery_date', is_custom_field=1),
    dict(fieldname='mw_ai_comment',            fieldtype='Text',
         label='AI-комментарий', read_only=1,  insert_after='mw_drawing_status', is_custom_field=1),
    dict(fieldname='mw_note',                  fieldtype='Small Text',
         label='Примечание',               insert_after='mw_ai_comment',        is_custom_field=1),

    # ── Блок «Организация и запрос» — правая колонка ─────────────────────────
    dict(fieldname='mw_cb_org',    fieldtype='Column Break', label='',
         insert_after='mw_note',    is_custom_field=1),
    dict(fieldname='mw_source',    fieldtype='Link',  label='Источник',
         options='UTM Source',      insert_after='mw_cb_org',    is_custom_field=1),
    dict(fieldname='mw_city',      fieldtype='Data',  label='Город',
         insert_after='mw_source',  is_custom_field=1),
    dict(fieldname='mw_state',     fieldtype='Data',  label='Регион',
         insert_after='mw_city',    is_custom_field=1),
]

# ─── Client Script ─────────────────────────────────────────────────────────────
CLIENT_SCRIPT_NAME = 'Lead-Form'
CLIENT_SCRIPT = """\
frappe.ui.form.on('Lead', {
    mw_full_name: function(frm) {
        frm.set_value('first_name', frm.doc.mw_full_name);
    },
    mw_job_title: function(frm) {
        frm.set_value('job_title', frm.doc.mw_job_title);
    }
});
"""


def _apply_customize_form():
    cf = frappe.get_doc('Customize Form')
    cf.doc_type = 'Lead'
    cf.run_method('fetch_to_customize')
    print(f'  загружено полей: {len(cf.fields)}')

    field_map = {f.fieldname: f for f in cf.fields}

    # Скрыть и переименовать стандартные поля
    hidden_count = 0
    for f in cf.fields:
        if f.fieldname in HIDE:
            f.hidden = 1
            hidden_count += 1
        if f.fieldname in SECTION_LABELS:
            f.label = SECTION_LABELS[f.fieldname]

    print(f'  скрыто: {hidden_count} полей')
    print(f'  переименовано секций: {len(SECTION_LABELS)}')

    # Добавить или обновить кастомные поля
    for cf_def in CUSTOM_FIELDS:
        fn = cf_def['fieldname']
        if fn in field_map:
            f = field_map[fn]
            for k, v in cf_def.items():
                setattr(f, k, v)
            print(f'  updated: {fn}')
        else:
            cf.append('fields', cf_def)
            print(f'  added:   {fn}')

    cf.run_method('save_customization')
    frappe.db.commit()


def _upsert_client_script():
    existing = frappe.db.get_value('Client Script', {'dt': 'Lead'}, 'name')
    if existing:
        doc = frappe.get_doc('Client Script', existing)
        doc.script = CLIENT_SCRIPT
        doc.enabled = 1
        doc.save(ignore_permissions=True)
        print(f'  обновлён: {existing}')
    else:
        frappe.get_doc({
            'doctype': 'Client Script',
            'name': CLIENT_SCRIPT_NAME,
            'dt': 'Lead',
            'view': 'Form',
            'enabled': 1,
            'script': CLIENT_SCRIPT,
        }).insert(ignore_permissions=True)
        print(f'  создан: {CLIENT_SCRIPT_NAME}')
    frappe.db.commit()


def execute():
    print('=== Lead Form Setup via Customize Form API ===\n')

    print('[1/2] Customize Form...')
    _apply_customize_form()

    print('\n[2/2] Client Script...')
    _upsert_client_script()

    print('\n✅ Готово. Запустите: bench --site erp.localhost clear-cache')
