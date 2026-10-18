/** @odoo-module **/
/**
 * Панель ассистента (18.10.2026): кнопка ✦ в верхней панели, чат справа.
 *
 * Прототип принят Антоном 18.10 («кайф. пусть сотрудники видят лимиты и расходы»). Сервер —
 * pmk.ai.chat.ask(вопрос, история, открытый документ), только чтение. Разговор живёт, пока
 * открыта вкладка: панель — пункт systray, при переходах между разделами не пересоздаётся.
 * Ссылки в ответе вида [СД-0112](rec:crm.lead:12) открывают документ. Сервисы — env.services
 * (грабля шага 31: useService вешал вид).
 */
import { Component, markup, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\(rec:([a-z0-9_.]+):(\d+)\)/g,
        '<a href="#" class="o_pmk_ai__rec" data-model="$2" data-id="$3">$1</a>');

/** Узкий Markdown (таблицы «| … |» — 18.10, ассистент отвечает ими по ценам): **жирный**, _курсив_, списки «- », ссылки rec:модель:id. Всё прочее — текст. */
export function renderAnswer(text) {
    const lines = esc(text || "").split("\n");
    const html = [];
    let list = false;
    let table = false;
    for (const raw of lines) {
        const cells = raw.trim().match(/^\|(.+)\|$/);
        if (cells) {
            const parts = cells[1].split("|").map((c) => c.trim());
            if (parts.every((c) => /^:?-{2,}:?$/.test(c))) continue;   // строка-разделитель
            const row = parts.map((c) => inline(c));
            if (!table) { html.push('<table class="o_pmk_ai__tbl"><tr>' + row.map((c) => "<th>" + c + "</th>").join("") + "</tr>"); table = true; }
            else html.push("<tr>" + row.map((c) => "<td>" + c + "</td>").join("") + "</tr>");
            continue;
        }
        if (table) { html.push("</table>"); table = false; }
        let line = inline(raw);
        const item = line.match(/^\s*[-•*]\s+(.*)$/);
        if (item) {
            if (!list) { html.push("<ul>"); list = true; }
            html.push("<li>" + item[1] + "</li>");
            continue;
        }
        if (list) { html.push("</ul>"); list = false; }
        html.push(line.trim() ? "<p>" + line + "</p>" : "");
    }
    if (list) html.push("</ul>");
    if (table) html.push("</table>");
    return markup(html.join(""));
}

export class PmkAiPanel extends Component {
    static template = "pmk_ai.Panel";
    static props = {};

    setup() {
        this.orm = this.env.services.orm;
        this.action = this.env.services.action;
        this.state = useState({ open: false, busy: false, items: [], status: null, text: "", context: null, top: 46 });
        this.input = useRef("input");
        this.list = useRef("list");
    }

    currentContext() {
        const ctrl = this.action.currentController;
        const props = (ctrl && ctrl.props) || {};
        const title = (ctrl && (ctrl.displayName || (ctrl.action && ctrl.action.name))) || "";
        let id = props.resId;
        if (!id && props.resModel) {
            const m = window.location.pathname.match(/\/(\d+)(?:\/)?$/);
            id = m ? Number(m[1]) : false;
        }
        // Открыта запись — её название из заголовка вкладки («(53) СМ-00035» → «СМ-00035»).
        const docTitle = (document.title || "").replace(/^\(\d+\)\s*/, "").trim();
        return { model: props.resModel || false, id: id || false,
                 title: id && docTitle && docTitle !== "Odoo" ? docTitle : title };
    }

    async toggle() {
        this.state.open = !this.state.open;
        if (this.state.open) {
            // Панель — под всей шапкой (у нас она в две строки: разделы и пункты раздела).
            const nav = document.querySelector(".o_navbar");
            this.state.top = nav ? Math.round(nav.getBoundingClientRect().bottom) : 46;
            this.state.context = this.currentContext();
            this.state.status = await this.orm.call("pmk.ai.chat", "get_status", []);
            setTimeout(() => this.input.el && this.input.el.focus(), 50);
        }
    }

    scrollDown() {
        setTimeout(() => { if (this.list.el) this.list.el.scrollTop = this.list.el.scrollHeight; }, 30);
    }

    async send(text) {
        const question = (text || this.state.text || "").trim();
        if (!question || this.state.busy) return;
        this.state.text = "";
        if (this.input.el) this.input.el.value = "";   // t-model не сбрасывает поле, если вид не менялся
        const history = this.state.items.filter((i) => !i.error).map((i) => ({ role: i.role, text: i.text }));
        this.state.items.push({ role: "user", text: question });
        this.state.busy = true;
        this.state.context = this.currentContext();
        this.scrollDown();
        try {
            const res = await this.orm.call("pmk.ai.chat", "ask", [question, history, this.state.context]);
            this.state.status = res.status || this.state.status;
            if (res.error) {
                this.state.items.push({ role: "assistant", text: res.error, error: true });
            } else {
                this.state.items.push({ role: "assistant", text: res.answer, html: renderAnswer(res.answer), seconds: res.seconds });
            }
        } catch (e) {
            this.state.items.push({ role: "assistant", text: "Ошибка сервера — повторите.", error: true });
        } finally {
            this.state.busy = false;
            this.scrollDown();
        }
    }

    onKey(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    onClickAnswer(ev) {
        const a = ev.target.closest(".o_pmk_ai__rec");
        if (!a) return;
        ev.preventDefault();
        this.action.doAction({ type: "ir.actions.act_window", res_model: a.dataset.model,
                               res_id: Number(a.dataset.id), views: [[false, "form"]], target: "current" });
    }

    clear() {
        this.state.items = [];
    }

    get contextLabel() {
        const c = this.state.context;
        if (!c) return "";
        return c.title ? "видит: " + c.title : "";
    }

    get usageText() {
        const s = this.state.status;
        if (!s) return "";
        return `За ${s.month}: ${s.questions} вопр. (ваших ${s.mine}) · ${s.spent.toFixed(2)} $ из ${Math.round(s.budget)} $`;
    }
}

registry.category("systray").add("pmk_ai.panel", { Component: PmkAiPanel }, { sequence: 30 });
