/**
 * Открыл переписку — прочитаны её письма («Почта как в Mail.ru», Г9).
 *
 * Модуль почты при открытии помечает одно письмо — представителя строки
 * (selectMessage, пометка через setSeen). А строка-переписка жирная, пока
 * непрочитано любое её письмо. Поэтому переписки, где непрочитано старое
 * письмо или ответ клиента на наше письмо в «Отправленных», не гасли никогда.
 *
 * Гасим письма не новее ПОКАЗАННОГО (upto): открытие строки — всё, что не
 * новее письма строки. С шага 20 (30.09.2026) переписка видна под письмом
 * целиком, новые сверху, и самое новое письмо развёрнуто: когда его тело
 * пришло, лента зовёт крючок корня conversationShown — гасим всё, что не
 * новее его (якоря: строка и это письмо). Ответ клиента, пришедший позже
 * нашего письма в «Отправленных», виден сверху и гаснет (до шага 20 он
 * оставался жирным). То же — у любого письма, развёрнутого в ленте, если
 * в переписке ещё есть что гасить.
 *
 * Самое новое — НЕ при открытии, а когда его тело показано (разбор шага
 * 20): тело могло не прийти (mail.ru отказал) — тогда письмо остаётся
 * непрочитанным и здесь, и на mail.ru; а пометка при открытии писала
 * строку самого нового письма в ту же секунду, когда лента читала его
 * тело, — запись тела упиралась в пометку, и Odoo повторял запрос целиком:
 * второй вход в mail.ru и второе чтение тела. Пометку показанного шлём
 * после пометки открытия (pmkOpening): иначе две пометки писали бы одни и
 * те же строки одновременно. «Прочитано» (кнопка, выделение) гасит
 * переписку целиком.
 * В «Все входящие» переписка общая для всех ящиков (unified) — там и гасим
 * во всех. Строку гасим по числу, которое вернул сервер, а не наугад.
 *
 * Сами письма переписки ищет сервер (pmk_mark_threads_seen): get_thread
 * прячет вторую копию письма, лежащего в двух папках, а счётчик её считает.
 * Пометка идёт штатным set_seen_bulk — значит, и в очередь на mail.ru (Г1).
 * Синхронизацию не запускаем и список заново не грузим.
 *
 * Без режима переписок всё как было: строка = письмо.
 * В режиме переписок одиночная пометка модуля (setSeen(true)) выключена
 * СОВСЕМ: помечает только selectMessage (с upto), кнопка «Прочитано» —
 * toggleSeen. Раньше setSeen глушился набором «открывается сейчас», но
 * запоздалый ответ прошлого открытия звал setSeen, когда выделена уже другая
 * строка, — и гасил её переписку целиком, вместе с неоткрытым ответом
 * клиента (повторная проверка 29.09). Других вызовов setSeen(true) у модуля
 * почты нет: selectMessage и toggleSeen (mail_client_action.js).
 * С шага 17 (29.09.2026) модуль почты сам выбрасывает опоздавший ответ
 * (у каждого открытия свой знак) и setSeen по нему не зовёт, а четыре
 * запроса открытия идут разом. По текущему открытию setSeen(true)
 * по-прежнему зовётся синхронно сразу после записи ответа — глушилка ниже
 * нужна ради него. selectMessage модуля почты возвращает исход открытия
 * ("shown" / "superseded" / "failed"); по "failed" не гасим ничего.
 *
 * «Непрочитано» (шаг 18, 30.09.2026) — одно письмо (со всеми его копиями в
 * ящике: строку сервер считает по одной копии), но с точными числами с
 * сервера (pmk_mark_unseen): модуль почты прибавлял +1 открытой папке, а не
 * папке письма, в «Все входящие» счётчики не трогал, а строку искал по id
 * письма — письмо из окна переписки или истории контакта строкой не
 * является, и строка не жирнела. Теперь строку ищем по ключу переписки и
 * ставим ей число, которое вернул сервер. Значок в окне меняется сразу, до
 * ответа сервера. Без режима переписок — как у модуля почты (он с шага 18
 * сам берёт папку письма из detail.folder_id).
 *
 * Шаг 22 (30.09.2026): список обновляется после синхронизации без сброса, и
 * ответ обновления, снятый с базы до нашей пометки, вернул бы строке
 * жирность. Поэтому pmkApplyThreadResult, поправив строки, зовёт крючок
 * корня noteListEdit: такой ответ корень не применяет, а перечитывает
 * список ещё раз (mail_client_action.js, refreshListOnce). bulkSeen идёт
 * через runBulk — его запись корень отслеживает сам (trackListWrite).
 *
 * Грабли: держимся за имена selectMessage / setSeen / toggleSeen / bulkSeen /
 * runBulk / conversationShown (крючок корня, его зовёт лента
 * panes/conversation.js через ReadingPane) / noteListEdit и за state.thread /
 * state.messages / state.accounts /
 * state.contact.history / state.detail / state.selectedMessageId /
 * state.unified / row.thread_key / row.unread_count. Серверные — за
 * pmk_mark_threads_seen и pmk_mark_unseen (models/mail_client_message.py).
 * Переименуют их — импорт не упадёт, а пометка тихо вернётся к одному письму.
 * Модуль почты теперь наш (vendor/README.md): правишь эти методы там —
 * правь и этот файл тем же коммитом.
 */
