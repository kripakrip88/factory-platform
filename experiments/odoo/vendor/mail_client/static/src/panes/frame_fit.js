/**
 * ПРАВКА ПМК: рамка письма ростом с само письмо («Почта как в Mail.ru», шаг 2,
 * А1; шаг 17 плана, 29.09.2026).
 *
 * Было: рамка занимала остаток окна чтения и прокручивалась сама. Колесо над
 * письмом крутило только текст, над шапкой — ничего, а шапка с вложениями и
 * адресатами стояла на месте и отнимала место у текста. Стало: у рамки своей
 * прокрутки нет, её высота — высота письма, и окно чтения прокручивается
 * целиком, где бы ни стоял курсор (колесо над рамкой, которой некуда
 * крутиться, браузер передаёт окну вокруг неё).
 *
 * Высоту меряем при СХЛОПНУТОЙ рамке (высота 0), а не по текущей. Письма
 * бывают с высотой «от окна» (min-height: 100vh у обёртки). Мерка по
 * текущей высоте давала бы «письмо чуть выше рамки» — рамку растим, письмо
 * растёт следом, и так без конца. Мерка при нулевой высоте от прежней
 * высоты не зависит — цикла нет по построению. Такое письмо остаётся со
 * своей небольшой прокруткой внутри рамки (на ту часть, что ниже «окна»):
 * подогнать его целиком нельзя в принципе, и это лучше бесконечного роста.
 * (Документ srcdoc браузер всегда разбирает в стандартном режиме, не в
 * quirks, — height="100%" у таблицы от окна не зависит; проверено.)
 * На время мерки снимаем и то, что CSS окна чтения даёт рамке сверх высоты
 * (min-height, flex-grow: короткое письмо тянет белый лист до низа окна),
 * иначе «ноль» был бы не нулём. Прокрутку окна чтения сохраняем: на время
 * мерки рамка короче, и браузер мог бы прижать прокрутку к новому низу.
 *
 * Полоса прокрутки окна чтения на время мерки не должна пропадать. На
 * Windows и на Mac с мышью она занимает ширину (около 15 px): схлопнули
 * рамку — окну нечего прокручивать, полоса ушла, рамка стала шире, и
 * письмо мерилось по широкой строке. После мерки полоса возвращалась, текст
 * переносился заново, и конец письма уходил под прокрутку внутри рамки
 * (проверка 30.09: рамка 6059 px при письме 6159 px). Ширину окна держит
 * scrollbar-gutter: stable (mail_client.scss); на время мерки окну ещё и
 * ставим overflow-y: scroll — для браузеров без scrollbar-gutter (Safari
 * до 18.2). При scrollbar-gutter это ничего не меняет.
 *
 * Широкое письмо (таблица 700–1000 px) прокручивается вбок внутри рамки:
 * ширина рамки — ширина окна, к высоте добавляется толщина нижней полосы
 * прокрутки, чтобы она не легла на последнюю строку.
 *
 * Пересчёт: догрузилась картинка (load/error ловим на погружении — эти
 * события не всплывают), сменился размер документа письма или ширина самой
 * рамки (ResizeObserver). Не чаще раза за кадр.
 *
 * Подгоняем, как только документ письма разобран, а не по load рамки (см.
 * followFrame): load ждёт все картинки письма, и с медленной картинкой
 * новое письмо секундами стояло в высоте прежнего, со своей прокруткой и с
 * ещё не снятыми ссылками javascript:.
 *
 * Работает только при allow-same-origin в песочнице рамки (без него
 * contentDocument закрыт). Тогда подгонки нет, и окно чтения оставляет
 * прежнее поведение: рамка на всю оставшуюся высоту с прокруткой внутри.
 * allow-scripts у рамки НЕТ и не будет: скрипты письма не выполняются.
 * Пара allow-same-origin + allow-scripts снимает песочницу целиком.
 */

import { forwardableKey, isTypingTarget } from "./hotkeys";

const XLINK = "http://www.w3.org/1999/xlink";
// Рамка подогнана (высота инлайном); без класса — прежнее поведение из CSS.
const FIT_CLASS = "o_mail_client_frame_fit";
// Документ, под который рамка подогнана последним. Элемент рамки один на все
// письма (прежнее письмо на время загрузки не убирается), меняется только
// srcdoc — по этой записи документ прежнего письма отличаем от нового.
const fittedDocs = new WeakMap();

