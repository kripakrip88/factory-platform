/**
 * Подсветка активного пункта во второй строке шапки.
 *
 * ЗАЧЕМ. Ядро Odoo 19 не помечает текущий подраздел никак: в шаблоне
 * web.NavBar.SectionsMenu пункт рисуется как
 *     <DropdownItem class="'o_nav_entry'" .../>
 * — ни класса active, ни aria-current (navbar.xml:166). Пользователь видит
 * строку пунктов и не понимает, где находится. Правило nav-state-active
 * требует, чтобы текущее положение читалось визуально.
 *
 * ПОЧЕМУ ВЫЧИСЛЯЕМ САМИ. menuService хранит только текущее ПРИЛОЖЕНИЕ
 * (currentAppId в menu_service.js), понятия «текущий пункт» в нём нет вовсе.
 *
 * КАК ОПРЕДЕЛЯЕМ — И ПОЧЕМУ НЕ ПО АДРЕСУ.
 * Первая версия сравнивала первый сегмент адресной строки с ссылкой пункта.
 * Это давало подсветку, отстающую на один шаг: открыты «Лиды» — подсвечены
 * «Заказы клиентов». Причина в том, что запись в адресную строку отложена —
 * router.js кладёт её в setTimeout (makeDebouncedPush, router.js:405-410),
 * поэтому в момент, когда шина сообщает о новом действии, location.pathname
 * ещё держит предыдущее.
 *
 * Вторая причина не использовать адрес: путь не всегда «первый сегмент —
 * действие». Odoo складывает стек в вид active_id/action/res_id
 * (router.js:134), так что у вложенного действия первым сегментом идёт
 * идентификатор родителя, а не то, что нам нужно.
 *
 * Поэтому вторая версия брала router.current.action — состояние роутера,
 * которое обновляется сразу, до записи в адрес, — и сравнивала со ссылкой
 * пункта (getMenuItemHref). С шага 23 первым источником стал сам контроллер
 * действия, а сравнение идёт по номеру и path — почему, см. ниже «ШАГ 23».
 * Роутер и адрес остались запасными источниками. Ключи — в том же виде, в
 * каком ядро пишет действие в адрес: число или строка с точкой дают
 * «action-<N>», остальное — сам путь (развилка stateToUrl, router.js:97-101).
 *
 * ПОЧЕМУ ПРАВИМ DOM, А НЕ ШАБЛОН. Шапку уже наследуют ядро, тема
 * theme_liquid_glass и мы — третий участник в том же узле нам дорого обошёлся.
 * К тому же класс через шаблон потребовал бы перерисовывать шапку на каждое
 * действие, а перерисовка тянет adapt() с пересчётом ширин всех пунктов.
 *
 * КОГДА ПЕРЕСЧИТЫВАЕМ — И ПОЧЕМУ ДВАЖДЫ.
 *  · ACTION_MANAGER:UI-UPDATED — шина сообщает о каждом открытом действии
 *    (action_service.js:1044);
 *  · ROUTE_CHANGE — клик по внутренней ссылке и навигация «назад/вперёд»
 *    (router.js:286, 301, 334);
 *  · после каждого рендера шапки — иначе класс слетит, когда adapt()
 *    перерисует пункты, схлопнув часть из них в меню «ещё».
 *
 * Каждый пересчёт делаем ДВА раза: сразу и в следующем такте. Причина в том,
 * что состояние роутера обновляется строкой `state = nextState` в самом конце
 * doPush (router.js), а сам doPush обычно отложен в setTimeout
 * (makeDebouncedPush) — и ROUTE_CHANGE после него НЕ триггерится. То есть в
 * момент, когда шина сообщает о новом действии, состояние ещё старое, и
 * никто больше об его обновлении не сообщит.
 *
 * Часть веток action_service толкает состояние синхронно (там pushState
 * вызывается с { sync: true }) — для них верен первый пересчёт. Для остальных
 * срабатывает второй: doPush уже стоит в очереди макрозадач, поэтому наш
 * setTimeout(0), поставленный позже, выполнится после него. Два дешёвых
 * прохода по десятку узлов надёжнее, чем угадывать, какая ветка сработала.
 *
 * ШАГ 23 (01.10.2026): ПО НОМЕРУ ДЕЙСТВИЯ И path, А НЕ ПО ОДНОЙ ССЫЛКЕ.
 * «Воронка сделок» и «Рассылка прайсов» не подсвечивались. Сравнение одной
 * строки «ссылка пункта = состояние роутера» ломалось, когда у пункта и у
 * открытого действия разные ключи одного и того же:
 *  · Воронка открывается и адресом /odoo/crm: это серверное действие
 *    crm.action_your_pipeline с path «crm», оно возвращает окно воронки
 *    (номер 348), и ядро приписывает окну path серверного
 *    (action_service.js, _executeServerAction: nextAction.path ||= …).
 *    Роутер держит «crm», у пункта ссылка «action-348» — мимо.
 *  · Рассылка прайсов — серверное действие без path; оно возвращает окно
 *    без номера, и в роутере вовсе нет действия (адрес
 *    /odoo/pmk.price.mailing/1). Лечится path у самого действия
 *    («price-mailing», pmk_purchase/views/price_mailing_views.xml): окно
 *    получает его от ядра, пункт — через actionPath.
 * Теперь у открытого действия и у пункта берём ОБА ключа — номер и path —
 * и пункт горит, если совпал любой (active_section_keys.js). Источник —
 * currentController.action: сам контроллер, а не адрес. Так же ядро само
 * определяет текущее приложение после загрузки — сравнивает
 * currentController.action.id с menu.actionID (webclient.js).
 * Контроллер уже новый в момент ACTION_MANAGER:UI-UPDATED (стек коммитится
 * в onMounted до сигнала), поэтому верен уже первый проход.
 * Нет ключей у контроллера (окно без номера и path — например, расчёт,
 * открытый кнопкой из сделки) — берём роутер, затем адрес, как раньше.
 * Ключи роутера с ключами контроллера НЕ смешиваем: в первом проходе роутер
 * ещё держит прошлое действие, и загорелся бы прошлый пункт.
 */

