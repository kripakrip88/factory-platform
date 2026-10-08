# -*- coding: utf-8 -*-
"""Одно понятие — одно слово, без английского (разбор UX, шаг 39, 05.10.2026).

ЗАЧЕМ. Перевод ядра называет одно понятие разными словами: сделка и
«возможность», задача, «дело», «активность» и «мероприятие», поставщик и
«продавец», снабженец и «покупатель» / «закупщик», регион и «состояние»; где
перевода нет — английское «Email», «Lost». Словарь завода (документ разбора,
«Слова»): сделка, проиграно, задача, эл. почта, закупки, менеджер, поставщик,
снабженец, регион.

Поставщику слова завода не показываем: портал (/my/purchase) и письмо ему
(кнопка «Просмотреть …») остаются со словами ядра — ссылки на них из файлов
слов выброшены.

ПОЧЕМУ НЕ СВОЙ ru.po (проверено 20.09 и по коду ядра Odoo 19, 05.10):
  • строки кода (_() в Python, _t() и тексты шаблонов в JS) процесс читает
    только из <модуль>/i18n(_extra)/ru.po САМОГО модуля:
    CodeTranslations._get_code_translations → get_po_paths → file_path, а
    file_path для загруженного модуля ищет только в его __path__ — файл,
    лежащий в другом модуле, не найдётся;
  • строки базы импорт ключует по xml-id, но без перезаписи оставляет уже
    записанный русский — свой файл ложится только в пустые места;
  • переопределить string= поля в _inherit — нельзя: при смене en_US
    upsert_en сбрасывает ВСЕ переводы подписи, а -u модуля-хозяина (crm,
    base…) возвращает его русский поверх (грабли шага 31 с date_deadline).

КАК.
  1. Файлы слов i18n_words/<модуль>.po — записи из ru.po ядра с нашим msgstr
     (как поменять слово — в шапке каждого файла). Это и есть словарь: одно
     слово меняется одной правкой.
  2. Строки кода. При импорте модуля оборачиваем загрузчики CodeTranslations
     (_load_python_translations, _load_web_translations): после штатной
     загрузки перевода модуля доливаем строки кода его файла слов. Действует
     в каждом процессе Odoo, загрузившем pmk_theme; deploy.sh перезапускает
     Odoo. Браузер заберёт новые строки сам: хэш /web/webclient/translations
     считается от содержимого (ir.http._get_web_translations_hash).
  3. Строки базы — подписи и подсказки полей, значения списков, имена
     моделей, термины видов. ir.module.module._load_module_terms: после
     штатной загрузки переводов, если в списке есть pmk_theme и язык ru_RU,
     грузим файлы слов с перезаписью. Срабатывает:
       • на каждом -u pmk_theme — то есть на каждом deploy.sh;
       • на -u любого модуля, от которого тема зависит (crm, base, mail…):
         тема обновляется следом за ним, и слова ложатся поверх его перевода;
       • на «Загрузить перевод» / «Обновить» языка и на включении языка.
     Перезапись не трогает записи noupdate (подтипы ленты, типы задач) — их
     меняет пункт 4.
  4. DATA_WORDS — данные noupdate и две подписи с общим msgid: точечно, по
     xml-id, и только если в базе стоит штатное слово. Ручную правку не
     затираем, повторный прогон ничего не делает.
  5. Заголовки окон и пункты «Действия» / «Печать» — ACTION_TITLES
     (ir_actions_act_window.py, применяет и ir_actions.py): имена действий в
     файлы слов не входят.

Проверено сухим прогоном по боевой базе (05.10.2026, только чтение): все
xml-id из файлов есть, ни один не noupdate; у всех 94 видов число терминов
en и ru совпадает (иначе перезапись термина откатила бы весь вид на
английский — TranslationImporter.save строит словарь по позициям); меняются
только наши термины.

ВЕРНУТЬ. Одно слово — удалить запись из файла слов и выложить; строки кода
вернутся сами (новый процесс), строку базы вернёт загрузка перевода модуля с
перезаписью: режим разработчика, Настройки → Переводы → Языки → Русский →
«Обновить», галочка «Перезаписать существующие термины». Всё разом —
удалить этот файл, его импорт в models/__init__.py и каталог i18n_words,
выложить и так же обновить перевод. DATA_WORDS обратно — SQL по той же
таблице. Список «было → стало» — docs/disabled-features.md, шаг 39.
"""
import logging
import os

