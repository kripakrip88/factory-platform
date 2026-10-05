# -*- coding: utf-8 -*-
"""Просмотр чертежей DXF: вложение -> пути для окна просмотра (разбор УДОБСТВА, шаг 46).

Кто зовёт:
- окно чертежа в ленте документа (расчёт, задание лазеру, сделка — любое
  вложение .dxf; static/src/js/attachment_list_patch.js) и кнопка
  «Посмотреть» у детали задания лазеру — по RPC `attachment_preview`;
- почта (vendor/mail_client, окно «Посмотреть» у вложения и у файла из
  архива) — серверным вызовом `_render_blob`: у письма байты лежат в своей
  модели, а не в ir.attachment с владельцем.

Сам разбор и отрисовка — tools/dxf_render.py, ОТДЕЛЬНЫМ ПРОЦЕССОМ (почему —
в его шапке). Здесь: права, быстрые проверки до запуска, очередь «один
чертёж за раз на сервер», кэш готового ответа по контрольной сумме файла.

КЭШ ЧИТАЕТСЯ И ПИШЕТСЯ ОТДЕЛЬНОЙ ТРАНЗАКЦИЕЙ (_side_cursor). Курсор
запроса Odoo работает в REPEATABLE READ: снимок базы взят ещё при проверке
входа, и ответ, который сосед нарисовал и записал позже, этому запросу не
виден до самого конца. Отдельный курсор видит уже записанное, а его запись
видна соседям сразу, не дожидаясь конца запроса.
"""
import base64
import datetime
import hashlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import time

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import file_path

from ..tools import dxf_render

_logger = logging.getLogger(__name__)

# Срок отдельного процесса. Внутри он сам встаёт на 40 с (SOFT_DEADLINE), а
# этот срок ловит застревание в разборе, который изнутри не прервать.
RENDER_TIMEOUT = 45
# Сколько ждать, пока сервер рисует другой чертёж. Рисуется один чертёж за
# раз: два тяжёлых разом — это ещё по полгигабайта памяти рядом с двумя
# рабочими процессами Odoo в контейнере на 2,5 ГБ. Ждать ДОЛГО нельзя: пока
# запрос спит, он держит рабочий процесс, а их на стенде два — второй занят
# отрисовкой, и Odoo не отвечал бы никому. Две секунды — чтобы двойной
# щелчок или два окна на один маленький чертёж (0,1–1 с) дождались готового
# ответа из кэша, а не получили «занято».
LOCK_WAIT = 2
LOCK_POLL = 0.25
# nginx перед Odoo ждёт ответа 60 с (proxy_read_timeout по умолчанию, в
# infra/nginx/nginx.conf не задан): ожидание + отрисовка должны укладываться
# с запасом, иначе браузер получит 504 вместо слов об отказе.
NGINX_READ_TIMEOUT = 60
# Ключ транзакционной блокировки Postgres «рисуется чертёж» (любое число,
# лишь бы не совпало с чужими: почта берёт свои ключи по id ящика).
LOCK_KEY = 46_0046_0046
# Отказ «рисуется слишком долго» помним сутки: тот же тяжёлый файл иначе при
# каждом открытии снова занимал бы рабочий процесс и единственную очередь
# отрисовки на 40–45 с. Не насовсем — тормозить мог и занятый сервер.
SLOW_CACHE_HOURS = 24
# Сколько готовых ответов хранить. Лишние — самые давно не открытые.
MAX_CACHE_ROWS = 200
# Обновлять отметку «открывали» не чаще раза в сутки на чертёж.
TOUCH_AFTER = datetime.timedelta(days=1)

BUSY = ("Сервер сейчас рисует чертёж (этот или другой) — откройте окно ещё раз "
        "через минуту. Файл можно скачать.")
NO_MODULE_ACCESS = "Просмотр чертежей доступен только сотрудникам."


def _refusal(reason, cache=False, slow=False):
    result = {'ok': False, 'reason': reason, 'cache': cache,
              'version': dxf_render.PAYLOAD_VERSION}
    if slow:
        result['slow'] = True
    return result


