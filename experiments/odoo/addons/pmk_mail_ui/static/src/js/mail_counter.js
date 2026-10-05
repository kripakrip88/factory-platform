/** @odoo-module **/
/**
 * Счётчик новых писем на пункте «Продажи → Почта» и во вкладке браузера
 * (разбор удобства, шаг 41, Г12, 05.10.2026).
 *
 * ЧТО СЧИТАЕМ. Непрочитанные во «Входящих» ящиков, доступных человеку, за
 * последние 30 дней (models/mail_client_step41.py, pmk_mail_unread_count):
 * старше окна отметки «прочитано» с mail.ru не обновляются, число врало бы.
 * Бейдж папки «Входящие» в самой почте — по-прежнему все непрочитанные.
 *
 * ОТКУДА И КОГДА. Первое число приходит со страницей (session_info,
 * models/ir_http.py) — без запроса при загрузке. Ключа нет (у человека нет
 * почты) — сервис ничего не делает. Дальше число перечитывается (одним
 * запросом, с паузой 1,5 с — правки идут пачкой):
 *   - по сигналу синхронизации почты mail_client.sync, если проход что-то
 *     изменил (прочитали письмо на mail.ru, пришло новое) — он приходит
 *     всем, кто видит ящик, раз в 2 минуты при изменениях;
 *   - после правок в самой почте (крючки модуля почты noteListEdit и
 *     inboxUnreadChanged — static/src/js/step41_mail.js);
 *   - запасной опрос раз в 5 минут — только на видимой вкладке, и при
 *     возврате на вкладку: сигнал шины мог не дойти (сон ноутбука, обрыв).
 * Вкладка браузера — штатный сервис title ядра: «(3) Почта - Odoo»
 * (setCounters складывает наше число с числом Обсуждений ядра).
 *
 * ПУНКТ МЕНЮ. Ядро рисует пункт без места под число, поэтому число ставится
 * атрибутом data-pmk-count на элемент пункта (по data-menu-xmlid), а рисует
 * его стиль (static/src/scss/mail_step41.scss, ::after). Атрибут
 * ставится после каждой отрисовки шапки и при смене числа — и в строке
 * разделов, и в мобильной шторке меню (её ядро рисует порталом в body,
 * поэтому поиск по документу, а не по корню шапки). Пункт ушёл в «Ещё»
 * строки разделов (узкое окно) — там числа нет: меню «Ещё» рисуется только
 * при открытии, без перерисовки шапки.
 *
 * Сервисы — через env.services, не useService (грабля шага 31: промис из
 * useService у уничтоженного компонента висит вечно).
 */
import { EventBus, useEffect } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { NavBar } from "@web/webclient/navbar/navbar";

import {
    MAIL_MENU_XMLID,
    POLL_MS,
    REFRESH_DELAY_MS,
    counterText,
    counterTitle,
    shouldRefresh,
} from "./mail_counter_rules";

export const pmkMailCounterService = {
    dependencies: ["bus_service", "orm", "title"],

    start(env, { bus_service: busService, orm, title }) {
        const events = new EventBus();
        const enabled = Object.prototype.hasOwnProperty.call(session, "pmk_mail_unread");
        let count = 0;
        let timer = null;
        let running = false;
        let again = false;

        const apply = (value) => {
            count = Math.max(0, Math.floor(Number(value) || 0));
            title.setCounters({ pmk_mail: count });
            events.trigger("change", count);
        };

        const load = async () => {
            timer = null;
            if (running) {
                again = true;
                return;
            }
            running = true;
            try {
                apply(await orm.silent.call("mail.client.account", "pmk_mail_unread_count", []));
            } catch {
                // Обрыв связи, выход из системы — число прежнее, следующий
                // сигнал или опрос перечитает.
            } finally {
                running = false;
                if (again) {
                    again = false;
                    schedule();
                }
            }
        };

        const schedule = (delay = REFRESH_DELAY_MS) => {
            if (!enabled) {
                return;
            }
            browser.clearTimeout(timer);
            timer = browser.setTimeout(load, delay);
        };

        if (enabled) {
            apply(session.pmk_mail_unread);
            busService.subscribe("mail_client.sync", (payload) => {
                if (shouldRefresh(payload)) {
                    schedule();
                }
            });
            const visible = () => document.visibilityState === "visible";
            browser.setInterval(() => {
                if (visible()) {
                    schedule(0);
                }
            }, POLL_MS);
            document.addEventListener("visibilitychange", () => {
                if (visible()) {
                    schedule(0);
                }
            });
        }

        return {
            get enabled() {
                return enabled;
            },
            get count() {
                return count;
            },
            bus: events,
            refresh() {
                schedule();
            },
        };
    },
};

registry.category("services").add("pmk_mail_counter", pmkMailCounterService);

patch(NavBar.prototype, {
    setup() {
        super.setup();
        const counter = this.env.services.pmk_mail_counter;
        if (!counter || !counter.enabled) {
            return;
        }
        useEffect(() => {
            this.pmkMarkMailCount(counter.count);
        });
        useBus(counter.bus, "change", () => this.pmkMarkMailCount(counter.count));
    },

    /** Число на пункте «Почта» — атрибутом, рисует стиль (mail_step41.scss). */
    pmkMarkMailCount(count) {
        const text = counterText(count);
        const title = counterTitle(count);
        for (const el of document.querySelectorAll(`[data-menu-xmlid="${MAIL_MENU_XMLID}"]`)) {
            if (text) {
                el.dataset.pmkCount = text;
                el.setAttribute("title", title);
            } else if (el.dataset.pmkCount) {
                delete el.dataset.pmkCount;
                el.removeAttribute("title");
            }
        }
    },
});