from odoo import api, models
from odoo.tools import SQL
from odoo.tools.misc import ReadonlyDict, file_open
from odoo.tools.translate import (
    JAVASCRIPT_TRANSLATION_COMMENT,
    PYTHON_TRANSLATION_COMMENT,
    CodeTranslations,
    TranslationImporter,
    code_translations,
)

_logger = logging.getLogger(__name__)

LANG = "ru_RU"
WORDS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n_words")
# Путь от каталога модулей — так файл открывает и импорт перевода ядра.
WORDS_PATH = "pmk_theme/i18n_words/%s.po"

# (xml-id, поле, штатное русское слово, наше). Подтипы ленты и типы задач
# записаны noupdate: импорт с перезаписью у них оставляет то, что в базе.
# Подпись вида «Активность» в переключателе видов — «Задачи», а в ленте и
# часиках у той же строки «Activity» нужна «Задача»: один msgid в файле слов
# не даст двух слов, поэтому подпись вида — здесь.
DATA_WORDS = [
    # Лента сделки: «Лид/возможность создана» и подписки на события.
    ("crm.mt_lead_create", "name", "Возможность создана", "Сделка создана"),
    ("crm.mt_lead_create", "description", "Лид/возможность создана", "Сделка создана"),
    ("crm.mt_lead_lost", "name", "Возможность потеряна", "Сделка проиграна"),
    ("crm.mt_lead_lost", "description", "Возможность потеряна", "Сделка проиграна"),
    ("crm.mt_lead_won", "name", "Возможность выиграна", "Сделка выиграна"),
    ("crm.mt_lead_won", "description", "Возможность выиграна", "Сделка выиграна"),
    ("crm.mt_lead_restored", "name", "Возможность восстановлена", "Сделка восстановлена"),
    ("crm.mt_lead_restored", "description", "Возможность восстановлена", "Сделка восстановлена"),
    ("crm.mt_salesteam_lead", "name", "Возможность создана", "Сделка создана"),
    ("crm.mt_salesteam_lead_lost", "name", "Возможность потеряна", "Сделка проиграна"),
    ("crm.mt_salesteam_lead_won", "name", "Возможность выиграна", "Сделка выиграна"),
    ("crm.mt_salesteam_lead_restored", "name", "Возможность восстановлена", "Сделка восстановлена"),
    ("crm.mt_salesteam_lead_stage", "name", "Стадия возможности изменена", "Стадия сделки изменена"),
    ("mail.mt_activities", "name", "Активности", "Задачи"),
    # RFQ — с шага З-6 (09.10.2026) «Заявка» (было «Запрос КП», pmk_purchase,
    # миграция 19.0.1.0.1); у подтипов ленты закупки осталось «ЗП». Вторая
    # строка — поверх нашего прежнего слова, оно уже стоит в базе.
    ("purchase.mt_rfq_sent", "name", "ЗП отправлен", "Заявка отправлена"),
    ("purchase.mt_rfq_sent", "name", "Запрос КП отправлен", "Заявка отправлена"),
    ("purchase.mt_rfq_confirmed", "name", "ЗП подтвержден", "Заказ подтверждён"),
    ("purchase.mt_rfq_approved", "name", "ЗП одобрен", "Заказ одобрен"),
    # Состояние «Отменён» закупки — с «ё», как у счёта покупателю ниже. Здесь,
    # а не в файле слов: у «Cancelled» тот же msgid у строки кода портала
    # (поставщику — слова ядра).
    ("purchase.selection__purchase_order__state__cancel", "name", "Отменен", "Отменён"),
    ("purchase.selection__purchase_report__state__cancel", "name", "Отменен", "Отменён"),
    # Тип задачи «Email» (перевода у ядра нет).
    ("mail.mail_activity_data_email", "name", "Email", "Письмо"),
    ("mail.mail_activity_data_email", "summary", "Email", "Письмо"),
    # Тип To-Do: у ядра он «Задача» — тем же словом, что и всё понятие
    # («Тип задачи: Задача»). Ядро держит его для напоминаний из верхнего
    # меню и палитры команд (подсказка окна — «Напоминание: ...»).
    ("mail.mail_activity_data_todo", "name", "Задача", "Напоминание"),
    ("mail.mail_activity_data_todo", "summary", "Задача", "Напоминание"),
    # Подпись вида в переключателе видов (ir.ui.view.get_view_info берёт её
    # из списка значений поля type) и в техническом списке видов действия.
    ("mail.selection__ir_ui_view__type__activity", "name", "Активность", "Задачи"),
    ("mail.selection__ir_actions_act_window_view__view_mode__activity", "name", "Активность", "Задачи"),
    # ─── Шаг З-2 (08.10.2026): заказ клиента — «Счёт покупателю» ────────
    # Состояния счёта словами завода. Здесь, а не в файле слов: у «Quotation»
    # и «Sales Order» один msgid со строкой кода (type_name) и именем модели —
    # им нужно «Счёт покупателю» (i18n_words/sale.po), состоянию — другое.
    # Те же четыре у отчёта продаж (sale.report) — одно понятие.
    ("sale.selection__sale_order__state__draft", "name", "Коммерческое предложение", "Черновик"),
    ("sale.selection__sale_order__state__sent", "name", "Коммерческое предложение отправлено",
     "Выставлен, ждём оплату"),
    ("sale.selection__sale_order__state__sale", "name", "Заказ на продажу", "В работе (оплачен)"),
    ("sale.selection__sale_order__state__cancel", "name", "Отменен", "Отменён"),
    ("sale.selection__sale_report__state__draft", "name", "Коммерческое предложение", "Черновик"),
    ("sale.selection__sale_report__state__sent", "name", "Коммерческое предложение отправлено",
     "Выставлен, ждём оплату"),
    ("sale.selection__sale_report__state__sale", "name", "Заказ на продажу", "В работе (оплачен)"),
    ("sale.selection__sale_report__state__cancel", "name", "Отменен", "Отменён"),
    # Единица штучного: строки счёта покупателю и 82 штучных товара — «шт»,
    # как в КП и на заводе (было «Единицы»). Печать КП и доборок единицу не
    # берёт (pmk_bridge: «шт» в шаблоне; pmk_calc: свои единицы).
    ("uom.product_uom_unit", "name", "Единицы", "шт"),
]

