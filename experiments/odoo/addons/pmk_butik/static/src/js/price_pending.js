/** @odoo-module **/
/**
 * №314: ручные цены металла — не сохраняются сами (Антон 22.10.2026: «лучше после редактирования
 * ячейки активируется кнопка „Сохранить“; если кликает по другой странице — всплывающее окно с
 * изменениями было → стало и варианты выбора»).
 *
 * Несохранённые цены живут здесь, по расчёту (переживают переход между вкладками формы). Таблица
 * «Конструкции» (konstr_grid.js) показывает их и кнопку «Сохранить цены (N)». Уход со страницы
 * расчёта — любой: меню, хлебные крошки, другая запись — перехватывает форма (патч FormController
 * ниже): окно «было → стало» с «Сохранить» / «Не сохранять» / «Остаться». Закрытие вкладки
 * браузера — штатное предупреждение браузера.
 */
import { Component, reactive } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

const MODEL = "pmk.metal.spec";
export const pendingPrices = reactive({});

export function pendingList(specId) {
    return Object.entries(pendingPrices[specId] || {}).map(([key, item]) => ({ key, ...item }));
}

export function setPending(specId, key, item) {
    const bucket = (pendingPrices[specId] = pendingPrices[specId] || {});
    if (String(item.value).replace(/\s/g, "") === String(item.old || "").replace(/\s/g, "")) {
        delete bucket[key];
    } else {
        bucket[key] = item;
    }
    if (!Object.keys(bucket).length) {
        delete pendingPrices[specId];
    }
}

export function clearPending(specId) {
    delete pendingPrices[specId];
}

export async function savePending(orm, specId) {
    const items = pendingList(specId);
    if (!items.length) {
        return null;
    }
    const prices = Object.fromEntries(items.map((item) => [item.key, item.value]));
    const data = await orm.call(MODEL, "konstr_save_prices", [[specId], prices]);
    clearPending(specId);
    return data;
}

export function money(value) {
    const num = Number(String(value || "").replace(/\s/g, "").replace(",", "."));
    return num ? Math.round(num).toLocaleString("ru-RU") : "—";
}

class PendingPricesDialog extends Component {
    static template = "pmk_butik.PendingPricesDialog";
    static components = { Dialog };
    static props = { items: Array, onChoice: Function, close: Function };

    money(value) {
        return money(value);
    }

    choose(choice) {
        this.props.onChoice(choice);
        this.props.close();
    }
}

export function askPendingPrices(env, specId) {
    return new Promise((resolve) => {
        env.services.dialog.add(
            PendingPricesDialog,
            { items: pendingList(specId), onChoice: resolve },
            { onClose: () => resolve("stay") }
        );
    });
}

patch(FormController.prototype, {
    async _pmkPricesGuard() {
        const specId = this.props.resModel === MODEL && this.model.root.resId;
        if (!specId || !pendingList(specId).length) {
            return true;
        }
        const choice = await askPendingPrices(this.env, specId);
        if (choice === "save") {
            await savePending(this.env.services.orm, specId);
            return true;
        }
        if (choice === "discard") {
            clearPending(specId);
            return true;
        }
        return false;
    },

    async beforeLeave(options = {}) {
        if (!options.forceLeave && !(await this._pmkPricesGuard())) {
            return false;
        }
        return super.beforeLeave(...arguments);
    },

    async onPagerUpdate() {
        if (!(await this._pmkPricesGuard())) {
            return;
        }
        return super.onPagerUpdate(...arguments);
    },

    async beforeUnload(ev) {
        if (this.props.resModel === MODEL && pendingList(this.model.root.resId).length) {
            ev.preventDefault();
            ev.returnValue = "Цены не сохранены";
        }
        return super.beforeUnload(...arguments);
    },
});
