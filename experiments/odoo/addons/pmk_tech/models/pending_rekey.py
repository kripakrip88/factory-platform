# -*- coding: utf-8 -*-
"""Разнесли позицию «на разнос» — ключи строк ушедших заявок (доводка З-10).

Строка заявки на металл помнит позицию расчёта ключом (pmk_request_key):
у позиции «на разнос» это она сама — linear:pending:pmk.metal.profile:<id>,
у настоящей — карточка товара, linear:<id карточки>. После «Привязать к
существующей» / «Принять в справочник» повторная «Заявка на металл» строит
уже настоящий ключ.

ЧЕРНОВИКИ НЕ ТРОГАЕМ: старая служебная строка уходит, настоящая встаёт
своим товаром (metal_request.py, _pmk_sync_requests) — так и обещано.

УШЕДШИЕ ПОСТАВЩИКУ (не черновик, не отменённая) — переписываем ключ на
настоящий. Иначе повтор не узнал бы в ней уже заказанный металл, завёл бы
новую строку на тот же металл, а старая осталась бы без слова: двойной
заказ. Метка pmk_pending у строки остаётся: по ней повтор понимает, что это
не «единственная строка позиции», а уже заказанная часть, и дозаказывает
только остаток (metal_request.py, _pmk_ordered_pending; плашка расхождения
— так же). Товар строки остаётся служебным «Позиция на разнос»: заказ уже
ушёл, менять его строки — дело снабженца.
"""
from odoo import models


class MetalPendingRekey(models.AbstractModel):
    _inherit = "pmk.metal.pending.mixin"

    def _pmk_pending_resolved(self, target):
        result = super()._pmk_pending_resolved(target)
        tmpl = target and "product_tmpl_id" in target._fields and target.product_tmpl_id
        if not tmpl:
            # У настоящей позиции нет карточки — повтор её не закажет
            # (заметка «нет карточки товара»), переписывать не на что.
            return result
        Line = self.env["purchase.order.line"].sudo()
        for rec in self:
            ident = "pending:%s:%s" % (rec._name, rec.id)
            lines = Line.search([
                ("pmk_request_key", "like", ident),
                ("order_id.state", "not in", ("draft", "cancel")),
            ])
            for line in lines:
                mode, sep, rest = line.pmk_request_key.partition(":")
                # Ключ: «вид:pending:модель:id» или «…:габарит» у листа.
                if not sep or not (rest == ident or rest.startswith(ident + ":")):
                    continue
                line.pmk_request_key = "%s:%s%s" % (mode, tmpl.id, rest[len(ident):])
        return result
