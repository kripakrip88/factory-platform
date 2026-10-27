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
        this.state = useState({
            open: false, busy: false, items: [], status: null, text: "", context: null, top: 46,
            threadId: false, threadName: "", threads: [], showList: false,
        });
        this.input = useRef("input");
        this.list = useRef("list");
        this.loaded = false;
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
        if (!this.state.open) return;
        // Панель — под всей шапкой (у нас она в две строки: разделы и пункты раздела).
        const nav = document.querySelector(".o_navbar");
        this.state.top = nav ? Math.round(nav.getBoundingClientRect().bottom) : 46;
        this.state.context = this.currentContext();
        if (!this.loaded) {
            // Первое открытие во вкладке — последний диалог с сервера (после F5 и в новой вкладке).
            this.loaded = true;
            this.state.threads = await this.orm.call("pmk.ai.chat", "threads", []);
            if (this.state.threads.length) {
                await this.openThread(this.state.threads[0].id);
            }
        }
        if (!this.state.status) {
            this.state.status = await this.orm.call("pmk.ai.chat", "get_status", []);
        }
        setTimeout(() => this.input.el && this.input.el.focus(), 50);
    }

    scrollDown() {
        setTimeout(() => { if (this.list.el) this.list.el.scrollTop = this.list.el.scrollHeight; }, 30);
    }

    toItems(raw) {
        return raw.map((i) => (i.role === "assistant" && !i.error && !i.pending
            ? { ...i, html: renderAnswer(i.text) } : i));
    }

    async openThread(threadId) {
        const res = await this.orm.call("pmk.ai.chat", "thread_messages", [threadId]);
        if (res.error) return;
        this.state.threadId = res.id;
        this.state.threadName = res.name;
        this.state.status = res.status;
        this.state.items = this.toItems(res.items);
        this.state.showList = false;
        this.scrollDown();
        const pending = this.state.items.find((i) => i.pending);
        if (pending) {
            this.wait(pending.pending, res.id);
        }
    }

    async toggleList() {
        this.state.showList = !this.state.showList;
        if (this.state.showList) {
            this.state.threads = await this.orm.call("pmk.ai.chat", "threads", []);
        }
    }

    newThread() {
        this.state.threadId = false;
        this.state.threadName = "";
        this.state.items = [];
        this.state.showList = false;
        setTimeout(() => this.input.el && this.input.el.focus(), 50);
    }

    async archiveThread(thread) {
        await this.orm.call("pmk.ai.chat", "archive_thread", [thread.id]);
        this.state.threads = this.state.threads.filter((t) => t.id !== thread.id);
        if (this.state.threadId === thread.id) this.newThread();
    }

    /** Ждать ответ вопроса из очереди; ответ кладётся в свой диалог, даже если открыт другой. */
    async wait(requestId, threadId) {
        this.state.busy = this.state.threadId === threadId;
        let res;
        const until = Date.now() + 4 * 60 * 1000;
        do {
            await new Promise((r) => setTimeout(r, 1500));
            res = await this.orm.call("pmk.ai.chat", "poll", [requestId]);
            // «Связь с ИИ плохая — пробую ещё…» вместо «Думаю…», пока фон повторяет (27.10.2026).
            const pending = this.state.items.find((i) => i.pending === requestId);
            if (pending && (pending.note || "") !== (res.note || "")) pending.note = res.note || "";
        } while ((res.state === "queued" || res.state === "running") && Date.now() < until);
        if (res.state === "queued" || res.state === "running") {
            res = { error: "Ответ задерживается — загляните позже: он сохранится в диалоге." };
        }
        this.state.status = res.status || this.state.status;
        if (this.state.threadId !== threadId) return;   // открыт другой диалог — ответ подгрузится при возврате
        const idx = this.state.items.findIndex((i) => i.pending === requestId);
        const item = res.error
            ? { role: "assistant", text: res.error, error: true }
            : { role: "assistant", text: res.answer, html: renderAnswer(res.answer), seconds: res.seconds,
                usage: res.usage_id, rated: false };
        if (idx >= 0) this.state.items.splice(idx, 1, item); else this.state.items.push(item);
        this.state.busy = false;
        this.scrollDown();
    }

    async send(text) {
        const question = (text || this.state.text || "").trim();
        if (!question || this.state.busy) return;
        this.state.text = "";
        if (this.input.el) this.input.el.value = "";   // t-model не сбрасывает поле, если вид не менялся
        this.state.context = this.currentContext();
        this.state.items.push({ role: "user", text: question });
        this.scrollDown();
        try {
            // Вопрос — в очередь диалога, ответ готовит фоновый процесс (правило «не тормозить
            // систему»): страница не держит процесс Odoo, а раз в 1,5 с спрашивает, готово ли.
            const queued = await this.orm.call("pmk.ai.chat", "ask", [question, this.state.threadId, this.state.context]);
            this.state.status = queued.status || this.state.status;
            if (queued.error) {
                this.state.items.push({ role: "assistant", text: queued.error, error: true });
                this.scrollDown();
                return;
            }
            this.state.threadId = queued.thread_id;
            this.state.threadName = queued.thread_name;
            this.state.items.push({ role: "assistant", pending: queued.request_id });
            await this.wait(queued.request_id, queued.thread_id);
        } catch (e) {
            this.state.items.push({ role: "assistant", text: "Ошибка сервера — повторите.", error: true });
            this.state.busy = false;
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

    /** 👍/👎 под ответом; к 👎 — что не так (уходит на разбор, правила — в knowledge/90_remarks.md). */
    async rate(item, rating) {
        if (!item.usage || item.rated) return;
        let note = "";
        if (rating === "bad") {
            note = window.prompt("Что не так в ответе? Это попадёт в разбор и обучение ассистента.", "") || "";
        }
        await this.orm.call("pmk.ai.chat", "rate", [item.usage, rating, note]);
        item.rated = rating;
    }

    get contextLabel() {
        const c = this.state.context;
        return c && c.title ? "видит: " + c.title : "";
    }

    get usageText() {
        const s = this.state.status;
        if (!s) return "";
        return `За ${s.month}: ${s.questions} вопр. (ваших ${s.mine}) · ${s.spent.toFixed(2)} $ из ${Math.round(s.budget)} $`;
    }
}

registry.category("systray").add("pmk_ai.panel", { Component: PmkAiPanel }, { sequence: 30 });