function frameDocument(frame) {
    try {
        return frame.contentDocument;
    } catch {
        return null;
    }
}

/**
 * Страховка к санитайзеру. html_sanitize при синхронизации уже вычищает
 * ссылки «javascript:», но с allow-same-origin цена промаха выросла: ссылка с
 * target=_blank (его ставит <base> нашего листа письма) открывается вне
 * песочницы, а новое окно получает происхождение рамки — то есть наше.
 * Адрес разбираем как браузер (табуляции, переводы строк, регистр), а не
 * сравниваем строку.
 */
function disarmScriptLinks(doc) {
    for (const link of doc.querySelectorAll("a, area")) {
        const raw = link.getAttribute("href") ?? link.getAttributeNS(XLINK, "href");
        if (raw === null) {
            continue;
        }
        let protocol = "";
        try {
            protocol = new URL(raw).protocol;
        } catch {
            continue; // относительный адрес — не скрипт
        }
        if (protocol === "javascript:" || protocol === "vbscript:") {
            link.removeAttribute("href");
            link.removeAttributeNS(XLINK, "href");
        }
    }
}

/**
 * Подогнать рамку под высоту письма и держать подогнанной.
 *
 * @param {HTMLIFrameElement} frame
 * @param {{ getScroller?: () => HTMLElement | null }} [options]
 *        getScroller — окно чтения, чью прокрутку беречь при мерке.
 * @returns {(() => void) | null} остановка слежения; null — документ рамки
 *          недоступен, подгонки нет.
 */
export function fitFrame(frame, { getScroller } = {}) {
    const doc = frameDocument(frame);
    if (!doc || !doc.documentElement || !doc.body) {
        return null;
    }
    disarmScriptLinks(doc);
    fittedDocs.set(frame, doc);

    const view = frame.ownerDocument.defaultView;
    const style = frame.style;
    let raf = 0;
    let stopped = false;

    const measure = () => {
        raf = 0;
        // Письмо в рамке уже другое (открыли следующее) или рамки нет.
        if (stopped || !frame.isConnected || frame.contentDocument !== doc) {
            return;
        }
        const root = doc.scrollingElement || doc.documentElement;
        const scroller = getScroller && getScroller();
        const top = scroller ? scroller.scrollTop : 0;
        // Полоса окна на время мерки остаётся (см. шапку файла).
        const overflowY = scroller ? scroller.style.overflowY : "";
        if (scroller) {
            scroller.style.overflowY = "scroll";
        }
        style.setProperty("min-height", "0px");
        style.setProperty("flex-grow", "0");
        style.height = "0px";
        // +1: округление до целых не должно давать полосу прокрутки на
        // полпикселя. Цикла не будет — следующая мерка снова с нуля.
        const content = root.scrollHeight + 1;
        style.height = `${content}px`;
        const bar = frame.contentWindow.innerHeight - root.clientHeight;
        if (bar > 0) {
            style.height = `${content + bar}px`;
        }
        style.removeProperty("min-height");
        style.removeProperty("flex-grow");
        if (scroller) {
            scroller.style.overflowY = overflowY;
            if (scroller.scrollTop !== top) {
                scroller.scrollTop = top;
            }
        }
    };
    const schedule = () => {
        if (!raf && !stopped) {
            raf = view.requestAnimationFrame(measure);
        }
    };

    const observer = new view.ResizeObserver(schedule);
    observer.observe(frame);
    observer.observe(doc.documentElement);
    observer.observe(doc.body);
    doc.addEventListener("load", schedule, true);
    doc.addEventListener("error", schedule, true);
    const forward = forwardKeys(frame, view);
    doc.addEventListener("keydown", forward);
    measure();

    return () => {
        stopped = true;
        observer.disconnect();
        if (raf) {
            view.cancelAnimationFrame(raf);
            raf = 0;
        }
        doc.removeEventListener("load", schedule, true);
        doc.removeEventListener("error", schedule, true);
        doc.removeEventListener("keydown", forward);
    };
}

