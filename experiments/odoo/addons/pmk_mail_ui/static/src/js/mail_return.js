/**
 * Документ из почты — в этом же окне, возврат — на то же письмо (15.10.2026).
 *
 * Было: лид, контрагент, сделка, счёт открывались новой вкладкой. У Антона
 * Odoo установлен приложением («Открыть в приложении»), там новая вкладка —
 * отдельное окно. Формы в окошке он раньше назвал «недоразумением». Теперь
 * документ открывается обычной страницей в этом же окне, в строке пути —
 * «Почта / …»; щелчок по «Почта» возвращает почту, и она сама открывает то
 * письмо, с которого ушли (step53_open.js, takeMailReturn).
 *
 * Номер письма — в sessionStorage этой вкладки, на 30 минут и на один
 * возврат: почта, открытая позже из меню, на старое письмо не прыгает.
 */
const KEY = "pmk_mail.return";
const TTL_MS = 30 * 60 * 1000;

export function rememberMailReturn(messageId) {
    if (!messageId) {
        return;
    }
    try {
        window.sessionStorage.setItem(KEY, JSON.stringify({ messageId, at: Date.now() }));
    } catch {
        // Нет хранилища — вернёмся во «Входящие», не страшно.
    }
}

export function takeMailReturn() {
    try {
        const raw = window.sessionStorage.getItem(KEY);
        window.sessionStorage.removeItem(KEY);
        const data = raw ? JSON.parse(raw) : null;
        if (data && data.messageId && Date.now() - (data.at || 0) < TTL_MS) {
            return Number(data.messageId) || 0;
        }
    } catch {
        // Битая запись — как будто её не было.
    }
    return 0;
}

/** Открыть документ в этом же окне, запомнив письмо для возврата. */
export function openFromMail(env, model, id, messageId) {
    rememberMailReturn(messageId);
    return env.services.action.doAction({
        type: "ir.actions.act_window",
        res_model: model,
        res_id: id,
        views: [[false, "form"]],
        target: "current",
    });
}
