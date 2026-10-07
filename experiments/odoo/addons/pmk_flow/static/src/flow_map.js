/** @odoo-module **/
/**
 * Схема связей документов — вкладкой «Связи» в форме и отдельной страницей.
 *
 * ДВА ВХОДА, ОДНА СХЕМА. Штатные документы (заказ, закупка, производство,
 * счёт, отгрузка) открывают схему кнопкой — это клиентское действие, как было
 * у автора модуля. Расчёт и сделка показывают её вкладкой: клиентское действие
 * во вкладку формы не вставить, поэтому там виджет вида (<widget
 * name="pmk_flow_map"/>). Оба входа рисуют один и тот же PmkFlowMap.
 *
 * ⚠️ КЛЮЧИ СВОИ, НЕ АВТОРСКИЕ. Пока на стенде стоит исходный модуль
 * (codeerts_transaction_flow_visualizer), он держит ключ действия
 * "ma_transaction_flow_map", шаблон со своим именем и классы o_flow_*.
 * Совпади у нас хоть одно — реестр откажет на повторной регистрации, и веб-
 * клиент не загрузится целиком. Поэтому всё с префиксом pmk.
 */

import { Component, useEffect, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

// Геометрия схемы, px. Шаблон берёт размеры узла отсюда же (this.geo), чтобы
// прямоугольник и расчёт концов линий не разошлись после правки одного из них.
const GEO = {
    nodeW: 200,
    nodeH: 50,
    colGap: 64,
    rowGap: 14,
    pad: 16,
    headH: 26,
    // Вылет дуги для связи внутри одной колонки (проект ↔ задача).
    arc: 28,
};

// Сколько знаков влезает в строку узла при ширине 200 px. Полный текст —
// в подсказке при наведении.
const LABEL_MAX = 25;
const STATE_MAX = 30;
// Подпись колонки может занять и промежуток до следующей колонки, но не больше:
// «Раскрой · Лазер · Производство» иначе наезжает на соседнюю подпись.
const HEAD_MAX = 34;

const COLORS = new Set(["grey", "blue", "green", "red"]);

function clip(text, max) {
    const s = String(text || "");
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

/**
 * Раскладка по этапам: колонка — место документа в цепочке завода.
 *
 * ⚠️ У АВТОРА КОЛОНКА РАВНЯЛАСЬ ШАГУ ОБХОДА от открытого документа. Сделка
 * (шаг назад) и раскрой (шаг вперёд) вставали в одну колонку, и вместо
 * цепочки «письмо → сделка → расчёт → раскрой» выходила звезда вокруг
 * документа. Теперь колонку задаёт stage узла (словарь _STAGES на сервере),
 * а пустые этапы между занятыми сжимаются, но порядок остаётся.
 *
 * Порядок внутри колонки — по среднему положению соседей (барицентр): один
 * проход слева направо, один обратно. Для схем в десятки узлов этого хватает,
 * чтобы линии почти не перекрещивались.
 */
export function layoutFlow(graph, anchorId) {
    const nodes = (graph && graph.nodes) || [];
    if (!nodes.length) {
        return { nodes: [], edges: [], heads: [], width: 0, height: 0 };
    }
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const adj = new Map(nodes.map((n) => [n.id, new Set()]));
    const edges = ((graph && graph.edges) || []).filter(
        (e) => e.from !== e.to && byId.has(e.from) && byId.has(e.to)
    );
    for (const e of edges) {
        adj.get(e.from).add(e.to);
        adj.get(e.to).add(e.from);
    }

    const ranks = [...new Set(nodes.map((n) => n.stage))].sort((a, b) => a - b);
    const colOfRank = new Map(ranks.map((rank, i) => [rank, i]));
    const colOf = (id) => colOfRank.get(byId.get(id).stage);
    const columns = ranks.map(() => []);
    for (const n of nodes) {
        columns[colOfRank.get(n.stage)].push(n);
    }

    const span = (k) => k * GEO.nodeH + Math.max(0, k - 1) * GEO.rowGap;
    const bodyTop = GEO.pad + GEO.headH;
    const bodyH = span(Math.max(...columns.map((c) => c.length)));
    const y = new Map();

    // side < 0 — упорядочить по соседям слева, side > 0 — по соседям справа.
    // Узел без таких соседей остаётся на своём месте (или уходит вниз, если
    // места у него ещё нет).
    const placeColumn = (ci, side) => {
        const keyOf = (n) => {
            let sum = 0;
            let count = 0;
            for (const id of adj.get(n.id)) {
                const c = colOf(id);
                if (y.has(id) && (side < 0 ? c < ci : c > ci)) {
                    sum += y.get(id);
                    count += 1;
                }
            }
            if (count) {
                return sum / count;
            }
            return y.has(n.id) ? y.get(n.id) : Infinity;
        };
        const ordered = columns[ci]
            .map((n) => ({ n, k: keyOf(n) }))
            // Infinity - Infinity = NaN, а NaN ложно — тогда решают модель и
            // номер записи, и порядок остаётся одинаковым от открытия к открытию.
            .sort(
                (a, b) =>
                    a.k - b.k ||
                    a.n.model.localeCompare(b.n.model) ||
                    a.n.res_id - b.n.res_id
            )
            .map((o) => o.n);
        columns[ci] = ordered;
        const top = bodyTop + (bodyH - span(ordered.length)) / 2;
        ordered.forEach((n, row) => y.set(n.id, top + row * (GEO.nodeH + GEO.rowGap)));
    };
    for (let ci = 0; ci < columns.length; ci++) {
        placeColumn(ci, -1);
    }
    for (let ci = columns.length - 2; ci >= 0; ci--) {
        placeColumn(ci, +1);
    }

    const colX = (ci) => GEO.pad + ci * (GEO.nodeW + GEO.colGap);
    const placed = nodes.map((n) => {
        const color = COLORS.has(n.color) ? n.color : "grey";
        const anchor = n.id === anchorId;
        // Открытый документ не кликается: переход на самого себя только
        // добавил бы лишнюю крошку в навигацию.
        // Письмо (шаг 53) открывается действием — окном почты, а не формой.
        const clickable = !anchor && Boolean(n.open_action || (n.open_model && n.open_res_id));
        const cls = ["o_pmk_flow_node", `o_pmk_flow_node--${color}`];
        if (anchor) {
            cls.push("o_pmk_flow_node--anchor");
        }
        if (clickable) {
            cls.push("o_pmk_flow_node--link");
        }
        return {
            ...n,
            x: colX(colOf(n.id)),
            y: y.get(n.id),
            anchor,
            clickable,
            cls: cls.join(" "),
            shortLabel: clip(n.label, LABEL_MAX),
            shortState: clip(n.state, STATE_MAX),
        };
    });
    const pos = new Map(placed.map((n) => [n.id, n]));

    // Концы линии — по взаимному положению: из правого края левого узла в
    // левый край правого. У автора линия всегда шла из правого края «откуда»
    // в левый край «куда», и связь с документом левее перечёркивала узлы.
    const lines = edges.map((e) => {
        const a = pos.get(e.from);
        const b = pos.get(e.to);
        const midA = a.y + GEO.nodeH / 2;
        const midB = b.y + GEO.nodeH / 2;
        let d;
        if (a.x === b.x) {
            const xr = a.x + GEO.nodeW;
            d = `M${xr},${midA} C${xr + GEO.arc},${midA} ${xr + GEO.arc},${midB} ${xr},${midB}`;
        } else {
            const [l, r] = a.x < b.x ? [a, b] : [b, a];
            const x1 = l.x + GEO.nodeW;
            const y1 = l.y + GEO.nodeH / 2;
            const x2 = r.x;
            const y2 = r.y + GEO.nodeH / 2;
            const dx = Math.max(GEO.colGap / 2, (x2 - x1) / 3);
            d = `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
        }
        return { id: `${e.from}|${e.to}`, from: e.from, to: e.to, d };
    });

    // Подпись колонки — этапы, которые в ней есть: «Раскрой · Лазер».
    // Порядок по модели, а не по строкам: иначе подпись менялась бы от того,
    // какой документ оказался сверху.
    const heads = columns.map((col, ci) => {
        const kinds = [...col]
            .sort((a, b) => a.model.localeCompare(b.model))
            .map((n) => n.kind);
        const label = [...new Set(kinds)].join(" · ");
        return { key: ranks[ci], x: colX(ci), label: clip(label, HEAD_MAX), full: label };
    });

    return {
        nodes: placed,
        edges: lines,
        heads,
        width: colX(columns.length - 1) + GEO.nodeW + GEO.arc + GEO.pad,
        height: bodyTop + bodyH + GEO.pad,
    };
}

export class PmkFlowMap extends Component {
    static template = "pmk_flow.FlowMap";
    static props = {
        resModel: { type: String },
        resId: { type: Number },
        // Отдельная страница: без потолка высоты, прокручивается вся страница.
        page: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.geo = GEO;
        this.state = useState({
            loading: false,
            loaded: false,
            error: "",
            nodes: [],
            edges: [],
            heads: [],
            width: 0,
            height: 0,
            truncated: false,
            restricted: false,
            hoverId: null,
        });
        // Номер запроса: ответ на устаревший запрос (листнули к следующей
        // записи, пока строилась схема) не должен затереть свежий.
        this.requestSeq = 0;
        // Грузим по факту монтирования и при смене документа. Вкладка формы
        // монтируется только когда её открыли — значит, запрос уходит по
        // клику на «Связи», а не при каждом открытии расчёта.
        useEffect(
            () => {
                this.load();
            },
            () => [this.props.resModel, this.props.resId]
        );
    }

    get anchorId() {
        return `${this.props.resModel},${this.props.resId}`;
    }

    async load() {
        const seq = ++this.requestSeq;
        this.state.loading = true;
        this.state.error = "";
        try {
            const graph = await this.orm.call("pmk.flow.builder", "get_flow_graph", [
                this.props.resModel,
                this.props.resId,
            ]);
            if (seq !== this.requestSeq) {
                return;
            }
            Object.assign(this.state, layoutFlow(graph, this.anchorId), {
                truncated: Boolean(graph.truncated),
                restricted: Boolean(graph.restricted),
                loaded: true,
                hoverId: null,
            });
        } catch (error) {
            if (seq !== this.requestSeq) {
                return;
            }
            // Ошибку показываем во вкладке, а не окном поверх формы: схема —
            // справочный вид, и её сбой не должен мешать работать с документом.
            this.state.error =
                (error && error.data && error.data.message) ||
                (error && error.message) ||
                String(error);
        } finally {
            if (seq === this.requestSeq) {
                this.state.loading = false;
            }
        }
    }

    // Наведение на узел подсвечивает его связи: на схеме в два десятка
    // документов иначе не проследить, какая линия куда ведёт.
    setHover(id) {
        this.state.hoverId = id;
    }

    edgeClass(edge) {
        const hover = this.state.hoverId;
        return hover && (edge.from === hover || edge.to === hover)
            ? "o_pmk_flow_edge o_pmk_flow_edge--on"
            : "o_pmk_flow_edge";
    }

    openNode(node) {
        if (!node.clickable) {
            return;
        }
        // Окно почты на этом письме (pmk_flow/models/flow_builder.py,
        // _letter_action; разбор UX, шаг 53).
        if (node.open_action) {
            return this.action.doAction(node.open_action);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: node.open_model,
            res_id: node.open_res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onNodeKeydown(ev, node) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.openNode(node);
        }
    }
}

/**
 * Вкладка «Связи» в форме: <widget name="pmk_flow_map"/>.
 *
 * Документ берётся из записи формы. У несохранённой записи id ещё нет —
 * связей у неё тоже нет, поэтому вместо пустой схемы просьба сохранить.
 * props.record.resId читается в шаблоне, поэтому после сохранения вкладка
 * перерисуется сама и схема загрузится без перехода.
 */
export class PmkFlowMapWidget extends Component {
    static template = "pmk_flow.FlowMapWidget";
    static components = { PmkFlowMap };
    static props = { ...standardWidgetProps };
}

/**
 * Отдельная страница схемы — кнопка «Связи» на штатных формах.
 *
 * ⚠️ Документ приходит только в контексте кнопки. После перезагрузки
 * браузера на этой странице контекста уже нет — показываем, откуда открыть
 * схему, а не пустой холст.
 */
export class PmkFlowMapAction extends Component {
    static template = "pmk_flow.FlowMapAction";
    static components = { PmkFlowMap };
    static props = { "*": true };

    setup() {
        const ctx = (this.props.action && this.props.action.context) || {};
        this.resModel = ctx.flow_model || "";
        this.resId = ctx.flow_res_id || 0;
    }
}

registry.category("view_widgets").add("pmk_flow_map", { component: PmkFlowMapWidget });
registry.category("actions").add("pmk_flow_map", PmkFlowMapAction);
