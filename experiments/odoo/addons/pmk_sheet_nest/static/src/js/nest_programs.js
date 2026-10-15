/** @odoo-module **/
/**
 * Раскрой-документ: блок на каждую программу (толщина и вид листа) — как цвета у раскроя
 * зонтов (Антон 15.10.2026). В блоке: лист, станок, детали, состояние, сводка 4 порядков
 * резки (щелчок по столбцу — выбор), кнопки «Рассчитать / Собрать / Принять / Открыть».
 *
 * Действия — прямыми вызовами программы (pmk.laser.job) через env.services.orm, затем
 * документ перечитывается. Пока хоть одна программа считается, перечитываем раз в 5 с.
 */
import { Component, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { STRATEGIES, summaryView } from "@pmk_sheet_nest/js/strategy_pick";

export class NestProgramsField extends Component {
    static template = "pmk_sheet_nest.NestPrograms";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ busyIds: {}, error: "" });
        this.timer = setInterval(() => this.poll(), 5000);
        onWillUnmount(() => clearInterval(this.timer));
    }

    get programs() {
        return this.props.record.data[this.props.name].records.map((rec) => {
            const d = rec.data;
            return {
                id: rec.resId, rec, d,
                title: d.name, sheet: d.sheet_id && d.sheet_id.display_name,
                machine: d.machine_id && d.machine_id.display_name,
                view: summaryView(d.nest_summary_json, d.nest_strategy),
            };
        });
    }

    async poll() {
        if (this.programs.some((p) => p.d.nest_busy) && !this.props.record.dirty) {
            await this.props.record.load();
        }
    }

    async run(prog, method) {
        this.state.error = "";
        this.state.busyIds[prog.id] = true;
        try {
            if (this.props.record.dirty) {
                await this.props.record.save();
            }
            const action = await this.env.services.orm.call("pmk.laser.job", method, [[prog.id]]);
            if (action && action.type === "ir.actions.act_window") {
                await this.env.services.action.doAction(action);
                return;
            }
            await this.props.record.load();
        } catch (e) {
            this.state.error = (e && e.data && e.data.message) || String(e);
        } finally {
            delete this.state.busyIds[prog.id];
        }
    }

    async pick(prog, col) {
        const c = prog.view.cols.find((x) => x.key === col.key);
        if (!c || c.error || prog.d.nest_busy || prog.d.sheet_count) {
            return;
        }
        await this.env.services.orm.write("pmk.laser.job", [prog.id], { nest_strategy: col.key });
        await this.props.record.load();
    }

    open(prog) {
        this.env.services.action.doAction({
            type: "ir.actions.act_window", res_model: "pmk.laser.job", res_id: prog.id,
            views: [[false, "form"]], target: "current",
        });
    }
}

registry.category("fields").add("pmk_sheet_nest_programs", {
    component: NestProgramsField,
    supportedTypes: ["one2many"],
    relatedFields: [
        { name: "name", type: "char" },
        { name: "thickness_mm", type: "float" },
        { name: "sheet_id", type: "many2one", relation: "pmk.metal.sheet" },
        { name: "machine_id", type: "many2one", relation: "pmk.laser.machine" },
        { name: "parts_text", type: "char" },
        { name: "task_text", type: "char" },
        { name: "nest_status", type: "char" },
        { name: "nest_status_kind", type: "selection",
          selection: [["none", ""], ["busy", ""], ["done", ""], ["stale", ""], ["error", ""]] },
        { name: "nest_summary_json", type: "text" },
        { name: "nest_strategy", type: "selection", selection: STRATEGIES },
        { name: "nest_can_build", type: "boolean" },
        { name: "nest_can_accept", type: "boolean" },
        { name: "nest_program", type: "char" },
        { name: "nest_busy", type: "boolean" },
        { name: "nest_warnings", type: "text" },
        { name: "sheet_count", type: "integer" },
        { name: "nest_state_text", type: "char" },
    ],
});
