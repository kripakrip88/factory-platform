# -*- coding: utf-8 -*-
"""Клиент API Модульбанка — только чтение (account-info, operation-history).

Документация: https://api.modulbank.ru/ . Токен — из личного кабинета, с
правами account-info + operation-history + web-notifications, БЕЗ
operation-upload (загрузка и подписание платёжек). Методов платежей здесь нет
и не будет — для черновиков платёжек отдельный токен и отдельный код.

⚠️ Сертификат api.modulbank.ru выдан российским УЦ Минцифры, которому Python
не доверяет: проверяем по своему файлу data/russian_trusted_ca.pem, а не
отключаем проверку.
⚠️ category у Модульбанка «наоборот»: Debet — ВХОДЯЩИЕ, Credit — исходящие.
Даты в ответе — московское время.
"""
import logging
import os

import requests

_logger = logging.getLogger(__name__)

API = "https://api.modulbank.ru/v1"
CA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "data", "russian_trusted_ca.pem")
INCOMING = "Debet"
RECEIVED = ("Received", "PayReceived")   # деньги зачислены
PAGE = 50                                # предел records у банка


class ModulbankError(Exception):
    pass


class Modulbank:

    def __init__(self, token, timeout=30):
        self.token = token
        self.timeout = timeout

    def _post(self, path, payload=None):
        try:
            resp = requests.post(
                f"{API}/{path}", json=payload or {}, timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.token}"}, verify=CA_FILE)
        except requests.RequestException as exc:
            raise ModulbankError(f"нет связи с банком: {exc}") from exc
        if resp.status_code != 200:
            raise ModulbankError(f"банк ответил {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def accounts(self):
        """[(номер счёта, id в банке, название, категория, статус)] всех компаний токена."""
        out = []
        for company in self._post("account-info"):
            for acc in company.get("bankAccounts") or []:
                out.append({"number": acc.get("number"), "id": acc.get("id"),
                            "name": acc.get("accountName"), "category": acc.get("category"),
                            "status": acc.get("status")})
        return out

    def incoming(self, account_id, date_from):
        """Зачисленные поступления на счёт с даты (yyyy-mm-dd), все страницы.

        Банк сортирует по дате проведения по убыванию, и при новых операциях
        страницы сдвигаются — дубли отсекает вызывающий по id операции.
        """
        ops, skip = [], 0
        while True:
            page = self._post(f"operation-history/{account_id}", {
                "category": INCOMING, "from": date_from, "records": PAGE, "skip": skip})
            if not isinstance(page, list):
                raise ModulbankError(f"неожиданный ответ: {str(page)[:200]}")
            ops += [o for o in page if o.get("status") in RECEIVED]
            if len(page) < PAGE:
                return ops
            skip += PAGE
