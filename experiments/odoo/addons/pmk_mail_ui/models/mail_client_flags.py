# -*- coding: utf-8 -*-
"""Отметки «прочитано / отвечено / флажок» — общие с mail.ru в обе стороны.

Разбор удобства, Г1 (Антон, 29.09.2026: «делаем общими»). Ящик pmkpark@mail.ru
подключён «только чтение», и модуль mail_client понимает это буквально:
• прочитанное в Odoo остаётся только в Odoo — _set_flag ставит операцию в
  очередь лишь при «Двусторонней» синхронизации;
• прочитанное на mail.ru до Odoo не доходит: изменения отметок модуль узнаёт
  только через CONDSTORE (UID FETCH … CHANGEDSINCE), а mail.ru его не умеет —
  у всех папок highest_mod_seq = 0. Запасной путь (_reconcile_by_uid_diff)
  только удаляет пропавшие письма. Отметки застыли на дне подключения, 27.09.

«Двусторонняя» не годится: она открывает перенос и удаление, а при чтении
без записи удалённое из Odoo письмо пропадает насовсем (_check_two_way).
Поэтому третий режим: всё как «только чтение», но три отметки общие. Все
проверки модуля почты сравнивают режим с 'two_way', и для них новый режим —
«не двусторонний»: перенос и удаление закрыты, кнопок нет (can_act=False).
Режим 'one_way' не трогаем: zakaz@ и тесты модуля почты его не заметят.

ТУДА — штатная очередь mail.client.sync.op. Она уходит в начале КАЖДОГО прохода
и режим не проверяет (_push_pending_ops), своя отправка не нужна.
ОБРАТНО — если сервер не знает CONDSTORE, одной командой UID FETCH спрашиваем
FLAGS у писем папки за последние 30 дней и сверяем с базой.

ПОРЯДОК. В проходе сначала уходит очередь, потом читаются папки — так устроен
сам _sync. Но письмо, открытое в Odoo после отправки очереди и до чтения своей
папки, получило бы с сервера старое «не прочитано» и до следующего прохода
висело бы непрочитанным. Письма с неотправленной операцией при чтении
пропускаем: сервер о них ещё не знает.

ОТКАЗ СЕРВЕРА. В этот ящик Odoo раньше не писал ни разу, и право записи у
пароля приложения mail.ru не проверено. Если сервер отказывает, модуль почты
после пяти попыток (5 проходов) бросает операцию (state='failed') — и тогда
первое же чтение вернуло бы письму отметку сервера: всё открытое в Odoo
через ~50 минут снова жирное, без всякого сигнала. Поэтому брошенная
операция тоже держит письмо (отметка Odoo остаётся, пока сервер её не примет
или человек не решит), а ящик после прохода помечается ошибкой с объяснением
(значок у ящика, Настройки → Почтовые ящики). Лечение — дать паролю право
записи и нажать «Повторить» в «Ожидающих операциях» либо вернуть ящику
«Только чтение». Держим не вечно — FLAG_WINDOW_DAYS: старше этого письма всё
равно выпадают из окна чтения.

Штатную _apply_flag_changes не берём: она рассчитана на «только изменённые»
от CHANGEDSINCE, читает письма целиком (с текстом) и сверяет метки. Мы же
отдаём ей всё окно, ~1250 писем каждые 10 минут, а метки в этом режиме живут
только в Odoo — она стирала бы их каждым проходом. По той же причине в нашем
режиме её подменяет наша запись и на сервере с CONDSTORE (Dovecot, zakaz@,
если его переключат, или mail.ru, если включит CONDSTORE): там отметки
приходят штатно, через CHANGEDSINCE, но первое же наше «прочитано» поднимает
MODSEQ письма, CHANGEDSINCE возвращает его без меток — и штатная запись стёрла
бы метку, поставленную в Odoo, да ещё и перебила бы неотправленную операцию.

ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ (повторная проверка 29.09, отложено осознанно):
• Путь CONDSTORE в этом режиме (сейчас не работает нигде: zakaz@ в one_way,
  у mail.ru CONDSTORE нет). Отметки, отложенные конфликтом записи или
  удержанием, там НЕ перечитаются на следующем проходе: _sync_messages
  продвинет highest_mod_seq. Прежде чем переводить zakaz@ в этот режим —
  не продвигать MODSEQ при откате/удержании или пробрасывать конфликт.
• Штатный _push_pending_ops снимает is_dirty со всех писем ящика вне точки
  сохранения: если менеджер снова тронет письмо в первые 1-2 с прохода,
  проход откатит первую папку и до следующего прохода покажет ошибку
  (операции уйдут повторно, +FLAGS безвреден). Чинить вместе с шагом 22
  (частая синхронизация + защита от наложения).

ГРАБЛИ. Опираемся на закрытые имена модуля почты: ImapConnection._uid,
_iter_fetch_items, _RE_UID, _RE_FLAGS. Переименуют при обновлении vendor —
модуль не загрузится (ImportError); после обновления гонять tests/.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from psycopg2.errors import DeadlockDetected, LockNotAvailable, SerializationFailure

from odoo import _, api, fields, models

from odoo.addons.mail_client.tools.imap_client import (
    _RE_FLAGS,
    _RE_UID,
    ImapError,
    _iter_fetch_items,
)

_logger = logging.getLogger(__name__)

SHARED_FLAGS_MODE = "pmk_shared_flags"
# Общие отметки. Метки (IMAP-ключевые слова) — нет: умеет ли их mail.ru, не
# проверено, а в этом режиме они и раньше жили только в Odoo.
SHARED_FLAGS = ("\\Seen", "\\Flagged", "\\Answered")
# Окно чтения отметок. Отдельная величина, не sync_window_days (то — глубина
# первой загрузки). Хранилище растёт, а старое письмо на mail.ru перечитывают
# редко: без окна трафик рос бы с каждым днём.
FLAG_WINDOW_DAYS = 30
# «Спам»: 3300 писем за месяц, все непрочитанные, в продажах его не читают.
# Это ~3/4 трафика прохода. Отметки из Odoo туда всё равно уходят (очередь).
# Роль «Спама» у mail.ru держится на RU_NAME_ROLES (mail_client_folder.py).
SKIP_ROLES = {"spam"}
# Те же пять полей, что пишет штатная _apply_flag_changes (её folder.py:440-447).
FLAG_FIELDS = {
    "\\seen": "flag_seen",
    "\\flagged": "flag_flagged",
    "\\answered": "flag_answered",
    "\\draft": "flag_draft",
    "\\deleted": "flag_deleted",
}
# Встречная запись в ту же строку письма (крон читает отметки, менеджер в ту
# же секунду открыл письмо): Postgres отказывает одной из сторон.
_CONCURRENCY_ERRORS = (SerializationFailure, DeadlockDetected, LockNotAvailable)


class MailClientAccount(models.Model):
    _inherit = "mail.client.account"

    sync_mode = fields.Selection(
        selection_add=[(SHARED_FLAGS_MODE, "Только чтение + общие отметки")],
        # Поле обязательное: без политики Odoo не загрузит модуль. При удалении
        # pmk_mail_ui ящик вернётся в «только чтение» (значение по умолчанию).
        ondelete={SHARED_FLAGS_MODE: "set default"},
    )

    def _pmk_shares_flags(self):
        self.ensure_one()
        return self.sync_mode == SHARED_FLAGS_MODE

    def _sync(self):
        super()._sync()
        # Проход удался (иначе ошибка уже записана), но отметки сервер мог
        # отвергнуть: _sync об этом молчит и пишет «подключено».
        if self.state == "connected" and self._pmk_shares_flags():
            self._pmk_report_refused_marks()

    def _pmk_report_refused_marks(self):
        refused = self.env["mail.client.sync.op"]._pmk_live_refusals(
            [("account_id", "=", self.id)])
        if not refused:
            return
        self.write({
            "state": "error",
            "error_message": _(
                "Отметки (прочитано, отвечено, флажок) не доходят до почтового "
                "сервера: он отказал %(count)s раз, последний ответ — %(error)s.\n"
                "В Odoo отметки сохранены, и сервер их не перебивает. Дайте ящику "
                "право записи и нажмите «Повторить» в Настройки → Почтовые ящики → "
                "Ожидающие операции, либо верните ящику режим «Только чтение».",
                count=len(refused), error=refused[0].last_error or "—",
            ),
        })
        # Сигнал о проходе уже ушёл с «подключено» — повторяем с ошибкой.
        self._notify_bus()


class MailClientMessage(models.Model):
    _inherit = "mail.client.message"

    def _set_flag(self, flag, value):
        # Локальная запись и очередь для two_way — штатные. Здесь только
        # очередь для нашего режима: two_way свою операцию уже получил, второй
        # не нужно (тест модуля почты требует ровно одну).
        result = super()._set_flag(flag, value)
        if flag in SHARED_FLAGS:
            SyncOp = self.env["mail.client.sync.op"]
            for message in self:
                if message.account_id._pmk_shares_flags():
                    SyncOp.queue(message, "set_flag" if value else "unset_flag",
                                 {"flags": [flag]})
        return result


class MailClientFolder(models.Model):
    _inherit = "mail.client.folder"

    def _reconcile_existing(self, connection, status):
        shared = self.account_id._pmk_shares_flags()
        # Удаления (сравнение UID) — штатно, и раньше наших отметок. Режим
        # передаём контекстом: путь CHANGEDSINCE внутри super() зовёт
        # _apply_flag_changes, и та не должна читать ящик второй раз — тест
        # модуля почты считает её запросы (test_flag_sync_cost_…: не больше 5).
        super(MailClientFolder, self.with_context(pmk_shared_flags=shared)
              )._reconcile_existing(connection, status)
        # Жёстко по режиму: у обычного ящика (и у заглушек в тестах модуля
        # почты) соединение может и не уметь _uid — нас там быть не должно.
        if not shared or self.role in SKIP_ROLES:
            return
        # Сервер умеет CONDSTORE (Dovecot, zakaz@): отметки уже пришли через
        # CHANGEDSINCE — штатным путём, но нашей записью (_apply_flag_changes
        # ниже). Если mail.ru когда-нибудь его включит, наш проход по окну
        # отключится сам. highest_mod_seq здесь ещё прошлый: новый
        # _sync_messages пишет после нас.
        if int(self.highest_mod_seq or 0) and status.get("mod_seq"):
            return
        self._pmk_pull_flags(connection, status)

    def _pmk_pull_flags(self, connection, status):
        low = self._pmk_flag_window_start()
        if not low:
            return                      # в папке нет свежих писем
        high = status["uid_next"] - 1 if status.get("uid_next") else "*"
        try:
            entries = self._pmk_fetch_flags(connection, low, high)
        except ImapError as exc:
            # Сбой одной папки не должен сорвать проход: письма уже
            # загружены, отметки дочитаем через 10 минут.
            _logger.warning("Почта %s/%s: отметки с сервера не прочитать — %s",
                            self.account_id.email, self.imap_path, exc)
            return
        self._pmk_store_flags(entries)

    def _apply_flag_changes(self, changed):
        # Путь CONDSTORE (CHANGEDSINCE). Штатная запись стирала бы метки Odoo
        # и перебивала бы неотправленные операции — см. шапку файла. Режим —
        # из контекста _reconcile_existing (единственный вызов у модуля
        # почты): без него — штатный путь, без лишнего запроса к ящику.
        if not self.env.context.get("pmk_shared_flags"):
            return super()._apply_flag_changes(changed)
        return self._pmk_store_flags(changed or [])

    def _pmk_store_flags(self, entries):
        """Записать отметки с сервера: без писем, чья отметка из Odoo ещё не
        дошла, и с откатом только своей записи при встречной правке."""
        waiting = self._pmk_uids_waiting_push()
        entries = [e for e in entries if e["uid"] not in waiting]
        if not entries:
            return
        # Всё, что проход записал до нас (новые письма, удаления), — в базу
        # ДО точки сохранения: сбой в чужой записи должен идти штатным путём
        # _sync, а не приниматься за наш конфликт отметок.
        self.env.flush_all()
        try:
            # Письмо могли поменять в Odoo, пока идёт проход. Конфликт записи
            # откатываем до точки сохранения: без неё _sync откатил бы всю
            # папку и пометил бы ящик ошибкой до следующего прохода. При
            # откате точка сохранения чистит кэш — теряется только наша запись.
            with self.env.cr.savepoint():
                changed = self._pmk_apply_flags(entries)
        except _CONCURRENCY_ERRORS as exc:
            _logger.info("Почта %s/%s: отметки отложены до следующего прохода — %s",
                         self.account_id.email, self.imap_path, exc)
            return
        if changed:
            _logger.info("Почта %s/%s: отметки с сервера у %s писем",
                         self.account_id.email, self.imap_path, changed)

    def _pmk_flag_window_start(self):
        """Наименьший UID среди писем папки за окно. Спрашиваем диапазон, а не
        список UID: у mail.ru номера общие на весь ящик, 665 писем Входящих
        разбросаны по 4800 номерам, и список раздул бы команду до килобайт.
        Сервер всё равно ответит только за письма выбранной папки."""
        since = fields.Datetime.now() - timedelta(days=FLAG_WINDOW_DAYS)
        rows = self.env["mail.client.message"].search_read(
            [("folder_id", "=", self.id), ("date", ">=", since)],
            ["imap_uid"], order="imap_uid", limit=1)
        return rows[0]["imap_uid"] if rows else None

    @staticmethod
    def _pmk_fetch_flags(connection, low, high):
        """[{'uid': int, 'flags': [str]}] для UID low:high — в разборе ответа
        imaplib, как его делает сам модуль почты."""
        typ, data = connection._uid("FETCH", "%s:%s" % (low, high), "(FLAGS)")
        if typ != "OK":
            raise ImapError("UID FETCH FLAGS refused")
        entries = []
        for attributes, _literal in _iter_fetch_items(data):
            uid_match = _RE_UID.search(attributes)
            flags_match = _RE_FLAGS.search(attributes)
            # Строка без FLAGS ничего не говорит об отметках. Читать её как
            # «отметок нет» (так делает fetch_flags_since модуля почты) —
            # значит снять «прочитано» с письма.
            if not uid_match or not flags_match:
                continue
            uid = int(uid_match.group(1))
            if uid < low:               # «N:*» при N > последнего отдаёт последнее
                continue
            entries.append({"uid": uid, "flags": [
                f.decode("ascii", "ignore") for f in flags_match.group(1).split()]})
        return entries

    def _pmk_uids_waiting_push(self):
        """Письма, чья отметка из Odoo ещё не дошла до сервера. Именно операции,
        а не is_dirty: _push_pending_ops снимает is_dirty со всех писем
        ящика, даже если операция не прошла и ждёт повтора. Операция, которую
        сервер отверг пять раз (failed), тоже держит письмо — иначе отметка
        Odoo молча откатилась бы (см. «ОТКАЗ СЕРВЕРА» в шапке); ящик при этом
        помечен ошибкой. Держит FLAG_WINDOW_DAYS, не дольше."""
        SyncOp = self.env["mail.client.sync.op"]
        pending = SyncOp.sudo().search_read([
            ("folder_id", "=", self.id),
            ("op_type", "in", ("set_flag", "unset_flag")),
            ("state", "=", "pending"),
        ], ["imap_uid"])
        refused = SyncOp._pmk_live_refusals([("folder_id", "=", self.id)])
        return {row["imap_uid"] for row in pending} | set(refused.mapped("imap_uid"))

    def _pmk_apply_flags(self, entries):
        """Записать отличия. Читаем только нужные столбцы (не письмо целиком
        с текстом), пишем группами по одинаковому набору значений: обычно это
        0–2 UPDATE за папку. Метки не трогаем — они живут только в Odoo."""
        if not entries:
            return 0
        # Сервер мог прислать строку одного письма дважды — берём последнюю.
        by_server = {entry["uid"]: entry for entry in entries}
        Message = self.env["mail.client.message"]
        rows = Message.search_read(
            [("folder_id", "=", self.id), ("imap_uid", "in", list(by_server))],
            ["imap_uid", *FLAG_FIELDS.values()])
        groups = defaultdict(list)
        for row in rows:
            flags = {f.lower() for f in by_server[row["imap_uid"]]["flags"]}
            values = {field: flag in flags for flag, field in FLAG_FIELDS.items()}
            if any(row[field] != value for field, value in values.items()):
                groups[tuple(sorted(values.items()))].append(row["id"])
        # Строк о письмах, которых у нас нет (старше первой загрузки или
        # пришли на сервер уже после выборки заголовков), в rows просто нет —
        # такие не трогаем: новые придут с отметками вместе с заголовками.
        for values, ids in groups.items():
            Message.browse(ids).write(dict(values))
        return sum(len(ids) for ids in groups.values())


class MailClientSyncOp(models.Model):
    _inherit = "mail.client.sync.op"

    @api.model
    def _pmk_live_refusals(self, domain):
        """Отвергнутые (failed) операции отметок, которые ещё что-то значат.

        Не считаются (повторная проверка 29.09):
        • старше окна отметок — письмо всё равно выпало из чтения;
        • в архивной папке — папку переименовали или удалили на mail.ru, путь
          не вернётся, и «дайте право записи» было бы враньём;
        • перекрытые более поздней операцией по тому же письму и той же
          отметке, которая прошла или ждёт отправки: запись работает, а
          старое намерение уже заменено новым («Повторить» по такой операции
          накатило бы старое поверх нового)."""
        SyncOp = self.sudo()
        since = fields.Datetime.now() - timedelta(days=FLAG_WINDOW_DAYS)
        failed = SyncOp.search(domain + [
            ("op_type", "in", ("set_flag", "unset_flag")),
            ("state", "=", "failed"),
            ("create_date", ">=", since),
            ("folder_id.active", "=", True),
        ], order="write_date desc, id desc")
        if not failed:
            return failed
        later = SyncOp.search_read([
            ("folder_id", "in", failed.folder_id.ids),
            ("imap_uid", "in", failed.mapped("imap_uid")),
            ("op_type", "in", ("set_flag", "unset_flag")),
            ("state", "in", ("done", "pending")),
            ("id", ">", min(failed.ids)),
        ], ["folder_id", "imap_uid", "payload"])

        def overtaken(op):
            flags = set((op.payload or {}).get("flags") or [])
            return any(
                row["id"] > op.id
                and row["folder_id"][0] == op.folder_id.id
                and row["imap_uid"] == op.imap_uid
                and flags & set((row["payload"] or {}).get("flags") or [])
                for row in later)

        return failed.filtered(lambda op: not overtaken(op))
