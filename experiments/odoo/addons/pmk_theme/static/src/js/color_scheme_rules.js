/** @odoo-module **/
/**
 * Тема у человека, а не у браузера (разбор UX, шаг 40) — чистые правила.
 * Без импортов Odoo: их гоняет node вне браузера. Использует color_scheme.js.
 *
 * Сервер хранит выбор в res.users.pmk_color_scheme: "dark", "light" или
 * пусто (ещё не выбирал — показываем светлую). Браузер хранит копию в ключе
 * чужой темы theme_nexus (nexus_theme_dark_mode = "1"/"0") и номер того, чья
 * это копия (OWNER_KEY).
 */
export const OWNER_KEY = "pmk_theme_owner_uid";

/**
 * С какой темы начать до первой отрисовки шапки.
 *  • выбор на сервере есть — он главный (копия в браузере могла остаться от
 *    другого компьютера, от другого человека или быть недоступной);
 *  • выбора нет, а копия в браузере чужая (на общем компьютере работал
 *    другой человек) — светлая, чужое не переносим;
 *  • выбора нет, копия своя или ничья (записана до шага 40) — она: так
 *    переносится сохранённая тема Антона при первом входе.
 */
export function initialDark({ serverScheme, storedOwner, uid, vendorDark }) {
    if (serverScheme === "dark" || serverScheme === "light") {
        return serverScheme === "dark";
    }
    if (storedOwner !== null && storedOwner !== undefined && storedOwner !== String(uid)) {
        return false;
    }
    return Boolean(vendorDark);
}

/**
 * Что записать на сервер, когда тема на экране стала isDark: "dark",
 * "light" или null — ничего (совпадает; пусто на сервере = светлая).
 * isDark не булево (тема theme_nexus снята) — ничего.
 */
export function schemeToSave(serverScheme, isDark) {
    if (typeof isDark !== "boolean") {
        return null;
    }
    const effective = serverScheme === "dark" ? "dark" : "light";
    const current = isDark ? "dark" : "light";
    return current === effective ? null : current;
}
