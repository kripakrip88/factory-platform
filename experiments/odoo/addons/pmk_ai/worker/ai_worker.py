# -*- coding: utf-8 -*-
"""Фоновый процесс ассистента (18.10.2026) — контейнер odoo-ai-worker.

    odoo shell -c /etc/odoo/odoo.conf -d <база> --no-http < ai_worker.py

Правило Антона 18.10: «доработка не должна нарушать скорость работы системы». Вопрос к
Claude идёт 10–60 с; страница Odoo только ставит его в очередь (pmk.ai.request), а отвечает
этот процесс — до WORKER_THREADS вопросов сразу, у каждого свой курсор базы. Раз в секунду:
отметка «жив», зависшие вопросы → ошибка, новые — в работу. Код модуля обновился —
deploy.sh перезапускает контейнер.

27.10.2026: раз в KEEPALIVE_SEC — бесплатный запрос к API в отдельном потоке, чтобы соединение
не остывало (с VPS новое соединение до Anthropic в половине попыток не устанавливается).
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from odoo import SUPERUSER_ID, api
from odoo.addons.pmk_ai.models.ai_chat import WORKER_THREADS
from odoo.addons.pmk_ai.tools import claude

_log = logging.getLogger("pmk_ai.worker")
registry = env.registry  # noqa: F821 — env даёт odoo shell
pool = ThreadPoolExecutor(WORKER_THREADS)
inflight = set()
# Свой поток: соединение может устанавливаться до минуты — вопросы ждать не должны.
warm_pool = ThreadPoolExecutor(1)
warm = {"next": 0.0, "busy": False}


def handle(job):
    """job = (модель, метод, id): вопрос чата или работа модуля (разбор письма)."""
    model, method, record_id = job
    try:
        with registry.cursor() as cr:
            getattr(api.Environment(cr, SUPERUSER_ID, {})[model], method)(record_id)
    except Exception:
        _log.exception("%s %s", model, record_id)
    finally:
        inflight.discard(job)


def keep_warm(key, base):
    try:
        code = claude.keepalive(key, base)
        if code >= 400:
            _log.warning("связь с API: HTTP %s на проверочный запрос", code)
    except Exception as exc:
        _log.warning("связь с API: %s", exc.__class__.__name__)
    finally:
        warm["busy"] = False


_log.info("фоновый процесс ассистента запущен, база %s, потоков %s", registry.db_name, WORKER_THREADS)
print("pmk_ai worker: база %s, потоков %s" % (registry.db_name, WORKER_THREADS), flush=True)
while True:
    try:
        # Изменения из других процессов (ключ, лимит, модель в «Настройки → Ассистент»):
        # без этого фон отвечал бы со старыми настройками из своего кэша.
        registry = registry.check_signaling()
        with registry.cursor() as cr:
            jobs = api.Environment(cr, SUPERUSER_ID, {})["pmk.ai.chat"]._worker_jobs(WORKER_THREADS - len(inflight))
        for job in jobs:
            job = tuple(job)
            inflight.add(job)
            pool.submit(handle, job)
        if time.time() >= warm["next"] and not warm["busy"]:
            warm["next"] = time.time() + claude.KEEPALIVE_SEC
            with registry.cursor() as cr:
                chat = api.Environment(cr, SUPERUSER_ID, {})["pmk.ai.chat"]
                key, base = chat._param("pmk_ai.api_key"), chat._param("pmk_ai.api_base")
            if key:
                warm["busy"] = True
                warm_pool.submit(keep_warm, key, base or None)
    except Exception:
        _log.exception("цикл очереди")
        time.sleep(5)
    time.sleep(1)
