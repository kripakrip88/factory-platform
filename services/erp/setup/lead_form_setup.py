"""
Настройка формы Lead: откат + пересборка (гибридный подход).

Механизм:
  1. reset()           — удаляет все Custom Field и Property Setter для Lead
  2. apply_standard()  — Customize Form API: скрывает стандартные поля, переименовывает секции
  3. create_custom_fields() — Custom Field DocType: создаёт/обновляет mw_* поля

Запуск:
    docker cp services/erp/setup/lead_form_setup.py erp-backend-1:/tmp/lead_form_setup.py
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

Важно:
  col_break123         — НЕ скрываем: держит lead_owner/status в col2
  column_break_20/16   — скрываем: email+mobile+phone в единую col2
  column_break_28/31   — скрываем: убираем пустые разрывы в Организации
"""

import frappe

HIDE = {
    # Личные данные
    'salutation', 'gender', 'middle_name', 'last_name', 'lead_name',
    'first_name',   # заменён кастомным mw_full_name
    'job_title',    # заменён кастомным mw_job_title
    # Тип / статус
    'type', 'customer', 'request_type',
    # Контакты — лишние
    'phone_ext', 'whatsapp_no', 'website',
    # Contact Info column breaks — скрываем чтобы email+mobile+phone шли в одну col2
    'column_break_20', 'column_break_16',
    # Организация — нерелевантные
    'annual_revenue', 'no_of_employees', 'industry', 'market_segment', 'fax',
    # Org column breaks — оставляем только наш mw_cb_org
    'column_break_28', 'column_break_31',
    # UTM — заменён mw_source
    'utm_source', 'utm_campaign', 'utm_medium', 'utm_content', 'utm_analytics_section',
    # Адрес — заменён кастомными mw_city / mw_state
    'address_section', 'city', 'state', 'country', 'territory',
    # Квалификация
    'qualification_tab', 'qualified_by', 'qualified_on', 'qualification_status',
    # Доп. информация
    'other_info_tab', 'language', 'unsubscribed', 'blog_subscriber', 'disabled',
    # Наша компания
    'company',
}

# ВАЖНО: col_break123 НЕ скрываем — он нужен чтобы lead_owner/status встали в col2

SECTION_LABELS = {
    'contact_info_tab':     'Контакт',
    'organization_section': 'Организация и запрос',
}

CUSTOM_FIELDS = [
    # ── Контакт: левая колонка ─────────────────────────────────────────────────
    {'fieldname': 'mw_full_name',  'fieldtype': 'Data',         'label': 'ФИО',
     'reqd': 1, 'insert_after': 'contact_info_tab'},
    {'fieldname': 'mw_job_title',  'fieldtype': 'Data',         'label': 'Должность',
     'insert_after': 'mw_full_name'},
    # Column Break → col2: email_id, mobile_no, phone
    {'fieldname': 'mw_cb_contact', 'fieldtype': 'Column Break', 'insert_after': 'mw_job_title'},

    # ── Организация и запрос: левая колонка ────────────────────────────────────
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

    # ── Организация и запрос: правая колонка ───────────────────────────────────
    {'fieldname': 'mw_cb_org',    'fieldtype': 'Column Break', 'insert_after': 'mw_note'},
    {'fieldname': 'mw_source',    'fieldtype': 'Link',  'label': 'Источник',
     'options': 'UTM Source',     'insert_after': 'mw_cb_org'},
    {'fieldname': 'mw_city',      'fieldtype': 'Data',  'label': 'Город',
     'insert_after': 'mw_source'},
    {'fieldname': 'mw_state',     'fieldtype': 'Data',  'label': 'Регион',
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
    print('[reset] Удаляем старые кастомизации...')
    cf_list = frappe.get_all('Custom Field', filters={'dt': 'Lead'}, pluck='name')
    for n in cf_list:
        frappe.delete_doc('Custom Field', n, ignore_permissions=True, force=True)
    ps_list = frappe.get_all('Property Setter', filters={'doc_type': 'Lead'}, pluck='name')
    for n in ps_list:
        frappe.delete_doc('Property Setter', n, ignore_permissions=True, force=True)
    frappe.db.commit()
    print(f'  CF удалено: {len(cf_list)}, PS удалено: {len(ps_list)}')


def apply_standard():
    print('[customize] Скрываем поля и переименовываем секции...')
    cf = frappe.get_doc('Customize Form')
    cf.doc_type = 'Lead'
    cf.run_method('fetch_to_customize')
    for f in cf.fields:
        if f.fieldname in HIDE:
            f.hidden = 1
        if f.fieldname in SECTION_LABELS:
            f.label = SECTION_LABELS[f.fieldname]
    cf.run_method('save_customization')
    frappe.db.commit()
    print(f'  скрыто: {sum(1 for f in cf.fields if f.fieldname in HIDE)}, переименовано: {len(SECTION_LABELS)}')


def create_custom_fields():
    print('[custom fields] Создаём mw_* поля...')
    existing = {r.fieldname for r in frappe.get_all('Custom Field', filters={'dt': 'Lead'}, fields=['fieldname'])}
    for fd in CUSTOM_FIELDS:
        fn = fd['fieldname']
        if fn in existing:
            doc = frappe.get_doc('Custom Field', f'Lead-{fn}')
            for k, v in fd.items():
                setattr(doc, k, v)
            doc.save(ignore_permissions=True)
            print(f'  updated: {fn}')
        else:
            frappe.get_doc({'doctype': 'Custom Field', 'dt': 'Lead', **fd}).insert(ignore_permissions=True)
            print(f'  created: {fn}')
    frappe.db.commit()


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
    print('=== Lead Form Setup ===\n')
    reset()
    apply_standard()
    create_custom_fields()
    _upsert_client_script()
    print('\n✅ Готово. Выполните: bench --site erp.localhost clear-cache')