/**
 * ПРАВКА ПМК (шаг 41, А6): горячие клавиши почты работают и тогда, когда
 * фокус в тексте письма (щёлкнули по письму, чтобы выделить текст). Рамка
 * своих клавиш наружу не отдаёт, поэтому знакомые почте клавиши
 * (forwardableKey, hotkeys.js: R A F L / Esc — без Ctrl, Cmd, Alt; стрелки
 * не пересылаются — в тексте письма они прокручивают письмо)
 * пересылаются копией на элемент рамки в окне почты: оттуда она всплывает к
 * сервису клавиш ядра и к «/» корня почты. Почта клавишу взяла — у
 * исходной отменяется действие браузера (прокрутка рамки, быстрый поиск).
 * Поле ввода внутри письма (бывает в рассылках) — не трогаем.
 */
function forwardKeys(frame, view) {
    return (ev) => {
        if (!forwardableKey(ev) || isTypingTarget(ev.target)) {
            return;
        }
        const copy = new view.KeyboardEvent("keydown", {
            key: ev.key,
            code: ev.code,
            repeat: ev.repeat,
            shiftKey: ev.shiftKey,
            bubbles: true,
            cancelable: true,
        });
        frame.dispatchEvent(copy);
        if (copy.defaultPrevented) {
            ev.preventDefault();
        }
    };
}

/**
 * Вести рамку окна чтения после смены srcdoc (открыли письмо, «Показать
 * картинки»): снять подгонку прежнего письма и подогнать новое, как только
 * его документ разобран (readyState «interactive»), — не дожидаясь load
 * рамки, который ждёт все картинки письма. Тогда же снимаются ссылки
 * javascript:. Пока нового документа нет — прежнее поведение из CSS (рамка
 * на остаток окна), а не высота прежнего письма.
 *
 * Документа, разобранного к нужному кадру, ждём опросом раз в кадр: у рамки
 * нет события «документ сменился», а load приходит последним. load тоже
 * слушаем — он ловит то, до чего опрос не дошёл (вкладка в фоне — кадров
 * нет; пустое письмо — рамка открыла about:blank, а не about:srcdoc).
 *
 * @param {HTMLIFrameElement} frame
 * @param {{ getScroller?: () => HTMLElement | null }} [options] — как у fitFrame.
 * @returns {() => void} остановка слежения.
 */
export function followFrame(frame, { getScroller } = {}) {
    const view = frame.ownerDocument.defaultView;
    // Что в рамке сейчас — прежнее письмо: srcdoc только что сменили, а
    // браузер заменяет документ не сразу. У новой рамки прежнего письма нет
    // (там пустой about:blank, его отсекает проверка адреса ниже).
    const previous = fittedDocs.has(frame) ? frameDocument(frame) : null;
    let stopFit = null;
    let fitted = null;
    let raf = 0;

    const showFallback = () => {
        frame.classList.remove(FIT_CLASS);
        frame.style.removeProperty("height");
    };
    const attach = (doc) => {
        if (stopFit) {
            stopFit();
        }
        frame.classList.add(FIT_CLASS);
        stopFit = fitFrame(frame, { getScroller });
        fitted = stopFit ? doc : null;
        if (!stopFit) {
            showFallback();
        }
    };
    const isNew = (doc) => Boolean(doc) && doc !== previous && doc !== fitted;
    const poll = () => {
        raf = 0;
        const doc = frameDocument(frame);
        if (!frame.isConnected || !doc) {
            return; // рамки нет или документ закрыт — прежнее поведение
        }
        if (isNew(doc) && doc.URL === "about:srcdoc" && doc.readyState !== "loading") {
            attach(doc);
            return;
        }
        raf = view.requestAnimationFrame(poll);
    };
    const onLoad = () => {
        const doc = frameDocument(frame);
        // Уже подогнано опросом — дальше следит fitFrame. Или это load
        // прежнего письма (его картинка догрузилась, пока браузер разбирал
        // новое) — ждём дальше.
        if (!isNew(doc)) {
            return;
        }
        if (raf) {
            view.cancelAnimationFrame(raf);
            raf = 0;
        }
        attach(doc);
    };

    showFallback();
    frame.addEventListener("load", onLoad);
    poll();

    return () => {
        frame.removeEventListener("load", onLoad);
        if (raf) {
            view.cancelAnimationFrame(raf);
            raf = 0;
        }
        if (stopFit) {
            stopFit();
            stopFit = null;
        }
    };
}
