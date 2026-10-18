# -*- coding: utf-8 -*-
"""Фоновый процесс ассистента (18.10.2026) — контейнер odoo-ai-worker.

    odoo shell -c /etc/odoo/odoo.conf -d <база> --no-http < ai_worker.py

Правило Антона 18.10: «доработка не должна нарушать скорость работы системы». Вопрос к
Claude идёт 10–60 с; страница Odoo только ставит его в очередь (pmk.ai.request), а отвечает
этот процесс — до WORKER_THREADS вопросов сразу, у каждого свой курсор базы. Раз в секунду:
отметка «жив», зависшие вопросы → ошибка, новые — в работу. Код модуля обновился —
deploy.sh перезапускает контейнер.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from odoo import SUPERUSER_ID, api
from odoo.addons.pmk_ai.models.ai_chat import WORKER_THREADS

_log = logging.getLogger("pmk_ai.worker")
registry = env.registry  # noqa: F821 — env даёт odoo shell
pool = ThreadPoolExecutor(WORKER_THREADS)
inflight = set()


def handle(request_id):
    try:
        with registry.cursor() as cr:
            api.Environment(cr, SUPERUSER_ID, {})["pmk.ai.chat"]._process_request(request_id)
    except Exception:
        _log.exception("вопрос %s", request_id)
    finally:
        inflight.discard(request_id)


_log.info("фоновый процесс ассистента запущен, база %s, потоков %s", registry.db_name, WORKER_THREADS)
print("pmk_ai worker: база %s, потоков %s" % (registry.db_name, WORKER_THREADS), flush=True)
while True:
    try:
        # Изменения из других процессов (ключ, лимит, модель в «Настройки → Ассистент»):
        # без этого фон отвечал бы со старыми настройками из своего кэша.
        registry = registry.check_signaling()
        with registry.cursor() as cr:
            ids = api.Environment(cr, SUPERUSER_ID, {})["pmk.ai.chat"]._worker_tick(WORKER_THREADS - len(inflight))
        for request_id in ids:
            inflight.add(request_id)
            pool.submit(handle, request_id)
    except Exception:
        _log.exception("цикл очереди")
        time.sleep(5)
    time.sleep(1)
