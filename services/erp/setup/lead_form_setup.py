"""
Настройка формы Lead: откат + пересборка через Customize Form API.

Использует тот же механизм что UI /desk/customize-form — атомарно сохраняет
конфигурацию формы, гарантируя корректный порядок полей.

Запуск:
    # 1. Скопировать файл в контейнер
    docker cp services/erp/setup/lead_form_setup.py erp-backend-1:/tmp/lead_form_setup.py

    # 2. Выполнить (откат + пересборка + кэш)
    docker exec erp-backend-1 bash -c '
      cd /home/frappe/frappe-bench/sites && source ../env/bin/activate && python3 -c "
        import frappe
        frappe.init(site=\"erp.localhost\", sites_path=\".\")
        frappe.connect()
        exec(open(\"/tmp/lead_form_setup.py\").read())
        execute()
        frappe.destroy()
      "' && \
    docker exec erp-backend-1 bench --site erp.localhost clear-cache

Целевой макет:
    [TOP]
      Серия              │  Владелец Лида
                         │  Статус *

    [Контакт]
      ФИО *              │  Email
      Должность          │  Мобильный телефон
                         │  Телефон

    [Организация и запрос]
      Наименование *     │  Источник
      Объём (тонн)       │  Город
      Дата поставки      │  Регион
      Наличие чертежей   │
      AI-комментарий     │
      Примечание         │

Client Script Lead-Form синхронизирует:
    mw_full_name → first_name
    mw_job_title → job_title
"""

import frappe

# ─── Стандартные поля — скрыть ────────────────────────────────────────────────
HIDE = {
    # Личные данные
    'salutation', 'gender', 'middle_name', 'last_name', 'lead_name',
    'first_name',   # заменён кастомным mw_full_name
    'job_title',    # заменён кастомным mw_job_title
    # Тип / статус
    'type', 'customer', 'request_type',
    # Контакты — лишние
    'phone_ext', 'whatsapp_no', 'website',
    # Contact Info column break-и — скрываем чтобы email+mobile+phone шли в одну col2
    'column_break_20',   # разрыв между email и mobile
    'column_break_16',   # разрыв перед phone
    # Организация — нерелевантные
    'annual_revenue', 'no_of_employees', 'industry', 'market_segment', 'fax',
    # Org column break-и — оставляем только наш mw_cb_org
    'column_break_28',
    'column_break_31',
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
}

# ВАЖНО: col_break123 НЕ скрываем — он нужен чтобы lead_owner/status встали в col2

# ─── Переименования стандартных секций ────────────────────────────────────────
SECTION_LABELS = {
    'contact_info_tab':     'Контакт',
    'organization_section': 'Организация и запрос',
}

# ─── Кастомные поля ────────────────────────────────────────────────────────────
CUSTOM_FIELDS = [
    # ── Контакт: левая колонка (ФИО, Должность) ──────────────────────────────
    {'fieldname': 'mw_full_name',  'fieldtype': 'Data',         'label': 'ФИО',
     'reqd': 1, 'insert_after': 'contact_info_tab'},
    {'fieldname': 'mw_job_title',  'fieldtype': 'Data',         'label': 'Должность',
     'insert_after': 'mw_full_name'},
    # Column Break → col2: email_id, mobile_no, phone встают следом
    {'fieldname': 'mw_cb_contact', 'fieldtype': 'Column Break',
     'insert_after': 'mw_job_title'},

    # ── Организация и запрос: левая колонка ───────────────────────────────────
    # company_name стандартное — col1, не трогаем
    {'fieldname': 'mw_estimated_volume',      'fieldtype': 'Float',
     'label': 'Объём (тонн)',            'insert_after': 'company_name'},
    {'fieldname': 'mw_desired_delivery_date', 'fieldtype': 'Date',
     'label': 'Желаемая дата поставки',  'insert_after': 'mw_estimated_volume'},
    {'fieldname': 'mw_drawing_status',        'fieldtype': 'Select',
     'label': 'Наличие чертежей',
     'options': '\nЕсть готовые\nНужна разработка\nЧастично',
     'insert_after': 'mw_desired_delivery_date'},
    {'fieldname': 'mw_ai_comment',            'fieldtype': 'Text',
     'label': 'AI-комментарий', 'read_only': 1, 'insert_after': 'mw_drawing_status'},
    {'fieldname': 'mw_note',                  'fieldtype': 'Small Text',
     'label': 'Примечание',              'insert_after': 'mw_ai_comment'},

    # ── Организация и запрос: правая колонка (Источник, Город, Регион) ────────
    # Column Break → col2
    {'fieldname': 'mw_cb_org',  'fieldtype': 'Column Break', 'insert_after': 'mw_note'},
    {'fieldname': 'mw_source',  'fieldtype': 'Link',  'label': 'Источник',
     'options': 'UTM Source',   'insert_after': 'mw_cb_org'},
    {'fieldname': 'mw_city',    'fieldtype': 'Data',  'label': 'Город',
     'insert_after': 'mw_source'},
    {'fieldname': 'mw_state',   'fieldtype': 'Data',  'label': 'Регион',
     'insert_after': 'mw_city'},
]

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


