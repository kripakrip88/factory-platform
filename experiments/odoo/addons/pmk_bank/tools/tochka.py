# -*- coding: utf-8 -*-
"""Клиент API Точки — только чтение (счета и выписки).

Документация: https://developers.tochka.com/docs/tochka-api/ . Ключ — JWT из
интернет-банка («Интеграции и API») с разрешениями ReadAccountsBasic +
ReadStatements + ManageWebhookData, БЕЗ CreatePaymentForSign/CreatePaymentOrder
(проверено 14.10.2026: запрос к платёжкам — 403 «Forbidden by consent»).
Методов платежей здесь нет и не будет.

Выписка у Точки асинхронная: POST /statements → statementId, потом опрос
GET …/statements/{id}, пока статус не «Ready». В выписке и приход, и расход —
берём только creditDebitIndicator = Credit со статусом Booked.

⚠️ Сертификат enter.tochka.com — УЦ Минцифры, проверяем по
data/russian_trusted_ca.pem (как у Модульбанка).
⚠️ JWT без refresh: через год перевыпуск в интернет-банке, и при этом меняется
client_id — вебхуки перерегистрировать.
"""
import time

import requests

from .modulbank import CA_FILE, ModulbankError as BankError

API = "https://enter.tochka.com/uapi"
READY_WAIT = 30          # секунд ждать готовности выписки
READY_STEP = 2


class Tochka:

    def __init__(self, token, timeout=30):
        self.token = token
        self.timeout = timeout

    def _req(self, method, path, payload=None):
        try:
            resp = requests.request(
                method, f"{API}/{path}", json=payload, timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.token}"}, verify=CA_FILE)
        except requests.RequestException as exc:
            raise BankError(f"нет связи с банком: {exc}") from exc
        if resp.status_code != 200:
            raise BankError(f"банк ответил {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("Data") or {}

    def accounts(self):
        out = []
        for acc in self._req("GET", "open-banking/v1.0/accounts").get("Account") or []:
            acc_id = acc.get("accountId") or ""
            out.append({"number": acc_id.split("/")[0], "id": acc_id,
                        "name": acc.get("accountSubType"), "status": acc.get("status"),
                        "customer": acc.get("customerCode")})
        return out

    def incoming(self, account_id, date_from, date_to=None):
        """Зачисленные поступления на счёт за период (yyyy-mm-dd), нормализованные."""
        today = time.strftime("%Y-%m-%d")
        init = self._req("POST", "open-banking/v1.0/statements", {"Data": {"Statement": {
            "accountId": account_id, "startDateTime": date_from, "endDateTime": date_to or today}}})
        st_id = (init.get("Statement") or {}).get("statementId")
        if not st_id:
            raise BankError("банк не вернул номер выписки")
        waited = 0
        while True:
            data = self._req("GET", f"open-banking/v1.0/accounts/{account_id}/statements/{st_id}")
            st = (data.get("Statement") or [{}])[0]
            if st.get("status") == "Ready":
                break
            if st.get("status") == "Error" or waited >= READY_WAIT:
                raise BankError("выписка не готова (%s)" % st.get("status"))
            time.sleep(READY_STEP)
            waited += READY_STEP
        out = []
        for t in st.get("Transaction") or []:
            if t.get("creditDebitIndicator") != "Credit" or t.get("status") != "Booked":
                continue
            party = t.get("DebtorParty") or {}
            amount = t.get("Amount") or {}
            out.append({
                "id": t.get("transactionId") or t.get("paymentId"),
                "executed": (t.get("documentProcessDate") or "")[:10],
                "amount": amount.get("amount") or 0.0,
                "currency": amount.get("currency"),
                "payer_name": party.get("name"),
                "payer_inn": party.get("inn"),
                "purpose": t.get("description"),
                "doc_number": t.get("documentNumber"),
                "raw": t,
            })
        return out
