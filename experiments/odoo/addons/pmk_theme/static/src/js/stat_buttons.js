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
//     не было», он не должен выглядеть так же, как настоящее число.
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

function decorate(button) {
    const label = [...button.querySelectorAll(".o_stat_text")]
        .map(textOf)
        .filter(Boolean)
        .join(" ");
    const valueEl = button.querySelector(".o_stat_value");
    const value = valueEl ? textOf(valueEl) : "";
    const tip = label || button.getAttribute("title") || "";
    if (tip && button.dataset.tooltip !== tip) {
        button.dataset.tooltip = tip;
        button.setAttribute("aria-label", value ? `${tip}: ${value}` : tip);
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
