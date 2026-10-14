# -*- coding: utf-8 -*-
"""Печатная форма счёта из МоегоСклада (PDF) — для уведомления о поступлении.

Счета покупателям в Odoo пришли из МоегоСклада (pmk_moysklad) и помнят свой id
там (sale.order.pmk_ms_id). МойСклад печатает документ по шаблону:
POST entity/invoiceout/{id}/export/ → 303 с адресом готового файла, файл
забирается без ключа. Печать документ в МоёмСкладе не меняет.

Шаблон — «Счет №» (общий) для всех организаций, решение Антона 14.10.2026:
реквизиты в нём берутся из организации документа (Чулков, Бутов, Астахов).
"""
import requests

API = "https://api.moysklad.ru/api/remap/1.2"
TEMPLATE = "Счет №"
TIMEOUT = 60


class PrintError(Exception):
    pass


class MoySkladPrint:

    def __init__(self, token, template=TEMPLATE):
        self.token = token
        self.template = template
        self._tpl_href = None

    def _headers(self):
        # МойСклад требует gzip; без Accept-Encoding отвечает ошибкой.
        return {"Authorization": "Bearer " + self.token, "Accept-Encoding": "gzip",
                "Content-Type": "application/json"}

    def _template_href(self):
        if self._tpl_href:
            return self._tpl_href
        try:
            rows = requests.get(f"{API}/entity/invoiceout/metadata/customtemplate",
                                headers=self._headers(), timeout=TIMEOUT).json().get("rows") or []
        except (requests.RequestException, ValueError) as exc:
            raise PrintError(f"МойСклад: шаблоны не получены: {exc}") from exc
        found = [r["meta"]["href"] for r in rows if r.get("name") == self.template]
        if not found:
            raise PrintError(f"МойСклад: нет шаблона «{self.template}»")
        self._tpl_href = found[0]
        return self._tpl_href

    def invoice_pdf(self, ms_id):
        """PDF счёта покупателю по его id в МоёмСкладе (байты)."""
        body = {"template": {"meta": {"href": self._template_href(), "type": "customtemplate",
                                      "mediaType": "application/json"}},
                "extension": "pdf"}
        try:
            resp = requests.post(f"{API}/entity/invoiceout/{ms_id}/export/", json=body,
                                 headers=self._headers(), timeout=TIMEOUT, allow_redirects=False)
            if resp.status_code != 303 or not resp.headers.get("Location"):
                raise PrintError(f"МойСклад: печать не удалась ({resp.status_code}): {resp.text[:150]}")
            # Файл — по временной ссылке, без ключа (ключ на чужой адрес не шлём).
            pdf = requests.get(resp.headers["Location"], timeout=TIMEOUT)
            pdf.raise_for_status()
        except requests.RequestException as exc:
            raise PrintError(f"МойСклад: нет связи: {exc}") from exc
        if not pdf.content.startswith(b"%PDF"):
            raise PrintError("МойСклад: вернул не PDF")
        return pdf.content
