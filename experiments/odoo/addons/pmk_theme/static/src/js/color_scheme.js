/** @odoo-module **/
/**
 * Тема у человека (разбор UX, шаг 40): переключатель в шапке пишет выбор в
 * res.users (pmk_color_scheme), а не только в браузер. На другом компьютере
 * тема та же; при первом входе выбор, сохранённый в браузере до шага 40,
 * переносится на сервер.
 *
 * КАК УСТРОЕНО. Механизм переключения — у чужой темы theme_nexus
 * (vendor/theme_nexus/static/src/js/dark_mode.js): NavBar.nexusDarkState,
 * копия в localStorage, класс o_nexus_dark на body. Её файл не трогаем:
 *   • onWillStart — до первой отрисовки ставим состояние по серверу
 *     (initialDark). Сервер к этому моменту уже нарисовал body с нужным
 *     классом (views/webclient_color_scheme.xml) — эффект темы при монтировании
 *     класс не меняет, вспышки нет; кружок переключателя сразу на своём месте;
 *   • useEffect — состояние сменилось (переключатель, первый вход с
 *     сохранённой в браузере темой) — пишем на сервер (schemeToSave).
 * Оба крючка срабатывают после всей цепочки setup, поэтому порядок патчей
 * (наш модуль грузится раньше theme_nexus) не важен.
 *
 * ⚠️ ЗАПИСЬ — ЧЕРЕЗ env.services.orm, НЕ useService: защищённый компонентом
 * промис не разрешается после его уничтожения (грабля шага 31, воронка).
 * Без theme_nexus (nexusDarkState нет) — ничего не делаем.
 */
import { onWillStart, useEffect } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { NavBar } from "@web/webclient/navbar/navbar";
import { OWNER_KEY, initialDark, schemeToSave } from "@pmk_theme/js/color_scheme_rules";

patch(NavBar.prototype, {
    setup() {
        super.setup(...arguments);
        onWillStart(() => {
            const state = this.nexusDarkState;
            if (!state) {
                return;
            }
            let storedOwner = null;
            try {
                storedOwner = browser.localStorage.getItem(OWNER_KEY);
                browser.localStorage.setItem(OWNER_KEY, String(user.userId));
            } catch {
                // Хранилище закрыто (приватное окно) — тему всё равно задал сервер.
            }
            state.isDark = initialDark({
                serverScheme: session.pmk_color_scheme,
                storedOwner,
                uid: user.userId,
                vendorDark: state.isDark,
            });
        });
        useEffect(
            (isDark) => {
                const scheme = schemeToSave(session.pmk_color_scheme, isDark);
                const orm = this.env.services && this.env.services.orm;
                if (!scheme || !orm) {
                    return;
                }
                const previous = session.pmk_color_scheme;
                session.pmk_color_scheme = scheme;
                orm.silent.call("res.users", "pmk_set_color_scheme", [scheme]).catch(() => {
                    // Не записалось (нет связи) — тема на экране уже сменилась,
                    // сервер помнит прежнюю. Возвращаем её и сюда: следующее
                    // переключение сравнится с ней и запишет.
                    if (session.pmk_color_scheme === scheme) {
                        session.pmk_color_scheme = previous;
                    }
                });
            },
            () => [this.nexusDarkState ? this.nexusDarkState.isDark : undefined]
        );
    },
});
