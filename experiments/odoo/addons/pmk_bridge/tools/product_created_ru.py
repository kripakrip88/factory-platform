# -*- coding: utf-8 -*-
"""«Product created» в ленте товара — по-русски (разбор UX, шаг 53, 07.10.2026).

ЧТО. Справочник заливался скриптом без языка в контексте (pmk_bridge,
20–23.09.2026), и ядро mail записало создание каждого товара по-английски:
«<p>Product created</p>» у шаблона товара и «<p>Product Variant created</p>»
у варианта. Боевая база, SELECT 07.10.2026: 753 и 757 записей ленты (тип
notification, подтип «Заметка», значений отслеживания нет) — «около 1500»
из вопроса приёмки шага 30. Антон: «перевести однозначно».

КАК ПИШЕТ ЯДРО ПО-РУССКИ. mail.thread._creation_message: «%s created» с
именем модели, перевод ядра (mail/i18n/ru.po) — «Создано: %s», имя модели
по-русски — «Товар» и «Вариант товара». Значит, «<p>Создано: Товар</p>»
(рядом в ленте уже есть 1 запись «Создано: Вариант товара» — ровно так).
Имена берём из ir_model (en_US → ru_RU), а не пишем строкой: переименуют
модель — замена пойдёт по новому имени.

ЧТО НЕ ТРОГАЕМ. Только запись целиком и только у product.template и
product.product: «Product Category created» (28 записей у категорий),
«Contact created» и прочая история — как была. Через SQL: это история,
пересчитывать в ней нечего (тот же приём — pmk_calc/tools/tracking_ru.py,
миграции pmk_calc 19.0.1.0.4 и 19.0.1.0.5).

Повторный вызов ничего не меняет (английского тела уже нет — 0 записей).
Вернуть: обратный UPDATE mail_message по тем же моделям
(«<p>Создано: Товар</p>» → «<p>Product created</p>»).
"""
from markupsafe import escape

MODELS = ("product.template", "product.product")
# Так тело записи хранит ядро: имя модели внутри <p>, экранировано.
CREATED_EN = "<p>%s created</p>"
CREATED_RU = "<p>Создано: %s</p>"


def model_names(cr, models=MODELS):
    """{модель: (имя en_US, имя ru_RU)} — из ir_model; без перевода — пропуск."""
    cr.execute("SELECT model, name->>'en_US', name->>'ru_RU' FROM ir_model WHERE model IN %s",
               [tuple(models)])
    return {model: (en, ru) for model, en, ru in cr.fetchall() if en and ru}


def translate_product_created(cr, models=MODELS):
    """Записи «… created» у товаров — «Создано: …». Возвращает {модель: записей}."""
    changed = {}
    for model, (en, ru) in sorted(model_names(cr, models).items()):
        cr.execute(
            "UPDATE mail_message SET body = %s"
            " WHERE model = %s AND message_type = 'notification' AND body = %s",
            [CREATED_RU % escape(ru), model, CREATED_EN % escape(en)])
        changed[model] = cr.rowcount
    return changed