def reset():
    """Полный откат — удаляем все кастомизации Lead."""
    print('=== Откат формы Lead ===')

    cf_list = frappe.get_all('Custom Field', filters={'dt': 'Lead'}, pluck='name')
    for n in cf_list:
        frappe.delete_doc('Custom Field', n, ignore_permissions=True, force=True)
    print(f'  Custom Field удалено: {len(cf_list)}')

    ps_list = frappe.get_all('Property Setter', filters={'doc_type': 'Lead'}, pluck='name')
    for n in ps_list:
        frappe.delete_doc('Property Setter', n, ignore_permissions=True, force=True)
    print(f'  Property Setter удалено: {len(ps_list)}')

    frappe.db.commit()
    print('  ✅ Откат выполнен.')


def setup():
    """Пересборка формы через Customize Form API."""
    print('=== Пересборка формы Lead ===')

    cf = frappe.get_doc('Customize Form')
    cf.doc_type = 'Lead'
    cf.run_method('fetch_to_customize')
    print(f'  загружено полей: {len(cf.fields)}')

    field_map = {f.fieldname: f for f in cf.fields}

    for f in cf.fields:
        if f.fieldname in HIDE:
            f.hidden = 1
        if f.fieldname in SECTION_LABELS:
            f.label = SECTION_LABELS[f.fieldname]

    print(f'  скрыто: {sum(1 for f in cf.fields if f.fieldname in HIDE)}')

    for fd in CUSTOM_FIELDS:
        fn = fd['fieldname']
        if fn in field_map:
            f = field_map[fn]
            for k, v in fd.items():
                setattr(f, k, v)
            print(f'  updated: {fn}')
        else:
            cf.append('fields', fd)
            print(f'  added:   {fn}')

    cf.run_method('save_customization')
    frappe.db.commit()
    print('  ✅ Пересборка выполнена.')


def _upsert_client_script():
    existing = frappe.db.get_value('Client Script', {'dt': 'Lead'}, 'name')
    if existing:
        doc = frappe.get_doc('Client Script', existing)
        doc.script = CLIENT_SCRIPT
        doc.enabled = 1
        doc.save(ignore_permissions=True)
        print(f'  Client Script обновлён: {existing}')
    else:
        frappe.get_doc({
            'doctype': 'Client Script',
            'name': CLIENT_SCRIPT_NAME,
            'dt': 'Lead',
            'view': 'Form',
            'enabled': 1,
            'script': CLIENT_SCRIPT,
        }).insert(ignore_permissions=True)
        print(f'  Client Script создан: {CLIENT_SCRIPT_NAME}')
    frappe.db.commit()


def execute():
    """Откат + пересборка + Client Script за один вызов."""
    reset()
    setup()
    _upsert_client_script()
    print('\n✅ Готово. Выполните: bench --site erp.localhost clear-cache')