import { patch } from "@web/core/utils/patch";

import { MailClientInbox } from "@mail_client/mail_client_action";

patch(MailClientInbox.prototype, {
    async selectMessage(messageId) {
        if (!this.state.threaded) {
            return super.selectMessage(messageId);
        }
        // Не открылось текущее — super бросает исключение, сюда не доходим.
        // Не открылось опоздавшее (уже открыли другое) — модуль почты ошибку
        // глотает и отвечает "failed": письма никто не видел, гасить нечего.
        // А если его уже нет на сервере, пометка вызвала бы окно ошибки про
        // письмо, которого нет на экране. "superseded" (письмо пришло, но уже
        // открыли другое) гасим, как раньше: его открывали, и оно дошло.
        const outcome = await super.selectMessage(messageId);
        if (outcome !== "failed" && this.pmkThreadHasUnread(messageId)) {
            // Якорь — только строка: самое новое письмо ленты гасит
            // conversationShown, когда его тело показано.
            const marking = this.pmkMarkThreadsSeen([messageId], { upto: true });
            this.pmkOpening = marking.catch(() => {});
            await marking;
        }
        return outcome;
    },

    /**
     * Письмо ленты показано (развёрнуто, тело пришло) — гасим переписку до
     * него. Сначала ждём пометку открытия: после её ответа строка и лента
     * знают, что ещё не прочитано, и часто гасить уже нечего. Переписке
     * верим, только если на экране всё ещё она: выделена другая строка
     * (идёт открытие) или письма в ленте нет — ничего не делаем.
     */
    async conversationShown(messageId) {
        super.conversationShown(messageId);
        if (!this.state.threaded) {
            return;
        }
        await this.pmkOpening;
        const detail = this.state.detail;
        if (
            !detail ||
            detail.id === messageId ||
            this.state.selectedMessageId !== detail.id ||
            !this.state.thread.some((item) => item.id === messageId) ||
            !this.pmkThreadHasUnread(detail.id)
        ) {
            return;
        }
        await this.pmkMarkThreadsSeen([detail.id, messageId], { upto: true });
    },

    setSeen(value) {
        if (!this.state.threaded) {
            return super.setSeen(value);
        }
        if (value) {
            // Пометку при открытии делает selectMessage, кнопку — toggleSeen.
            // Сюда приходит только вызов из selectMessage модуля почты, в том
            // числе запоздалый, от прошлого открытия, — его и глушим.
            return;
        }
        // «Непрочитано» — одно письмо, строка переписки снова жирная.
        return this.pmkMarkUnseen(this.state.selectedMessageId);
    },

    async toggleSeen() {
        const detail = this.state.detail;
        if (this.state.threaded && detail && !detail.flag_seen) {
            // Кнопка «Прочитано» в окне письма действует на всю переписку.
            return this.pmkMarkThreadsSeen([detail.id]);
        }
        return super.toggleSeen();
    },

    async bulkSeen(value) {
        if (!value || !this.state.threaded) {
            return super.bulkSeen(value);
        }
        const ids = new Set(this.state.selectedIds);
        for (const row of this.state.messages) {
            if (ids.has(row.id)) {
                row.flag_seen = true;
                row.unread_count = 0;
            }
        }
        // Открытая сейчас строка среди выделенных — её окно тоже гасим:
        // runBulk ответ сервера не отдаёт, а переписка в окне — та же.
        if (this.state.detail && ids.has(this.state.selectedMessageId)) {
            this.state.detail.flag_seen = true;
            for (const item of this.state.thread) {
                item.flag_seen = true;
            }
        }
        // runBulk модуля почты: крутилка, сброс выделения, счётчики папок
        // через loadAccounts. Список заново не грузим.
        await this.runBulk("pmk_mark_threads_seen", { unified: this.state.unified });
    },

    /**
     * Есть ли что гасить. Окну и переписке верим, только если это всё ещё
     * открытое письмо: при быстрых щелчках по строкам ответ прошлого
     * открытия приходит, когда на экране уже другое письмо (модуль почты
     * его тогда не записывает и молча возвращается — остаётся строка списка).
     */
    pmkThreadHasUnread(messageId) {
        const detail = this.state.detail;
        const current =
            this.state.selectedMessageId === messageId && detail && detail.id === messageId;
        const row = this.state.messages.find((m) => m.id === messageId);
        return Boolean(
            (current && !detail.flag_seen) ||
                (current && this.state.thread.some((m) => !m.flag_seen)) ||
                // Копию, которую get_thread спрятал, строка всё равно считает.
                (row && (!row.flag_seen || row.unread_count))
        );
    },

    async pmkMarkThreadsSeen(messageIds, { upto = false } = {}) {
        const result = await this.orm.call(
            "mail.client.message",
            "pmk_mark_threads_seen",
            [],
            { message_ids: messageIds, upto, unified: this.state.unified }
        );
        this.pmkApplyThreadResult(result, true);
    },

    async pmkMarkUnseen(messageId) {
        if (!messageId) {
            return;
        }
        const detail = this.state.detail;
        const shown = Boolean(detail && detail.id === messageId);
        if (shown) {
            detail.flag_seen = false; // значок в окне — сразу
        }
        let result;
        try {
            result = await this.orm.call("mail.client.message", "pmk_mark_unseen", [], {
                message_id: messageId,
                unified: this.state.unified,
            });
        } catch (error) {
            // Сервер отказал (общий ящик «только смотреть») — значок назад.
            if (shown && this.state.detail === detail) {
                detail.flag_seen = true;
            }
            throw error;
        }
        this.pmkApplyThreadResult(result, false);
    },

    /**
     * Ответ сервера (pmk_mark_threads_seen / pmk_mark_unseen) — в окно:
     * seen — чем стали письма из result.ids.
     */
    pmkApplyThreadResult(result, seen) {
        const ids = new Set(result.ids);
        const left = new Map(result.threads.map((t) => [t.thread_key, t.unread]));
        // Шаг 22: строки списка поправлены — обновление списка, запрошенное
        // до пометки, их не перебьёт (см. шапку).
        this.noteListEdit();
        // Строку ищем по ключу переписки, а не по id: письмо могли открыть
        // из окна переписки или из истории контакта, тогда это не строка списка.
        // Жирной она остаётся, если в переписке что-то непрочитано и теперь
        // (более новый ответ при открытии, чужой ящик «только смотреть»).
        for (const row of this.state.messages) {
            if (row.thread_key && left.has(row.thread_key)) {
                row.unread_count = left.get(row.thread_key);
                row.flag_seen = !row.unread_count;
            } else if (ids.has(row.id)) {
                row.flag_seen = seen;
                row.unread_count = seen ? 0 : Math.max(row.unread_count || 0, 1);
            }
        }
        for (const item of this.state.thread) {
            if (ids.has(item.id)) {
                item.flag_seen = seen;
            }
        }
        for (const item of this.state.contact?.history || []) {
            if (ids.has(item.id)) {
                item.flag_seen = seen;
            }
        }
        if (this.state.detail && ids.has(this.state.detail.id)) {
            this.state.detail.flag_seen = seen;
        }
        // Точные счётчики с сервера — и для папок, где лежат ответы клиента,
        // и в общем ящике, где activeFolderId пуст.
        const unread = new Map(result.folders.map((f) => [f.id, f.unread]));
        for (const account of this.state.accounts) {
            for (const folder of account.folders) {
                if (unread.has(folder.id)) {
                    folder.unread = unread.get(folder.id);
                }
            }
        }
    },
});
