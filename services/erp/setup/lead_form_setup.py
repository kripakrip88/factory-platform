#!/usr/bin/env python3
"""
Финальная настройка формы Lead — воспроизводит рабочее состояние.

Подход: гибридный
  - Customize Form API (fetch_to_customize + save_customization)
    → скрытие стандартных полей, переименование секций, field_order
  - Custom Field DocType
    → создание новых mw_* полей

Результат:
  TOP:              Серия | Владелец Лида + Статус
  Контакт:          ФИО, Должность | Email | Мобильный | Телефон
  Организация:      Название орг. | Источник
                    Объём (тонн)   | Город
                    Дата поставки  | Регион
                    Чертежи
                    AI-комментарий (read only)
                    Примечание

Запуск:
  docker compose exec backend bench --site frontend console
  exec(open('/tmp/lead_form_setup.py').read()); execute()
  # затем:
  docker compose exec backend bench --site frontend clear-cache
"""
import frappe

# ── 1. Стандартные поля которые скрываем ────────────────────────────────
HIDE = {
    'salutation', 'gender', 'middle_name', 'last_name', 'lead_name',
    'first_name', 'job_title',
    'type', 'customer', 'request_type',
    'phone_ext', 'whatsapp_no', 'website',
    'annual_revenue', 'no_of_employees', 'industry', 'market_segment', 'fax',
    'utm_source', 'utm_campaign', 'utm_medium', 'utm_content',
    'utm_analytics_section',
    'address_section', 'city', 'state', 'country', 'territory',
    'qualification_tab', 'qualified_by', 'qualified_on', 'qualification_status',
    'other_info_tab', 'language', 'unsubscribed', 'blog_subscriber',
    'disabled', 'company',
    # column_break_16 скрываем: между mobile и phone — лишний разрыв
    # column_break_20 оставляем видимым — он разделяет email от mobile
    'column_break_28',  # пустой разрыв в Organization
    'column_break_31',  # пустой разрыв в Organization
}

# ── 2. Переименования ────────────────────────────────────────────────────
SECTION_LABELS = {
    'contact_info_tab':     'Контакт',
    'organization_section': 'Организация и запрос',
}

# ── 3. Кастомные поля ────────────────────────────────────────────────────
CUSTOM_FIELDS = [
    # Контакт — левая колонка
    {'fieldname': 'mw_full_name',  'fieldtype': 'Data',
     'label': 'ФИО', 'reqd': 1, 'insert_after': 'contact_info_tab'},
    {'fieldname': 'mw_job_title',  'fieldtype': 'Data',
     'label': 'Должность', 'insert_after': 'mw_full_name'},
    # Column Break → email+mobile+phone идут правее
    {'fieldname': 'mw_cb_contact', 'fieldtype': 'Column Break',
     'insert_after': 'mw_job_title'},

    # Организация — левая колонка (company_name уже есть)
    {'fieldname': 'mw_estimated_volume',      'fieldtype': 'Float',
     'label': 'Объём (тонн)', 'insert_after': 'company_name'},
    {'fieldname': 'mw_desired_delivery_date', 'fieldtype': 'Date',
     'label': 'Желаемая дата поставки', 'insert_after': 'mw_estimated_volume'},
    {'fieldname': 'mw_drawing_status',        'fieldtype': 'Select',
     'label': 'Наличие чертежей',
     'options': '\nЕсть готовые\nНужна разработка\nЧастично',
     'insert_after': 'mw_desired_delivery_date'},
    {'fieldname': 'mw_ai_comment',            'fieldtype': 'Text',
     'label': 'AI-комментарий', 'read_only': 1,
     'insert_after': 'mw_drawing_status'},
    {'fieldname': 'mw_note',                  'fieldtype': 'Small Text',
     'label': 'Примечание', 'insert_after': 'mw_ai_comment'},
    # Column Break → правая колонка: Источник, Город, Регион
    {'fieldname': 'mw_cb_org',     'fieldtype': 'Column Break',
     'insert_after': 'mw_note'},
    {'fieldname': 'mw_source',     'fieldtype': 'Link',
     'label': 'Источник', 'options': 'UTM Source', 'insert_after': 'mw_cb_org'},
    {'fieldname': 'mw_city',       'fieldtype': 'Data',
     'label': 'Город', 'insert_after': 'mw_source'},
    {'fieldname': 'mw_state',      'fieldtype': 'Data',
     'label': 'Регион', 'insert_after': 'mw_city'},
]

# ── 4. Client Script — синхронизация mw_full_name → first_name ───────────
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
    """Полная очистка — удаляем все кастомизации Lead."""
    print('[1/4] Сброс...')
    cf_list = frappe.get_all('Custom Field', filters={'dt': 'Lead'}, pluck='name')
    for n in cf_list:
        frappe.delete_doc('Custom Field', n, ignore_permissions=True, force=True)
    ps_list = frappe.get_all('Property Setter', filters={'doc_type': 'Lead'}, pluck='name')
    for n in ps_list:
        frappe.delete_doc('Property Setter', n, ignore_permissions=True, force=True)
    frappe.db.commit()
    print(f'    CF удалено: {len(cf_list)}, PS удалено: {len(ps_list)}')


def apply_customize_form():
    """Через Customize Form API — скрытие и переименование."""
    print('[2/4] Customize Form API...')
    cf = frappe.get_doc('Customize Form')
    cf.doc_type = 'Lead'
    cf.run_method('fetch_to_customize')
    hidden_count = 0
    for f in cf.fields:
        if f.fieldname in HIDE:
            f.hidden = 1
            hidden_count += 1
        if f.fieldname in SECTION_LABELS:
            f.label = SECTION_LABELS[f.fieldname]
    cf.run_method('save_customization')
    frappe.db.commit()
    print(f'    скрыто: {hidden_count}, переименовано: {len(SECTION_LABELS)}')


def create_custom_fields():
    """Custom Field DocType — создаём mw_* поля."""
    print('[3/4] Custom Fields...')
    existing = {
        r.fieldname
        for r in frappe.get_all(
            'Custom Field', filters={'dt': 'Lead'}, fields=['fieldname']
        )
    }
    for fd in CUSTOM_FIELDS:
        fn = fd['fieldname']
        if fn in existing:
            doc = frappe.get_doc('Custom Field', f'Lead-{fn}')
            for k, v in fd.items():
                setattr(doc, k, v)
            doc.save(ignore_permissions=True)
            print(f'    updated: {fn}')
        else:
            doc = frappe.get_doc({'doctype': 'Custom Field', 'dt': 'Lead', **fd})
            doc.insert(ignore_permissions=True)
            print(f'    created: {fn}')
    frappe.db.commit()


def apply_client_script():
    """Client Script — синхронизация mw_full_name → first_name."""
    print('[4/4] Client Script...')
    existing = frappe.db.get_value('Client Script', {'dt': 'Lead'}, 'name')
    if existing:
        frappe.db.set_value('Client Script', existing, 'script', CLIENT_SCRIPT)
        frappe.db.set_value('Client Script', existing, 'enabled', 1)
        print(f'    updated: {existing}')
    else:
        doc = frappe.get_doc({
            'doctype': 'Client Script',
            'dt': 'Lead',
            'script': CLIENT_SCRIPT,
            'enabled': 1,
            'view': 'Form',
        })
        doc.insert(ignore_permissions=True)
        print(f'    created: {doc.name}')
    frappe.db.commit()


def execute():
    print('=== Lead Form Setup ===\n')
    reset()
    apply_customize_form()
    create_custom_fields()
    apply_client_script()
    print('\n✅ Готово.')
    print('Запусти: bench --site frontend clear-cache')
