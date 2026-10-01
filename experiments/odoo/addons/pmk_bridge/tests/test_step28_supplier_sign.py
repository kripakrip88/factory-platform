# -*- coding: utf-8 -*-
"""Признак «поставщик» (pmk_is_supplier) — разбор UX, шаг 28.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Здесь — штатная часть
признака: supplier_rank у самого контрагента или у его компании. Реестр
прайсов дописывает и проверяет pmk_purchase (test_step28_partner_mailing.py).
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSupplierSignStep28(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        cls.supplier = Partner.create({"name": "ООО «Поставщик 28»", "is_company": True,
                                       "supplier_rank": 1})
        cls.supplier_person = Partner.create({"name": "Менеджер поставщика 28",
                                              "parent_id": cls.supplier.id})
        cls.client = Partner.create({"name": "ООО «Клиент 28»", "is_company": True})
        cls.client_person = Partner.create({"name": "Инженер клиента 28",
                                            "parent_id": cls.client.id})

    def test_by_rank_and_company(self):
        self.assertTrue(self.supplier.pmk_is_supplier)
        self.assertFalse(self.supplier_person.supplier_rank,
                         "Ранг контактному лицу не передаётся — потому и смотрим на компанию.")
        self.assertTrue(self.supplier_person.pmk_is_supplier,
                        "Контактное лицо поставщика — сторона поставщика.")
        self.assertFalse(self.client.pmk_is_supplier)
        self.assertFalse(self.client_person.pmk_is_supplier)
        # Свой ранг у человека (заказ поставщику оформили на него) — тоже.
        self.client_person.supplier_rank = 1
        self.assertTrue(self.client_person.pmk_is_supplier)

    def test_follows_rank_and_writes_nothing(self):
        """Признак вычисляемый: идёт за рангом и в базу ничего не пишет."""
        self.assertFalse(self.env["res.partner"]._fields["pmk_is_supplier"].store)
        self.supplier.supplier_rank = 0
        self.assertFalse(self.supplier.pmk_is_supplier)
        self.assertFalse(self.supplier_person.pmk_is_supplier,
                         "Вслед за компанией — и её контактное лицо.")
