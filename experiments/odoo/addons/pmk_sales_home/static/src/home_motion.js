/** @odoo-module **/
/**
 * Тихая анимация главных страниц (18.10.2026, вариант 1 — выбор Антона: «хочется
 * красиво, но не перегружать интерфейс»). Появление и рост полос — в CSS
 * (sales_home.scss); здесь только одно: после «Обновить» плитка, у которой
 * поменялась цифра, на миг подсвечивается — видно, что изменилось.
 *
 * Общая для главных продаж, производства и закупок: плитки у всех — .o_pmk_home__k
 * с подписью .l, числом .v и строкой .s. Сравниваем по подписи, а не по месту:
 * плитка, которой нет прав, пропадает, и номера съезжают.
 */
import { onPatched, useRef } from "@odoo/owl";

const tileText = (tile) => ["v", "s"].map((cls) => tile.querySelector("." + cls)?.textContent || "").join("|");

function snapshot(root) {
    if (!root) {
        return null;
    }
    const out = {};
    for (const tile of root.querySelectorAll(".o_pmk_home__k")) {
        out[tile.querySelector(".l")?.textContent || ""] = tileText(tile);
    }
    return out;
}

function flash(root, before) {
    for (const tile of root.querySelectorAll(".o_pmk_home__k")) {
        const label = tile.querySelector(".l")?.textContent || "";
        if (label in before && before[label] !== tileText(tile)) {
            tile.classList.add("o_pmk_home__k--hit");
            // Два кадра: класс успевает лечь без перехода, снятие — уже с переходом.
            requestAnimationFrame(() => requestAnimationFrame(() => tile.classList.remove("o_pmk_home__k--hit")));
        }
    }
}

/**
 * В setup(): `this.motion = useHomeMotion();` и в шаблоне t-ref="root" на корне.
 * В load(): `const before = this.motion.before();` до запроса и
 * `this.motion.after(before)` перед записью новых данных в состояние.
 */
export function useHomeMotion() {
    const root = useRef("root");
    let pending = null;
    onPatched(() => {
        if (pending && root.el) {
            flash(root.el, pending);
        }
        pending = null;
    });
    return {
        before: () => snapshot(root.el),
        after: (before) => {
            pending = before;
        },
    };
}
