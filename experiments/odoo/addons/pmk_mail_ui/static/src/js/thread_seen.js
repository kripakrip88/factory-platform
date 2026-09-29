/**
 * Открыл переписку — прочитаны её письма («Почта как в Mail.ru», Г9).
 *
 * Модуль почты при открытии помечает одно письмо — представителя строки
 * (selectMessage, пометка через setSeen). А строка-переписка жирная, пока
 * непрочитано любое её письмо. Поэтому переписки, где непрочитано старое
 * письмо или ответ клиента на наше письмо в «Отправленных», не гасли никогда.
 *
 * Открытие гасит письма не новее открытого (upto): ответ клиента, пришедший
 * позже нашего письма, из «Отправленных» не виден — он остаётся жирным, пока
 * его не откроют. «Прочитано» (кнопка, выделение) гасит переписку целиком.
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
 * «Непрочитано» — как у модуля почты: одно письмо.
 *
 * Грабли: держимся за имена selectMessage / setSeen / toggleSeen / bulkSeen /
 * runBulk и за state.thread / state.messages / state.accounts / row.thread_key.
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
            await this.pmkMarkThreadsSeen([messageId], { upto: true });
        }
        return outcome;
    },

    setSeen(value) {
        if (value && this.state.threaded) {
            // Пометку при открытии делает selectMessage, кнопку — toggleSeen.
            // Сюда приходит только вызов из selectMessage модуля почты, в том
            // числе запоздалый, от прошлого открытия, — его и глушим.
            return;
        }
        // «Непрочитано» — как у модуля почты: одно письмо, строка снова жирная.
        return super.setSeen(value);
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
        const ids = new Set(result.ids);
        const left = new Map(result.threads.map((t) => [t.thread_key, t.unread]));
        // Строку ищем по ключу переписки, а не по id: письмо могли открыть
        // из окна переписки или из истории контакта, тогда это не строка списка.
        // Жирной она остаётся, если в переписке что-то непрочитано и теперь
        // (более новый ответ при открытии, чужой ящик «только смотреть»).
        for (const row of this.state.messages) {
            if (row.thread_key && left.has(row.thread_key)) {
                row.unread_count = left.get(row.thread_key);
                row.flag_seen = !row.unread_count;
            } else if (ids.has(row.id)) {
                row.flag_seen = true;
                row.unread_count = 0;
            }
        }
        for (const item of this.state.thread) {
            if (ids.has(item.id)) {
                item.flag_seen = true;
            }
        }
        for (const item of this.state.contact?.history || []) {
            if (ids.has(item.id)) {
                item.flag_seen = true;
            }
        }
        if (this.state.detail && ids.has(this.state.detail.id)) {
            this.state.detail.flag_seen = true;
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
