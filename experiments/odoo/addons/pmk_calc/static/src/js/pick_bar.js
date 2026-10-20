/** @odoo-module **/
// Действия над отмеченными позициями расчёта — в строке заголовков таблицы,
// поверх названий колонок, пока что-то отмечено (Антон 13.10.2026: полоса
// «Перенести / копировать / удалить» над списком «занимает очень много места»;
// раньше — просьба «кнопку переноса объединить в выпадашку»).
//
// Рисует заголовок колонки галочек (pick_head.js, pick_toggle.xml):
// «N поз.» (снять все), меню «Перенести в ▾» со всеми калькуляторами, кроме
// своего, «Копировать» и «Удалить» отмеченные. Откуда список — опция колонки
// pick_source (metal | dobor | vent). Действие делает сервер
// (pmk.metal.spec.pmk_bulk), расчёт перечитывается.
//
// Новый калькулятор — строка в TARGETS и ветки на сервере (spec_move.py).

import { Component, toRaw } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// Поставить всем строкам списка одно значение — пачкой: промежуточные строки
// без пересчёта с сервером, последняя — обычным update (счётчик «Отмечено»).
export async function pickAll(records, name, value) {
    const recs = records.filter((r) => r.data[name] !== value);
    for (const [i, rec] of recs.entries()) {
        if (i < recs.length - 1) {
            await rec._update({ [name]: value }, { withoutOnchange: true, withoutParentUpdate: true });
        } else {
            await rec.update({ [name]: value });
        }
    }
}

const TARGETS = [
    { key: "metal", label: "Конструкции" },
    { key: "dobor", label: "Доборные элементы" },
    { key: "vent", label: "Вентзонты" },
];

export class PmkPickActions extends Component {
    static template = "pmk_calc.PmkPickActions";
    static components = { Dropdown, DropdownItem };
    static props = { list: Object, name: String, source: String };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
    }

    get record() {
        return this.props.list._parent;
    }

    // Имя поля-списка в расчёте: после сохранения список приходит новым
    // объектом, отмеченные берём заново по имени.
    get listName() {
        const raw = toRaw(this.props.list);
        const entry = Object.entries(this.record.data).find(([, v]) => toRaw(v) === raw);
        return entry?.[0];
    }

    get picked() {
        return this.props.list.records.filter((r) => r.data[this.props.name]);
    }

    get targets() {
        return TARGETS.filter((t) => t.key !== this.props.source);
    }

    clear() {
        return pickAll(this.props.list.records, this.props.name, false);
    }

    async run(action, target = false) {
        const record = this.record;
        const listName = this.listName;
        // Отмеченные — до сохранения: у вкладок калькуляторов список вычисляемый,
        // и после сохранения галочки сбрасываются.
        let ids = this.picked.map((r) => r.resId).filter(Boolean);
        if (!(await record.save())) {
            return;
        }
        if (this.props.source === "metal" && listName) {
            ids = record.data[listName].records.filter((r) => r.data[this.props.name]).map((r) => r.resId).filter(Boolean);
        }
        if (!ids.length) {
            this.notification.add(_t("Отметьте строки галочкой."), { type: "warning" });
            return;
        }
        await this.orm.call("pmk.metal.spec", "pmk_bulk", [[record.resId], this.props.source, action, target, ids]);
        await record.load();
    }

    confirmDelete() {
        const n = this.picked.length;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Удалить отмеченные"),
            body: _t("Удалить отмеченные строки: %s?", n),
            confirmLabel: _t("Удалить"),
            confirm: () => this.run("delete"),
            cancel: () => {},
        });
    }
}