def _renderer_digest():
    """Контрольная сумма исходника рисовальщика — в версию кэша: исправили
    tools/dxf_render.py или его пределы — старые ответы (и старые отказы
    «повреждён», «слишком много объектов») не подходят, без ручного шага."""
    try:
        with open(dxf_render.__file__, 'rb') as source:
            return hashlib.sha1(source.read()).hexdigest()[:12]
    except (OSError, TypeError):
        return '-'


RENDERER_DIGEST = _renderer_digest()


class PmkDrawing(models.AbstractModel):
    _name = 'pmk.drawing'
    _description = 'Просмотр чертежей DXF'

    # ------------------------------------------------------------------
    # для браузера
    # ------------------------------------------------------------------
    @api.model
    def attachment_preview(self, attachment_id):
        """Чертёж из ir.attachment — для окна просмотра.

        Права — как у самого вложения: ir.attachment.check_access('read')
        в Odoo 19 проверяет и документ-владелец (res_model/res_id), и права
        на поле, к которому файл приложен (res_field: «Чертёж» детали
        лазера). Файл только читается.

        Ответ: договор tools/dxf_render.py (ok, viewbox, layers, items, …)
        плюс name, file_size, download_url для подписи окна.
        """
        if not self.env.user._is_internal():
            raise AccessError(NO_MODULE_ACCESS)
        try:
            attachment = self.env['ir.attachment'].browse(int(attachment_id)).exists()
        except (TypeError, ValueError):
            attachment = self.env['ir.attachment']
        if not attachment:
            raise UserError("Это вложение больше не существует.")
        attachment.check_access('read')
        attachment = attachment.sudo()
        info = {
            'name': attachment.name or '',
            'file_size': attachment.file_size or 0,
            'download_url': '/web/content/%d?download=true' % attachment.id,
        }
        if attachment.type != 'binary':
            info.update(_refusal("Это ссылка, а не файл — показывать нечего."))
            return info
        if (attachment.file_size or 0) > dxf_render.MAX_FILE_BYTES:
            # Байты в память не берём вовсе: предел известен по размеру.
            info.update(_refusal(_too_big(attachment.file_size), cache=True))
            return info
        result = self._render_blob(attachment.raw or b'', attachment.name or '')
        info.update(result)
        return info

    # ------------------------------------------------------------------
    # для сервера (почта)
    # ------------------------------------------------------------------
    @api.model
    def _available(self):
        """Стоит ли на сервере ezdxf. Образ пересобрали без него — окно
        скажет «Просмотр DXF недоступен», остальное работает."""
        return importlib.util.find_spec('ezdxf') is not None

    @api.model
    def _render_blob(self, blob, name=''):
        """Байты DXF -> ответ окну. Закрытый метод: по RPC его не вызвать,
        права проверяет тот, кто достал байты (attachment_preview, почта)."""
        blob = blob or b''
        if not blob:
            return _refusal("Файл пустой.", cache=True)
        if len(blob) > dxf_render.MAX_FILE_BYTES:
            return _refusal(_too_big(len(blob)), cache=True)
        kind = dxf_render.sniff(blob)
        if kind is None:
            return _refusal(dxf_render.NOT_DXF, cache=True)

        checksum = hashlib.sha1(blob).hexdigest()
        version = self._cache_version()
        cached = self._cache_get(checksum, version)
        if cached is not None:
            return cached
        if not self._available():
            return _refusal(dxf_render.UNAVAILABLE)
        # Быстрый счёт объектов до запуска процесса: отказ «слишком много»
        # не стоит полсекунды на запуск питона.
        if kind == 'ascii':
            limit = dxf_render.MAX_ZERO_TAGS
            if dxf_render.count_zero_tags(blob, stop_after=limit) > limit:
                result = dxf_render.render(blob)          # тот же отказ словами
                self._remember(checksum, version, result)
                return self._public(result)
        if not self._acquire_lock():
            return _refusal(BUSY)
        # Пока ждали, этот же чертёж мог нарисовать сосед — его запись видна
        # (кэш читается отдельной транзакцией, см. шапку файла).
        cached = self._cache_get(checksum, version)
        if cached is not None:
            return cached
        started = time.monotonic()
        result = self._run_renderer(blob)
        _logger.info("pmk_drawing: %s — %s за %.1f с%s", name or checksum[:12],
                     'нарисован' if result.get('ok') else 'отказ',
                     time.monotonic() - started,
                     '' if result.get('ok') else ': %s' % result.get('reason'))
        self._remember(checksum, version, result)
        return self._public(result)

    @api.model
    def _remember(self, checksum, version, result):
        """В кэш: готовый чертёж и отказ, который повторится на тех же
        байтах, — на месяц; отказ по времени — на сутки; «занято», «нет
        библиотеки», сбой разбора — нет."""
        if result.get('cache'):
            self._cache_put(checksum, version, result)
        elif result.get('slow'):
            self._cache_put(checksum, version, result, hours=SLOW_CACHE_HOURS)

    # ------------------------------------------------------------------
    # отдельный процесс
    # ------------------------------------------------------------------
    @api.model
    def _run_renderer(self, blob):
        """python3 -I tools/dxf_render.py: байты на вход, JSON на выход."""
        script = file_path('pmk_drawing/tools/dxf_render.py')
        env = {
            # Кэш шрифтов ezdxf — в ~/.cache/ezdxf; без HOME он строится
            # заново при каждом запуске (секунды на первый текст).
            'HOME': os.environ.get('HOME') or '/var/lib/odoo',
            'PATH': os.environ.get('PATH') or '/usr/bin:/bin',
            'LANG': 'C.UTF-8',
            # numpy под пределом памяти: один поток — без резерва адресов
            # под буферы потоков OpenBLAS.
            'OPENBLAS_NUM_THREADS': '1',
            'OMP_NUM_THREADS': '1',
            'MKL_NUM_THREADS': '1',
        }
        try:
            proc = subprocess.run(
                [sys.executable or 'python3', '-I', script],
                input=blob, capture_output=True, timeout=RENDER_TIMEOUT, env=env, check=False,
            )
        except subprocess.TimeoutExpired:
            return _refusal("Чертёж рисуется слишком долго (больше %d с) — показать его не "
                            "получится. Файл можно скачать и открыть у себя." % RENDER_TIMEOUT,
                            slow=True)
        except OSError:
            _logger.exception("pmk_drawing: не запустился разбор чертежа")
            return _refusal("Разбор чертежа на сервере не запустился. Файл можно скачать.")
        result = None
        if proc.stdout:
            try:
                result = json.loads(proc.stdout)
            except ValueError:
                result = None
        if not isinstance(result, dict):
            _logger.warning("pmk_drawing: разбор прерван, код %s: %s", proc.returncode,
                            (proc.stderr or b'')[-1000:].decode('utf-8', 'replace'))
            # Процесс убит пределом памяти или процессора (код < 0 — сигнал).
            return _refusal("Чертёж слишком тяжёлый: разбор остановлен по пределу памяти "
                            "или времени. Файл можно скачать и открыть у себя.", slow=True)
        if result.get('detail'):
            _logger.warning("pmk_drawing: чертёж не разобран: %s", result['detail'])
        return result

    @api.model
    def _acquire_lock(self):
        """Один чертёж за раз на весь сервер. Блокировка транзакционная —
        снимется сама с концом запроса, даже если он упадёт. Ждём не дольше
        LOCK_WAIT (почему коротко — у LOCK_WAIT)."""
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_KEY,))
            if self.env.cr.fetchone()[0]:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOCK_POLL)

    # ------------------------------------------------------------------
    # кэш
    # ------------------------------------------------------------------
    @api.model
    def _cache_version(self):
        """Версия ответа, библиотеки и исходника рисовальщика: обновили
        ezdxf или поправили tools/dxf_render.py (код, пределы) — старый кэш
        не подходит."""
        try:
            from importlib.metadata import version
            library = version('ezdxf')
        except Exception:
            library = '-'
        return '%s/%s/%s' % (dxf_render.PAYLOAD_VERSION, library, RENDERER_DIGEST)

    @api.model
    def _side_cursor(self):
        """Отдельная транзакция для кэша (почему — в шапке файла). В тестах
        реестр в режиме теста отдаёт курсор-обёртку над курсором теста."""
        return self.env.registry.cursor()

    @api.model
    def _cache_get(self, checksum, version):
        try:
            with self._side_cursor() as cr:
                env = self.env(cr=cr, su=True)
                now = fields.Datetime.now()
                record = env['pmk.drawing.preview'].search([
                    ('checksum', '=', checksum), ('version', '=', version),
                    '|', ('expires', '=', False), ('expires', '>', now),
                ], order='id desc', limit=1)
                if not record:
                    return None
                payload = record.payload
                # Отметка «открывали» — для уборки: ходовой чертёж не должен
                # уходить вместе с забытыми. Раз в сутки, не на каждый взгляд;
                # не вышло (сосед отмечает тот же) — не беда, ответ уже есть.
                if record.write_date and record.write_date < now - TOUCH_AFTER:
                    try:
                        with cr.savepoint(flush=False):
                            cr.execute("UPDATE pmk_drawing_preview SET write_date = %s "
                                       "WHERE id = %s AND write_date < %s",
                                       (now, record.id, now - TOUCH_AFTER))
                    except Exception:
                        _logger.info("pmk_drawing: отметка «открывали» не обновлена")
        except Exception:
            # Кэш — ускорение, а не условие: не прочёлся — рисуем.
            _logger.warning("pmk_drawing: кэш не прочитан", exc_info=True)
            return None
        try:
            return json.loads(base64.b64decode(payload or b''))
        except (ValueError, TypeError):
            return None

    @api.model
    def _cache_put(self, checksum, version, result, hours=None):
        public = self._public(result)
        try:
            text = json.dumps(public, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        except ValueError:
            return                     # бесконечность в ответе — не запоминаем
        try:
            with self._side_cursor() as cr:
                Preview = self.env(cr=cr, su=True)['pmk.drawing.preview']
                Preview.create({
                    'checksum': checksum,
                    'version': version,
                    'ok': bool(public.get('ok')),
                    'expires': (fields.Datetime.now() + datetime.timedelta(hours=hours)
                                if hours else False),
                    'payload': base64.b64encode(text.encode('utf-8')),
                })
                Preview.flush_model()
                # Уборка по числу — своя: штатная временной модели при
                # превышении стирает ВСЁ старше 5 минут, а не лишнее.
                # Остаются MAX_CACHE_ROWS самых недавно открытых. Сосед
                # убирает те же строки — уберёт он, новый ответ остаётся.
                try:
                    with cr.savepoint():
                        Preview.search([], order='write_date desc, id desc',
                                       offset=MAX_CACHE_ROWS).unlink()
                except Exception:
                    _logger.info("pmk_drawing: лишние ответы кэша не убраны")
        except Exception:
            _logger.warning("pmk_drawing: ответ не записан в кэш", exc_info=True)

    @staticmethod
    def _public(result):
        """Ответ без служебного: признаки кэша и подробности ошибки — журналу."""
        return {key: value for key, value in result.items()
                if key not in ('cache', 'slow', 'detail')}


def _too_big(size):
    return ("Чертёж весит %s — больше предела просмотра (%s). Файл можно скачать и "
            "открыть у себя." % (dxf_render._mb(size), dxf_render._mb(dxf_render.MAX_FILE_BYTES)))


class PmkDrawingPreview(models.TransientModel):
    """Готовый ответ окну по контрольной сумме файла.

    Уборка — две:
    - по возрасту — штатная автоочистка Odoo (ir.autovacuum, раз в сутки):
      записи, которые не открывали 30 дней, удаляются вместе с файлом ответа
      (открытие обновляет отметку не чаще раза в сутки — _cache_get);
    - по числу — своя, при каждой записи (_cache_put): остаются
      MAX_CACHE_ROWS самых недавно открытых. Штатную уборку по числу
      (_transient_max_count) не берём: при превышении она стирает ВСЁ старше
      5 минут, то есть весь кэш разом.
    Запоминаются и отказы по размеру и порче (повторятся на тех же байтах);
    отказ по времени — на сутки (expires); «занято», «нет библиотеки» — нет.
    """

    _name = 'pmk.drawing.preview'
    _description = 'Готовый чертёж DXF для окна просмотра'
    _transient_max_hours = 720
    _transient_max_count = 0

    checksum = fields.Char('Контрольная сумма', required=True, index=True)
    version = fields.Char('Версия', required=True)
    ok = fields.Boolean('Нарисован')
    expires = fields.Datetime('Действует до', help="Пусто — пока не уберёт автоочистка.")
    payload = fields.Binary('Ответ окну', attachment=True)
