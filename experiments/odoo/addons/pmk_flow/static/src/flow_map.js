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

const COLORS = new Set(["grey", "blue", "green", "red"]);

/**
 * Схема строками по этапам жизни заказа (разбор схемы 12.10.2026): раскладку
 * считает сервер (pmk_flow/models/flow_lanes.py, get_flow_lanes) — этапы,
 * колонки «Заявки», деревья «Расчёта». Здесь только классы узла и соседи для
 * подсветки: линий между этапами нет, связи видны при наведении.
 *
 * Прежняя раскладка (SVG, колонка на этап, линии) уходила вправо на 2900 px:
 * «документы не структурированы, всё превратилось в кашу».
 */
export function prepareLanes(data) {
    const nodes = (data && data.nodes) || {};
    const near = {};
    for (const id of Object.keys(nodes)) {
        near[id] = new Set();
    }
    for (const e of (data && data.edges) || []) {
        if (near[e.from] && near[e.to]) {
            near[e.from].add(e.to);
            near[e.to].add(e.from);
        }
    }
    for (const n of Object.values(nodes)) {
        const color = COLORS.has(n.color) ? n.color : "grey";
        // Открытый документ не кликается: переход на самого себя только
        // добавил бы лишнюю крошку в навигацию.
        n.clickable = !n.anchor && Boolean(n.open_action || (n.open_model && n.open_res_id));
        const cls = ["o_pmk_flow_node", `o_pmk_flow_node--${color}`];
        if (n.anchor) {
            cls.push("o_pmk_flow_node--anchor");
        }
        if (n.clickable) {
            cls.push("o_pmk_flow_node--link");
        }
        if (n.draft) {
            cls.push("o_pmk_flow_node--draft");
        }
        if (n.open_tab) {
            cls.push("o_pmk_flow_node--tab");
        }
        n.cls = cls.join(" ");
    }
    return { nodes, near, lanes: (data && data.lanes) || [] };
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
        this.state = useState({
            loading: false,
            loaded: false,
            error: "",
            lanes: [],
            nodes: {},
            count: 0,
            truncated: false,
            restricted: false,
            hoverId: null,
        });
        this.near = {};
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

    async load() {
        const seq = ++this.requestSeq;
        this.state.loading = true;
        this.state.error = "";
        try {
            const data = await this.orm.call("pmk.flow.builder", "get_flow_lanes", [
                this.props.resModel,
                this.props.resId,
            ]);
            if (seq !== this.requestSeq) {
                return;
            }
            const prepared = prepareLanes(data);
            this.near = prepared.near;
            Object.assign(this.state, {
                lanes: prepared.lanes,
                nodes: prepared.nodes,
                count: data.count || 0,
                truncated: Boolean(data.truncated),
                restricted: Boolean(data.restricted),
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

    node(id) {
        return this.state.nodes[id];
    }

    // Наведение подсвечивает документ и его связи на всех этапах: линий между
    // этапами нет, иначе снова каша.
    setHover(id) {
        this.state.hoverId = id;
    }

    nodeClass(id) {
        const n = this.state.nodes[id];
        const hover = this.state.hoverId;
        if (!hover) {
            return n.cls;
        }
        if (id === hover || (this.near[hover] && this.near[hover].has(id))) {
            return n.cls + " o_pmk_flow_node--lit";
        }
        return n.cls + " o_pmk_flow_node--dim";
    }

    async openNode(node) {
        if (!node.clickable) {
            return;
        }
        // Окно почты на этом письме (pmk_flow/models/flow_builder.py,
        // _letter_action; разбор UX, шаг 53).
        if (node.open_action) {
            return this.action.doAction(node.open_action);
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: node.open_model,
            res_id: node.open_res_id,
            views: [[false, "form"]],
            target: "current",
        });
        // Блок-вкладка (раскрой листа, раскрой зонтов, раскладка): документ
        // открыт — переключаем его на нужную вкладку.
        if (node.open_tab) {
            for (let i = 0; i < 30; i++) {
                const tab = document.querySelector(
                    `.o_form_view .o_notebook_headers a[name="${node.open_tab}"]`
                );
                if (tab) {
                    tab.click();
                    break;
                }
                await new Promise((resolve) => setTimeout(resolve, 100));
            }
        }
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
