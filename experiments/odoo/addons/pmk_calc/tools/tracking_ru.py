# -*- coding: utf-8 -*-
"""Старая история изменений расчётов и доборок — по-русски (разбор UX, шаг 30).

КТО ПИСАЛ. Модуль tracking_manager (vendor/tracking_manager, OCA) кладёт в
ленту документа готовый HTML по шаблону tracking_manager.track_o2m_m2m_template
в МОМЕНТ изменения: «New :», «Delete :», «Change :», подсказка стрелки
«Changed». Перевод шаблона (vendor/tracking_manager/i18n_extra/ru.po) чинит
только новые записи — старые лежат в mail_message.body такими, какими их
написали.

ЧТО ЕЩЁ НЕЧИТАЕМО В СТАРЫХ ЗАПИСЯХ (до правки модуля, шаг 30):
  • «pmk.metal.spec.line(43, 44, 45)» — состав изделия (one2many) модуль
    печатал служебным видом набора записей. Теперь — число строк;
  • «pmk.dobor.order.line,20» — у позиции доборки не было своего имени, а в
    момент заведения нет и названия («Доборка N» ставит create после
    super()). Теперь — название позиции. У удалённой — название из той же
    истории («Изменено: … Название доборки : → Доборка 2»), если оно там
    есть, иначе слово «доборка».

И ЗАПИСЬ ЯДРА О СОЗДАНИИ (доводка шага 30): «Спецификация металлопроката
created», «Заказ доборных элементов created» — документы, заведённые
скриптом без языка; рядом в той же ленте теперь «Добавлено: …». Ядро по-
русски пишет «Создано: …» — так и приводим (created_ru).

Функции чистые: ими пользуются миграция pmk_calc 19.0.1.0.4 и тест
tests/test_step30_tracking.py.

СЛОВО ДОКУМЕНТА (разбор UX, шаг 39, 05.10.2026): «расчёт», а не
«спецификация» — так называется модель с этого шага. Запись ядра о создании
хранит имя модели, каким оно было в момент записи: «Создано: Спецификация
металлопроката» → «Создано: Расчёт металлопроката» (renamed_created;
миграция 19.0.1.0.5, тест tests/test_step39_words.py).
"""
import re
from html import unescape

from markupsafe import escape

# Подписи шаблона — точные строки из vendor/tracking_manager/views/
# message_template.xml, как их сохранил mail_message.body (атрибут role="img"
# у стрелки чистка HTML снимает, поэтому сверяем по классу и подсказке).
LABELS = (
    ("<b>New :</b>", "<b>Добавлено:</b>"),
    ("<b>Delete :</b>", "<b>Удалено:</b>"),
    ("<b>Change :</b>", "<b>Изменено:</b>"),
    ('fa-long-arrow-right" title="Changed"', 'fa-long-arrow-right" title="Изменено"'),
)
SPEC_LINES = re.compile(r"pmk\.metal\.spec\.line\(([\d,\s]*)\)")
DOBOR_LINE = re.compile(r"pmk\.dobor\.order\.line,(\d+)")
# «Изменено: <позиция> · Название доборки : <было> → <стало>» — так модуль
# записывал «Доборку N» сразу после заведения позиции. Отсюда название
# позиции, которой в базе уже нет.
DOBOR_TITLE_SET = re.compile(
    r"<b>(?:Change :|Изменено:)</b>\s*pmk\.dobor\.order\.line,(\d+)\s*<ul>\s*<li>\s*"
    r"Название доборки :\s*.*?<div[^>]*>\s*</div>\s*(.*?)\s*</li>",
    re.S,
)
# Позиция удалена, и названия в истории нет — слово рода, а не номер записи.
NO_TITLE = "доборка"
# Запись ядра mail о создании документа (mail.thread._creation_message):
# «<p>%s created</p>», по-русски — «<p>Создано: %s</p>» (перевод ядра,
# mail/i18n/ru.po). Английской её пишет скрипт без языка в контексте
# (OdooBot) — так заведены первые расчёты, доборки, раскрой и задание
# лазеру. Только простой текст внутри <p>: чужие записи с разметкой
# («Bank Account <a …>#1</a> created») не наши и не трогаются.
CREATED = re.compile(r"^<p>([^<]+) created</p>$")
CREATED_RU = "<p>Создано: %s</p>"
CREATED_RU_RE = re.compile(r"^<p>Создано: ([^<]+)</p>$")
# Имена моделей до шага 39 → нынешние (pmk_calc/models/metal_spec.py).
RENAMED_MODELS = {
    "Спецификация металлопроката": "Расчёт металлопроката",
    "Изделие спецификации": "Изделие расчёта",
}


def dobor_ids(text):
    """Номера позиций доборки, упомянутых служебным видом."""
    return {int(n) for n in DOBOR_LINE.findall(text or "")}


def titles_from_history(bodies):
    """{номер позиции: последнее название} из записей «Название доборки».

    ``bodies`` — тела сообщений в порядке их записи (по id): позицию могли
    переименовать, верное — последнее. Пустое новое значение не берём.
    """
    titles = {}
    for body in bodies:
        for line_id, title in DOBOR_TITLE_SET.findall(body or ""):
            title = unescape(re.sub(r"<[^>]+>", "", title)).strip()
            if title:
                titles[int(line_id)] = title
    return titles


def rewrite(text, titles, html=True):
    """Текст записи истории по-русски.

    ``titles`` — {номер позиции доборки: название}. ``html`` — тело сообщения
    (название экранируется); для старых значений отслеживания
    (mail_tracking_value.*_value_char) — False, там простой текст.
    Повторный вызов ничего не меняет.
    """
    if not text:
        return text
    out = text
    if html:
        for old, new in LABELS:
            out = out.replace(old, new)
    out = SPEC_LINES.sub(
        lambda m: str(len([n for n in m.group(1).split(",") if n.strip()])), out)

    def _title(match):
        title = titles.get(int(match.group(1))) or NO_TITLE
        return str(escape(title)) if html else title

    return DOBOR_LINE.sub(_title, out)


def created_ru(body):
    """Запись ядра «… created» — по-русски, как её пишет ядро: «Создано: …».

    Название документа уже экранировано в теле — переносим его как есть.
    Другое тело возвращается без изменений; повторный вызов ничего не меняет.
    """
    match = CREATED.match(body or "")
    return CREATED_RU % match.group(1) if match else body


def renamed_created(body):
    """Запись о создании — с нынешним именем модели (шаг 39).

    «<p>Создано: Спецификация металлопроката</p>» → «<p>Создано: Расчёт
    металлопроката</p>». Английская запись «… created» сначала приводится к
    русской (created_ru). Только запись целиком и только имена из
    RENAMED_MODELS: «Создано: Изделие спецификации КМ1» или текст клиента со
    словом «спецификация» (чертёж клиента) не трогаются. Повтор ничего не
    меняет.
    """
    body = created_ru(body)
    match = CREATED_RU_RE.match(body or "")
    new = RENAMED_MODELS.get(match.group(1)) if match else None
    return CREATED_RU % new if new else body
