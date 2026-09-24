/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const COLOR_HEX = {
    grey: "#9aa7b8", blue: "#3B6EA5", green: "#2e9e5b", red: "#c0392b",
};

export class TransactionFlowMap extends Component {
    static template = "codeerts_transaction_flow_visualizer.FlowMap";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            nodes: [], edges: [], width: 0, height: 0,
            truncated: false, loading: true,
        });
        const ctx = (this.props.action && this.props.action.context) || {};
        this.model = ctx.flow_model;
        this.resId = ctx.flow_res_id;

        onWillStart(async () => {
            const graph = await this.orm.call(
                "transaction.flow.builder", "get_flow_graph",
                [this.model, this.resId],
            );
            this._layout(graph);
        });
    }

    _layout(graph) {
        const adj = {};
        graph.edges.forEach((e) => {
            (adj[e.from] = adj[e.from] || []).push(e.to);
            (adj[e.to] = adj[e.to] || []).push(e.from);
        });
        const anchorId = `${this.model},${this.resId}`;
        const depth = {};
        depth[anchorId] = 0;
        const queue = [anchorId];
        while (queue.length) {
            const cur = queue.shift();
            (adj[cur] || []).forEach((n) => {
                if (depth[n] === undefined) {
                    depth[n] = depth[cur] + 1;
                    queue.push(n);
                }
            });
        }
        const COL_W = 220, ROW_H = 90;
        const colCount = {};
        const positioned = graph.nodes.map((n) => {
            const d = depth[n.id] ?? 0;
            const row = (colCount[d] = colCount[d] || 0);
            colCount[d] += 1;
            return {
                ...n,
                x: 40 + d * COL_W,
                y: 40 + row * ROW_H,
                hex: COLOR_HEX[n.color] || COLOR_HEX.grey,
            };
        });
        const byId = Object.fromEntries(positioned.map((n) => [n.id, n]));
        const lines = graph.edges
            .filter((e) => byId[e.from] && byId[e.to])
            .map((e) => ({
                x1: byId[e.from].x + 160, y1: byId[e.from].y + 22,
                x2: byId[e.to].x, y2: byId[e.to].y + 22,
            }));
        // size the canvas to the actual content so it scrolls when larger than the screen
        this.state.width = Math.max(0, ...positioned.map((n) => n.x + 160)) + 60;
        this.state.height = Math.max(0, ...positioned.map((n) => n.y + 44)) + 60;
        this.state.nodes = positioned;
        this.state.edges = lines;
        this.state.truncated = graph.truncated;
        this.state.loading = false;
    }

    openRecord(node) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: node.model,
            res_id: node.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("ma_transaction_flow_map", TransactionFlowMap);