# Язык в «Моих предпочтениях»: «Russian / русский язык» → «Русский».
# Запись base.lang_ru грузится из res.lang.csv без noupdate: -u base вернёт
# штатное имя, и этот же крючок (тема обновляется следом) поставит наше.
LANG_NAME = ("base.lang_ru", "Russian / русский язык", "Русский")


def words_modules():
    """Штатные модули, для которых есть файл слов."""
    try:
        names = os.listdir(WORDS_DIR)
    except OSError:
        return []
    return sorted(name[:-3] for name in names if name.endswith(".po"))


def code_words(module_name, lang, comment):
    """{msgid: msgstr} строк кода модуля из его файла слов.

    ``comment`` — PYTHON_TRANSLATION_COMMENT или JAVASCRIPT_TRANSLATION_COMMENT.
    Нет файла, другой язык, файл не читается — пусто: штатный перевод модуля
    остаётся как был, ошибка — в журнал.
    """
    if lang != LANG or module_name not in words_modules():
        return {}
    try:
        with file_open(WORDS_PATH % module_name, mode="rb") as fileobj:
            return CodeTranslations._read_code_translations_file(
                fileobj, lambda row: row.get("value") and comment in row["comments"])
    except Exception:  # noqa: BLE001 — слова не должны ронять перевод модуля
        _logger.exception("pmk_theme: не прочитан файл слов %s", WORDS_PATH % module_name)
        return {}


