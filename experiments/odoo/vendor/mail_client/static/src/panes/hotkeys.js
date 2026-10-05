/** @odoo-module **/
/**
 * ПРАВКА ПМК (шаг 41 разбора удобства, А6, 05.10.2026): горячие клавиши
 * почты — правила без Owl и без сервисов.
 *
 * Клавиши (mail_client_action.js регистрирует их штатным useHotkey ядра,
 * кроме «/», которую ядро не принимает):
 *   ↑ / ↓ — соседнее письмо списка (одно нажатие — одно письмо: зажатая
 *           стрелка не листает и не помечает прочитанными пачку писем).
 *           Только когда человек «в списке» (arrowsMoveRows): письмо уже
 *           открыто или было открыто, последний щелчок и фокус — не в окне
 *           письма, письмо не закрывает список («на весь экран»). Иначе
 *           стрелки — браузеру: прокрутка списка или письма, как до шага 41
 *           (доводка: стрелка, нажатая, чтобы прокрутить, открывала
 *           соседнее письмо и отмечала его прочитанным — и на mail.ru);
 *   R / A / F — «Ответить», «Ответить всем», «Переслать»; L — «Лид». Ровно
 *           щелчок по ВИДИМОЙ кнопке закреплённой строки над письмом
 *           (data-mc-key): нет кнопки, скрыта, неактивна, письмо ещё
 *           грузится (окно inert) — клавиша ничего не делает;
 *   /     — курсор в поиск;
 *   Esc   — из «письма на весь экран» обратно к списку, закрыть шторку
 *           папок на телефоне.
 * В поле ввода, редакторе письма и при открытом окне (диалоге) клавиши не
 * перехватываются — так устроен и сервис клавиш ядра. Буквы — по физической
 * клавише: в русской раскладке R — это «К», как у ядра (getActiveHotkey).
 *
 * Фокус в тексте письма (рамка iframe) клавиш наружу не отдаёт: рамка
 * пересылает их сама (frame_fit.js, forwardableKey) — буквы, «/» и Esc, но
 * не стрелки: в тексте письма стрелки прокручивают письмо.
 *
 * Чистый модуль — его проверяет node: static/tests/step41_rules.test.mjs.
 */

/** Клавиши-буквы: физическая клавиша → значение data-mc-key кнопки. */
export const KEY_BUTTONS = ["r", "a", "f", "l"];

const TYPING_INPUTS = new Set([
    "text", "search", "email", "number", "password", "tel", "url", "date",
    "datetime-local", "month", "time", "week",
]);

/**
 * Фокус там, где человек печатает: поле ввода, textarea, select, редактор
 * (contenteditable). Флажок, кнопка — не ввод.
 */
export function isTypingTarget(el) {
    if (!el || typeof el !== "object") {
        return false;
    }
    const tag = String(el.tagName || "").toLowerCase();
    if (tag === "textarea" || tag === "select") {
        return true;
    }
    if (tag === "input") {
        return TYPING_INPUTS.has(String(el.type || "text").toLowerCase());
    }
    if (el.isContentEditable) {
        return true;
    }
    return Boolean(typeof el.closest === "function" && el.closest("[contenteditable='true']"));
}

function hasModifier(ev) {
    return Boolean(ev.ctrlKey || ev.metaKey || ev.altKey);
}

/**
 * «/» — в поиск. Сам знак «/» (в любой раскладке, где он есть, в том числе
 * с Shift) или физическая клавиша «/» без Shift: в русской раскладке на ней
 * точка. Без Ctrl, Cmd, Alt.
 */
export function isSearchKey(ev) {
    if (!ev || hasModifier(ev) || ev.isComposing) {
        return false;
    }
    return ev.key === "/" || (ev.code === "Slash" && !ev.shiftKey);
}

/**
 * Какие клавиши рамка письма пересылает почте: только те, что почта знает,
 * без Ctrl / Cmd / Alt (Ctrl+C, Ctrl+A, Ctrl+F в тексте письма — его
 * собственные). Стрелки — нет: человек щёлкнул по тексту письма и листает
 * его (доводка шага 41).
 */
export function forwardableKey(ev) {
    if (!ev || hasModifier(ev) || ev.isComposing) {
        return false;
    }
    if (ev.key === "Escape") {
        return true;
    }
    if (isSearchKey(ev)) {
        return true;
    }
    if (ev.shiftKey) {
        return false;
    }
    const code = String(ev.code || "");
    return /^Key[RAFL]$/.test(code) || KEY_BUTTONS.includes(String(ev.key || "").toLowerCase());
}

/**
 * Листают ли ↑ / ↓ письма списка (доводка шага 41). Да, только если:
 *   rows — в списке есть строки; current — человек на строке (письмо
 *     открыто или было открыто: rowOnScreen). Ничего не открывали — стрелки
 *     браузеру, иначе ↓ «по привычке» открывала первое письмо и гасила его;
 *   draft — не пишется письмо;
 *   readerCovers — письмо не закрывает список («на весь экран», телефон):
 *     там стрелки листают само письмо, соседнее — кнопками ↑ ↓;
 *   inReader — последний щелчок или фокус не в окне письма: щёлкнул по
 *     письму — стрелки прокручивают письмо, щёлкнул по списку — листают.
 */
export function arrowsMoveRows({
    rows = 0,
    current = false,
    draft = false,
    readerCovers = false,
    inReader = false,
} = {}) {
    return Boolean(rows > 0 && current && !draft && !readerCovers && !inReader);
}

/**
 * Соседнее письмо списка.
 *
 * rows — строки списка (state.messages), сверху вниз; открытая строка — по
 * id письма или, если строку теперь представляет другое письмо переписки
 * (пришёл ответ), по ключу переписки. dir: +1 — вниз (старше), -1 — вверх.
 * Ответ: {id} — открыть это письмо; {id: null, needMore: true} — внизу
 * загруженного, есть «Загрузить ещё»; {id: null} — дальше некуда.
 * Ничего не открыто: вниз — первое письмо, вверх — ничего (клавишам до
 * этого случая не дойти — arrowsMoveRows; остаётся для кнопок).
 */
export function neighbourId(rows, { selectedId = null, selectedKey = null, hasMore = false } = {}, dir = 1) {
    const list = rows || [];
    let index = list.findIndex((row) => row.id === selectedId);
    if (index === -1 && selectedKey) {
        index = list.findIndex((row) => row.thread_key && row.thread_key === selectedKey);
    }
    if (index === -1) {
        return dir > 0 && list.length ? { id: list[0].id } : { id: null };
    }
    const next = index + (dir > 0 ? 1 : -1);
    if (next < 0) {
        return { id: null };
    }
    if (next >= list.length) {
        return hasMore && dir > 0 ? { id: null, needMore: true } : { id: null };
    }
    return { id: list[next].id };
}

/**
 * Кнопка для клавиши: первая с data-mc-key = key, не выключенная, видимая и
 * не внутри inert (пока грузится следующее письмо, прежнее окно inert —
 * кнопки действуют на выделенную строку, а на экране ещё прежнее письмо).
 *
 * buttons — список элементов; isVisible(el) и isInert(el) — проверки
 * страницы (в node их подменяет тест).
 */
export function pickKeyButton(buttons, key, { isVisible = () => true, isInert = () => false } = {}) {
    for (const button of buttons || []) {
        const mcKey = button && button.dataset ? button.dataset.mcKey : null;
        if (mcKey !== key || button.disabled) {
            continue;
        }
        if (isInert(button) || !isVisible(button)) {
            continue;
        }
        return button;
    }
    return null;
}
