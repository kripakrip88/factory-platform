/**
 * Заказ вентзонтов: строка зонта разворачивается в состав прямо в таблице —
 * как изделие в «Расчёте металлопроката» (Антон 11.10.2026: «у них должна
 * быть возможность развернуть состав как в калькуляторе Расчёт
 * металлопроката»; зонты — будущая номенклатура). Разметка и стили — те же
 * pmk-prow, что у состава расчёта (dobor_builder.scss), чтобы два состава
 * читались одинаково. Виджет расчёта (product_lines_field.js) не подходит:
 * он завязан на разделы и поля деталей расчёта.
 *
 * Состав берётся из ответа генератора, который уже лежит в строке (spec_json —
 * пересчитывается onchange при вводе размера, цвета, металла), — без запроса
 * к серверу. Чертёж — крупно в окне поверх заказа (миниатюра не нужна:
 * «она не будет информативной»), картинка — /web/image поля drawing_png.
 * Для DXF и чертежа строка должна быть в базе: несохранённый заказ
 * сохраняется перед этим, как штатная кнопка в строке.
 */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { ListRenderer } from "@web/views/list/list_renderer";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

const NUM = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const AREA = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 });

function plural(n, one, few, many) {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) {
        return one;
    }
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) {
        return few;
    }
    return many;
}

export class VentHoodDrawingDialog extends Component {
    static template = "pmk_calc.VentHoodDrawingDialog";
    static components = { Dialog };
    static props = ["title", "src", "onDownload", "close"];

    setup() {
        // Крупно — по ширине окна; щелчок — в натуральную величину (2600 px)
        // с прокруткой, щелчок ещё раз — обратно.
        this.state = useState({ natural: false });
    }
}

export class VentHoodLinesRenderer extends ListRenderer {
    static rowsTemplate = "pmk_calc.VentHoodRows";
    // Стрелка состава — в самой строке зонта, в ячейке «Зонт» (Антон 11.10:
    // строка «Состав: N деталей на зонт» под каждым зонтом «занимает
    // слишком много места»). Строка состава появляется, только когда
    // раскрыта (или когда размер не подходит — с причиной).
    static recordRowTemplate = "pmk_calc.VentHoodRecordRow";

    setup() {
        super.setup();
        this.vh = useState({ open: {} });
        // Раскрытые сами, потому что зонт в заказе один (как у расчёта, шаг
        // 32). Обычный Set: пишется во время отрисовки.
        this.vhAutoOpen = new Set();
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
    }

    /**
     * Чередование зонтов (Антон 11.10: «на каждую позицию так же сделать
     * выделение разных строк, как в составе»): каждый второй зонт — вместе
     * со строкой своего состава — чуть темнее. Классом, а не nth-child:
     * строки состава вклиниваются между строками зонтов.
     */
    getRowClass(record) {
        return `${super.getRowClass(record)} ${this.vhAlt(record) ? "pmk-row-alt" : ""}`;
    }

    vhAlt(record) {
        return this.props.list.records.indexOf(record) % 2 === 1;
    }

    get vhColspan() {
        return this.nbCols;
    }

    vhSpec(record) {
        const raw = record.data.spec_json;
        if (!raw) {
            return null;
        }
        try {
            return JSON.parse(raw);
        } catch {
            return null;
        }
    }

    vhParts(record) {
        const spec = this.vhSpec(record);
        const qty = record.data.qty || 0;
        return (spec ? spec.parts : []).map((p, i) => ({
            key: i,
            name: p.name,
            size: `${NUM.format(p.size_mm[0])} × ${NUM.format(p.size_mm[1])}`,
            one: p.qty,
            all: p.qty * qty,
            area: AREA.format(p.area_m2_each),
        }));
    }

    vhLabel(record) {
        const spec = this.vhSpec(record);
        if (!spec) {
            return "";
        }
        const n = spec.parts.reduce((s, p) => s + p.qty, 0);
        return `${n} ${plural(n, "деталь", "детали", "деталей")} на зонт`;
    }

    vhWarnings(record) {
        return (record.data.warnings_text || "").split("\n").filter(Boolean);
    }

    isOpen(record) {
        if (record.id in this.vh.open) {
            return !!this.vh.open[record.id];
        }
        if (this.props.list.records.length === 1) {
            this.vhAutoOpen.add(record.id);
            return true;
        }
        return this.vhAutoOpen.has(record.id);
    }

    toggle(record) {
        this.vh.open[record.id] = !this.isOpen(record);
    }

    async vhSaved(record) {
        if (record.isNew || record.dirty || this.props.list.model.root.dirty) {
            const ok = await this.props.list.model.root.save();
            if (ok === false) {
                return null;
            }
        }
        return record.resId;
    }

    async vhDxf(record) {
        const id = await this.vhSaved(record);
        if (id) {
            const act = await this.orm.call("pmk.vent.hood", "action_download_dxf", [[id]]);
            await this.action.doAction(act);
        }
    }

    async vhDrawing(record) {
        const id = await this.vhSaved(record);
        if (!id) {
            return;
        }
        const spec = this.vhSpec(record);
        this.dialog.add(VentHoodDrawingDialog, {
            title: `Чертёж заготовок — ${spec ? spec.hood : ""}`,
            src: `/web/image/pmk.vent.hood/${id}/drawing_png?unique=${Date.now()}`,
            onDownload: async () => {
                const act = await this.orm.call("pmk.vent.hood", "action_download_png", [[id]]);
                await this.action.doAction(act);
            },
        });
    }
}

export class VentHoodLinesField extends X2ManyField {
    static components = { ...X2ManyField.components, ListRenderer: VentHoodLinesRenderer };
}

registry.category("fields").add("pmk_vent_hood_lines", {
    ...x2ManyField,
    component: VentHoodLinesField,
});