def _wrap_code_loaders():
    """Обернуть загрузчики строк кода — один раз на процесс."""
    if getattr(CodeTranslations, "_pmk_words", False):
        return
    load_python = CodeTranslations._load_python_translations
    load_web = CodeTranslations._load_web_translations

    def _load_python_translations(self, module_name, lang):
        load_python(self, module_name, lang)
        words = code_words(module_name, lang, PYTHON_TRANSLATION_COMMENT)
        if words:
            merged = dict(self.python_translations[(module_name, lang)])
            merged.update(words)
            self.python_translations[(module_name, lang)] = ReadonlyDict(merged)

    def _load_web_translations(self, module_name, lang):
        load_web(self, module_name, lang)
        words = code_words(module_name, lang, JAVASCRIPT_TRANSLATION_COMMENT)
        if words:
            merged = {message["id"]: message["string"]
                      for message in self.web_translations[(module_name, lang)]["messages"]}
            merged.update(words)
            self.web_translations[(module_name, lang)] = ReadonlyDict({
                "messages": tuple(
                    ReadonlyDict({"id": src, "string": value})
                    for src, value in merged.items()),
            })

    CodeTranslations._load_python_translations = _load_python_translations
    CodeTranslations._load_web_translations = _load_web_translations
    CodeTranslations._pmk_words = True
    # Переводы, загруженные до нас (модули грузятся раньше темы), — выбросить:
    # следующий запрос перечитает их уже со словами.
    for module_name in words_modules():
        code_translations.python_translations.pop((module_name, LANG), None)
        code_translations.web_translations.pop((module_name, LANG), None)


_wrap_code_loaders()


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    @api.model
    def _load_module_terms(self, modules, langs, overwrite=False):
        super()._load_module_terms(modules, langs, overwrite=overwrite)
        if "pmk_theme" in modules and LANG in langs:
            # Слова — не повод ронять обновление модулей: сбой откатывается до
            # точки сохранения, остаётся штатный перевод, ошибка — в журнал
            # (deploy.sh показывает строки ERROR).
            try:
                with self.env.cr.savepoint():
                    self._pmk_apply_words()
            except Exception:  # noqa: BLE001
                _logger.exception("pmk_theme: слова завода не легли — остался штатный перевод")

    @api.model
    def _pmk_apply_words(self):
        """Слова завода в базу: файлы слов с перезаписью, затем DATA_WORDS."""
        if not self.env["res.lang"]._lang_get(LANG):
            return
        importer = TranslationImporter(self.env.cr, verbose=False)
        for module_name in words_modules():
            importer.load_file(WORDS_PATH % module_name, LANG)
        importer.save(overwrite=True)
        self._pmk_apply_data_words()
        # save() чистит только кэш «default»; подписи полей живут в «stable»
        # (ir.model.fields._get_fields_cached), собранные виды — в «templates».
        self.env.registry.clear_cache("stable", "templates")

    @api.model
    def _pmk_apply_data_words(self):
        """DATA_WORDS и имя языка — только там, где стоит штатное слово."""
        cr = self.env.cr
        for xmlid, fname, old, new in DATA_WORDS:
            record = self.env.ref(xmlid, raise_if_not_found=False)
            field = record._fields.get(fname) if record else None
            if not field or not field.store or field.translate is not True:
                continue
            cr.execute(SQL(
                "UPDATE %(table)s SET %(col)s = %(col)s || jsonb_build_object(%(lang)s, %(new)s::text)"
                " WHERE id = %(id)s AND %(col)s->>%(lang)s = %(old)s",
                table=SQL.identifier(record._table), col=SQL.identifier(fname),
                lang=LANG, new=new, id=record.id, old=old,
            ))
            if cr.rowcount:
                record.invalidate_recordset([fname])
        xmlid, old, new = LANG_NAME
        lang = self.env.ref(xmlid, raise_if_not_found=False)
        if lang and lang.name == old:
            lang.name = new
