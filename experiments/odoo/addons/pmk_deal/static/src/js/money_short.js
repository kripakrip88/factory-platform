/** @odoo-module **/
// Сумма коротко: 9 500 000 → «9,5 млн ₽» — для шапки колонки воронки
// (приёмка 01.10.2026, R10), в том же виде, что на карточке сделки.
//
// Перенос tools/money_text.py (rub_short) один в один — карточку пишет
// сервер, шапку колонки рисует браузер, и формат должен совпадать:
//   • округление «как у человека» — половина от нуля (0,5 → 1), а не к
//     чётному;
//   • разряд выбирается ПОСЛЕ округления: 999 500 — «1 млн ₽», а не
//     «1000 тыс ₽»;
//   • от сотни — целыми: «123 млн ₽», а не «123,5 млн ₽»;
//   • внутри числа и между числом и единицей — неразрывный пробел.
// Отличие одно: ноль — прочерк «—» (в шапке пустой колонки «0 ₽» читалось
// бы как «посчитано, ноль»), на сервере — «0 ₽».

const NBSP = " ";
const UNITS = [
    [1e3, "тыс"],
    [1e6, "млн"],
    [1e9, "млрд"],
];

/**
 * Округление половины от нуля до `digits` знаков. Через запись числа с
 * экспонентой, а не умножением: 1.005 * 100 в двоичной арифметике — 100,4999…
 * (как Decimal(repr(x)) на сервере).
 */
export function roundHalfUp(value, digits = 0) {
    const sign = value < 0 ? -1 : 1;
    const abs = Math.abs(value);
    let shifted = Math.round(Number(`${abs}e${digits}`));
    if (!Number.isFinite(shifted)) {
        // Число и так записано с экспонентой («1e-7»): склейка не читается.
        shifted = Math.round(abs * 10 ** digits);
    }
    return (sign * shifted) / 10 ** digits;
}

/** 12,0 → «12», 9,5 → «9,5», 63,86 → «63,9» (digits = 1). */
function decimal(value, digits) {
    let text = roundHalfUp(value, digits).toFixed(digits);
    if (text.includes(".")) {
        text = text.replace(/0+$/, "").replace(/\.$/, "");
    }
    if (text === "-0" || text === "") {
        text = "0";
    }
    return text.replace(".", ",");
}

/** 9500000 → «9 500 000» (разряды — неразрывным пробелом). */
function grouped(value) {
    const whole = roundHalfUp(value, 0);
    const sign = whole < 0 ? "-" : "";
    return sign + String(Math.abs(whole)).replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

/** «3 429 022 ₽». */
export function rub(amount) {
    return `${grouped(amount || 0)}${NBSP}₽`;
}

/** «9,5 млн ₽», «54 тыс ₽», «950 ₽»; ноль и пусто — «—». */
export function rubShort(amount) {
    amount = amount || 0;
    if (!amount) {
        return "—";
    }
    if (Math.abs(roundHalfUp(amount, 0)) < 1000) {
        return rub(amount);
    }
    const last = UNITS[UNITS.length - 1][1];
    for (const [scale, unit] of UNITS) {
        const value = amount / scale;
        const digits = Math.abs(value) >= 100 ? 0 : 1;
        if (Math.abs(roundHalfUp(value, digits)) >= 1000 && unit !== last) {
            continue;
        }
        return `${decimal(value, digits)}${NBSP}${unit}${NBSP}₽`;
    }
    return rub(amount);
}