import { patch } from "@web/core/utils/patch";
import { useBus } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { router, routerBus } from "@web/core/browser/router";
import { NavBar } from "@web/webclient/navbar/navbar";
import { useEffect } from "@odoo/owl";
import { actionKey, controllerKeys, isMenuActive } from "@pmk_theme/js/active_section_keys";

patch(NavBar.prototype, {
    setup() {
        super.setup();
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.pmkScheduleMark());
        useBus(routerBus, "ROUTE_CHANGE", () => this.pmkScheduleMark());
        useEffect(() => {
            this.pmkMarkActiveSection();
        });
    },

    /**
     * Пересчёт сразу и в следующем такте — см. пояснение в шапке файла.
     * Отложенный вызов безопасен после размонтирования: pmkMarkActiveSection
     * выходит сам, если у компонента больше нет корневого узла.
     */
    pmkScheduleMark() {
        this.pmkMarkActiveSection();
        browser.setTimeout(() => this.pmkMarkActiveSection(), 0);
    },

    /**
     * Ключи открытого действия — номер и path (см. шапку файла, «шаг 23»).
     * Порядок источников: контроллер → роутер → адрес. Берём первый
     * непустой и не смешиваем.
     */
    pmkCurrentKeys() {
        const controller = this.actionService.currentController;
        const fromController = controllerKeys(controller && controller.action);
        if (fromController.length) {
            return fromController;
        }
        // Развилка actionKey повторяет stateToUrl (router.js:97-101).
        const fromRouter = actionKey(router.current && router.current.action);
        if (fromRouter) {
            return [fromRouter];
        }
        // Запасной путь: последний сегмент вида action-N из адреса.
        const m = /\/odoo\/(?:.*\/)?(action-[^/?#]+)/.exec(browser.location.pathname);
        return m ? [m[1]] : [];
    },

    pmkMarkActiveSection() {
        const root = this.root.el;
        if (!root) {
            return;
        }

        const keys = this.pmkCurrentKeys();
        const active = this.currentAppSections.find((section) => isMenuActive(section, keys));
        const activeId = active ? String(active.id) : null;

        // Цвет текущего раздела отдаём в CSS одной переменной на всю шапку —
        // так обе строки подсвечиваются одним цветом, а сами цвета остаются
        // в scss и не дублируются в коде.
        const app = this.currentApp;
        if (app && app.xmlid) {
            root.dataset.pmkApp = app.xmlid;
        } else {
            delete root.dataset.pmkApp;
        }

        for (const el of root.querySelectorAll(".o_menu_sections [data-section]")) {
            // У обычного пункта data-section висит на самой ссылке, у пункта с
            // потомками — на <span> внутри кнопки-выпадашки. Красим то, что видно.
            const target = el.closest(".o_nav_entry, .dropdown-toggle, button") || el;
            const on = activeId !== null && String(el.dataset.section) === activeId;

            target.classList.toggle("pmk_section--active", on);
            if (on) {
                target.setAttribute("aria-current", "page");
            } else {
                target.removeAttribute("aria-current");
            }
        }
    },
});
