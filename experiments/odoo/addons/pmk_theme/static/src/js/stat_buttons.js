/** @odoo-module **/
// Кнопки-счётчики над формой: значок и число, надпись — во всплывающей
// подсказке, ноль — серым.
//
// Разбор UX, шаг 3 (решение Антона 28.09.2026, скрин 31): «надписи вообще
// убрать, а оставить символы и число, при наведении выводить подсказку».
// Надпись прячут стили (scss/forms_nexus.scss, раздел «Кнопки-счётчики»),
// а этот файл делает то, чего стилями не сделать:
//   • кладёт текст надписи в data-tooltip — подсказку по нему показывает
//     штатная служба подсказок Odoo, и в aria-label — для читалок экрана;
//   • ставит класс o_pmk_stat_zero, когда число равно нулю: ноль — «шага ещё
//     не было», он не должен выглядеть так же, как настоящее число;
//   • округляет числа до целых: «0,000» → «0», «0,00 руб» → «0 руб»
//     (Антон, 28.09.2026: «убрать сотые и тысячные знаки после запятой»).
//     Кнопка — счётчик, а не отчёт: точное значение открывается по клику.
//
// Внутри выпадашки «Ещё» надписи видны (стили), и подсказку там не ставим —
// она повторяла бы строку меню.
//
// ⚠️ ПОЧЕМУ MutationObserver, А НЕ ПАТЧ КОМПОНЕНТА. Кнопки-счётчики — не один
// компонент: половину рисует шаблон формы, половину — виджет statinfo, есть
// и полностью свои (встреча, «Обзор» производства). Число приходит после
// загрузки записи и меняется при правке, без перерисовки кнопки. Наблюдатель
// ловит всё это одним местом.
//
// Атрибуты не наблюдаем (только дерево и текст), поэтому собственные записи
// data-tooltip и классов не зацикливают наблюдатель.

const ZERO_CLASS = "o_pmk_stat_zero";

function textOf(el) {
    return (el.textContent || "").replace(/\s+/g, " ").trim();
}

// «0», «0,00 руб», «0,000» — ноль; «1», «3 429 021,97 руб» — нет. Текст без
// цифр (например, дата встречи словами) нулём не считается.
function isZero(text) {
    const digits = text.replace(/[\s  ]/g, "").replace(/[^0-9,.\-]/g, "");
    if (!/\d/.test(digits)) {
        return false;
    }
    return Number.parseFloat(digits.replace(",", ".")) === 0;
}

// Число с дробной частью через запятую: «0,000», «3 429 021,97», «-12,5».
// Точка как разделитель не ловится намеренно: так пишутся даты («30.09»),
// их трогать нельзя.
const DECIMAL = /-?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+,\d+|-?\d+,\d+/g;

function roundNumber(match) {
    const number = Number.parseFloat(match.replace(/[\s\u00a0\u202f]/g, "").replace(",", "."));
    return Math.round(number).toLocaleString("ru-RU");
}

// Правим текстовые узлы, а не innerHTML: узлы остаются теми же, и Owl при
// следующей отрисовке спокойно запишет в них новое значение, если оно
// изменится (наблюдатель тут же округлит и его).
function roundValues(button) {
    for (const valueEl of button.querySelectorAll(".o_stat_value")) {
        const walker = document.createTreeWalker(valueEl, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            DECIMAL.lastIndex = 0;
            if (DECIMAL.test(node.nodeValue)) {
                node.nodeValue = node.nodeValue.replace(DECIMAL, roundNumber);
            }
        }
    }
}

function decorate(button) {
    roundValues(button);
    const label = [...button.querySelectorAll(".o_stat_text")]
        .map(textOf)
        .filter(Boolean)
        .join(" / ");
    const valueEl = button.querySelector(".o_stat_value");
    const value = valueEl ? textOf(valueEl) : "";
    const tip = label || button.getAttribute("title") || "";
    const inMenu = Boolean(button.closest(".o-dropdown--menu"));
    if (tip && !inMenu && button.dataset.tooltip !== tip) {
        button.dataset.tooltip = tip;
        button.setAttribute("aria-label", tip);
    }
    button.classList.toggle(ZERO_CLASS, Boolean(valueEl) && isZero(value));
}

function decorateAll() {
    for (const button of document.querySelectorAll(".o-form-buttonbox .oe_stat_button")) {
        decorate(button);
    }
}

function start() {
    decorateAll();
    new MutationObserver(decorateAll).observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true,
    });
}

if (document.body) {
    start();
} else {
    document.addEventListener("DOMContentLoaded", start, { once: true });
}
