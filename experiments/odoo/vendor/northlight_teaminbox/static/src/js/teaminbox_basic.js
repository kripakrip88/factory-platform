/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

const PAGE_SIZE = 25;
const EMPTY_FILTER = () => ({ dateFrom: "", dateTo: "" });

class TeamInboxBasic extends Component {
    static template = "northlight_teaminbox.TeamInboxBasic";
    static props = ["*"];

    setup() {
        this.state = useState({
            tab: "in",
            search: "",
            sort: "desc",
            dark: false,

            filter: EMPTY_FILTER(),
            filterDraft: EMPTY_FILTER(),
            showFilter: false,

            messages: [],
            hasMore: false,
            loadingList: true,
            loadingMore: false,

            selected: null,
            loadingBody: false,
            attachments: [],
            attOpen: false,

            stats: { total_in: 0, total_out: 0 },

            toast: "",
        });

        this._searchTimer = null;
        this._toastTimer = null;
        this._loadSeq = 0;
        // No theme setting in the free tier — it just follows the OS.
        this._systemDark = window.matchMedia("(prefers-color-scheme: dark)");
        this._onSystemTheme = () => this.applyTheme();
        this._systemDark.addEventListener("change", this._onSystemTheme);

        onWillStart(async () => {
            this.applyTheme();
            this.loadStats();
            await this.loadMessages();
        });
    }

    // ── Theme ─────────────────────────────────────────────────────────────

    applyTheme() {
        this.state.dark = this._systemDark.matches;
    }

    get rootClass() {
        return ["ntib_root", this.state.dark ? "ntib_dark" : ""].filter(Boolean).join(" ");
    }

    // ── Data loading ─────────────────────────────────────────────────────

    async loadStats() {
        try {
            const stats = await rpc("/teaminboxbasic/stats", {});
            if (stats && typeof stats === "object") {
                this.state.stats = {
                    total_in: stats.total_in ?? 0,
                    total_out: stats.total_out ?? 0,
                };
            }
        } catch (e) {
            console.error("[TeamInboxBasic] loadStats failed:", e);
        }
    }

    _requestParams(offset) {
        const f = this.state.filter;
        return {
            direction: this.state.tab,
            limit: PAGE_SIZE,
            offset,
            search: this.state.search || "",
            sort: this.state.sort,
            date_from: f.dateFrom,
            date_to: f.dateTo,
        };
    }

    async loadMessages() {
        const seq = ++this._loadSeq;
        this.state.loadingList = true;
        this.state.selected = null;
        this.state.attachments = [];
        this.state.attOpen = false;
        try {
            const messages = await rpc("/teaminboxbasic/messages", this._requestParams(0));
            if (seq !== this._loadSeq) return;
            const list = Array.isArray(messages) ? messages : [];
            this.state.messages = list;
            this.state.hasMore = list.length === PAGE_SIZE;
        } catch (e) {
            console.error("[TeamInboxBasic] loadMessages failed:", e);
            if (seq === this._loadSeq) this.state.messages = [];
        } finally {
            if (seq === this._loadSeq) this.state.loadingList = false;
        }
    }

    async loadMore() {
        if (this.state.loadingMore || !this.state.hasMore) return;
        this.state.loadingMore = true;
        const seq = this._loadSeq;
        try {
            const messages = await rpc("/teaminboxbasic/messages",
                this._requestParams(this.state.messages.length));
            if (seq !== this._loadSeq) return;
            const list = Array.isArray(messages) ? messages : [];
            this.state.messages = [...this.state.messages, ...list];
            this.state.hasMore = list.length === PAGE_SIZE;
        } catch (e) {
            console.error("[TeamInboxBasic] loadMore failed:", e);
        } finally {
            this.state.loadingMore = false;
        }
    }

    onRowsScroll(ev) {
        const el = ev.target;
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 160) {
            this.loadMore();
        }
    }

    async reloadCurrent() {
        await this.loadMessages();
    }

    async setTab(tab) {
        if (this.state.tab === tab) return;
        this.state.tab = tab;
        await this.reloadCurrent();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this.reloadCurrent(), 400);
    }

    async refresh() {
        await Promise.all([this.loadStats(), this.reloadCurrent()]);
        this.showToast(_t("Refreshed"));
    }

    // ── Filter popup (a glimpse — sort + date range; the rest is Pro) ─────

    get hasActiveFilter() {
        const f = this.state.filter;
        return !!(f.dateFrom || f.dateTo || this.state.sort !== "desc");
    }

    openFilter() {
        this.state.filterDraft = { ...this.state.filter };
        this.state.showFilter = true;
    }

    closeFilter() {
        this.state.showFilter = false;
    }

    setDraft(key, ev) {
        this.state.filterDraft[key] = ev.target.value;
    }

    async setSort(value) {
        if (this.state.sort === value) return;
        this.state.sort = value;
        await this.reloadCurrent();
    }

    async applyFilter() {
        this.state.filter = { ...this.state.filterDraft };
        this.state.showFilter = false;
        await this.reloadCurrent();
    }

    async clearFilter() {
        this.state.filter = EMPTY_FILTER();
        this.state.filterDraft = EMPTY_FILTER();
        this.state.sort = "desc";
        this.state.showFilter = false;
        await this.reloadCurrent();
    }

    // ── Message selection ────────────────────────────────────────────────

    async selectMessage(msg) {
        this.state.selected = msg;
        this.state.attachments = [];
        this.state.attOpen = false;
        if (!msg.body) {
            this.state.loadingBody = true;
            try {
                const result = await rpc("/teaminboxbasic/body", { message_id: msg.id });
                if (this.state.selected && this.state.selected.id === msg.id) {
                    this.state.selected = Object.assign({}, this.state.selected, {
                        body: result?.body || "",
                    });
                    this.state.attachments = result?.attachments || [];
                }
            } catch (e) {
                console.error("[TeamInboxBasic] body fetch failed:", e);
            } finally {
                this.state.loadingBody = false;
            }
        }
    }

    toggleAtt() {
        this.state.attOpen = !this.state.attOpen;
    }

    // ── Record navigation ────────────────────────────────────────────────

    openRecord(ev, model, resId) {
        if (ev) ev.stopPropagation();
        if (!model || !resId) return;
        window.open(`/odoo/${model}/${resId}`, "_blank", "noopener");
    }

    // ── Formatting (relative dates only — the format choice is Pro) ───────

    _dayLabel(d) {
        const now = new Date();
        const sameYear = d.getFullYear() === now.getFullYear();
        const bareDate = () => d.toLocaleDateString(this._locale(),
            sameYear ? { month: "short", day: "numeric" }
                     : { month: "short", day: "numeric", year: "numeric" });
        const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
        const diffDays = Math.round((startOfDay(d) - startOfDay(now)) / (24 * 3600 * 1000));
        if (diffDays === 0) return _t("Today");
        if (diffDays === -1) return _t("Yesterday");
        if (diffDays === 1) return _t("Tomorrow");
        if (diffDays > 1 && diffDays <= 6) return d.toLocaleDateString(this._locale(), { weekday: "long" });
        if (diffDays < -1 && diffDays >= -6) return d.toLocaleDateString(this._locale(), { weekday: "long" });
        return bareDate();
    }

    fmtTime(isoStr) {
        if (!isoStr) return "";
        const d = this._parseDate(isoStr);
        const now = new Date();
        const hm = d.toLocaleTimeString(this._locale(), { hour: "2-digit", minute: "2-digit" });
        if (d.toDateString() === now.toDateString()) return hm;
        return `${this._dayLabel(d)}, ${hm}`;
    }

    fmtFull(isoStr) {
        if (!isoStr) return "";
        const d = this._parseDate(isoStr);
        const hm = d.toLocaleTimeString(this._locale(), { hour: "2-digit", minute: "2-digit" });
        return `${this._dayLabel(d)} · ${hm}`;
    }

    _parseDate(isoStr) {
        const utc = /Z$|[+-]\d{2}:?\d{2}$/.test(isoStr) ? isoStr : isoStr + "Z";
        return new Date(utc);
    }

    _locale() {
        const lang = document.documentElement.getAttribute("lang")
            || navigator.language || "en";
        return lang.replace("_", "-");
    }

    dateGroup(isoStr) {
        const d = this._parseDate(isoStr);
        const now = new Date();
        if (d.toDateString() === now.toDateString()) return _t("Today");
        const yest = new Date(now.getTime() - 24 * 3600 * 1000);
        if (d.toDateString() === yest.toDateString()) return _t("Yesterday");
        return _t("Earlier");
    }

    get groupedMessages() {
        const out = [];
        let current = null;
        for (const item of this.state.messages) {
            const g = this.dateGroup(item.date);
            if (!current || current.group !== g) {
                current = { group: g, items: [] };
                out.push(current);
            }
            current.items.push(item);
        }
        return out;
    }

    subjectOf(msg) {
        return msg.subject || _t("(no subject)");
    }

    initials(name) {
        if (!name) return "?";
        const parts = name.trim().split(/\s+/);
        if (parts.length === 1) return (parts[0][0] || "?").toUpperCase();
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    parseAddr(str) {
        const s = (str || "").trim();
        const m = s.match(/^"?([^"<]*)"?\s*<([^>]+)>/);
        if (m) return { name: m[1].trim() || m[2], email: m[2] };
        return { name: s, email: s.includes("@") ? s : "" };
    }

    senderName(msg) {
        return msg.author_name || this.parseAddr(msg.email_from).name || "?";
    }

    senderEmail(msg) {
        return this.parseAddr(msg.email_from).email || msg.email_from || "";
    }

    clip(name, n = 22) {
        const s = name || "";
        return s.length > n ? s.slice(0, n) + "…" : s;
    }

    frameHtml(body) {
        const raw = body || "";
        const textColor = this.state.dark ? "#c6c8cf" : "#3b3c41";
        const styleTag = `<style>
            html, body { height: auto !important; min-height: 0 !important; }
            html { margin: 0; }
            body {
                margin: 0; padding: 0;
                font-size: 13.5px; line-height: 1.65; color: ${textColor};
                word-break: break-word; background: transparent;
            }
            body, body * {
                font-family: system-ui, -apple-system, "Segoe UI",
                    Roboto, "Helvetica Neue", Arial, sans-serif !important;
            }
            img { max-width: 100% !important; height: auto; }
            table { max-width: 100%; }
            blockquote {
                margin: 8px 0; padding: 4px 12px;
                border-left: 3px solid #d8d8d5; color: #8a8c94;
            }
            pre { white-space: pre-wrap; }
            hr { border: none; border-top: 1px solid #e5e5e3; }
        </style>`;
        const trimmed = raw.trimStart();
        const isFullDoc = /^<!doctype html|^<html[\s>]/i.test(trimmed);
        if (isFullDoc) {
            if (/<head[^>]*>/i.test(raw)) {
                return raw.replace(/<head([^>]*)>/i, `<head$1>${styleTag}`);
            }
            if (/<html[^>]*>/i.test(raw)) {
                return raw.replace(/<html([^>]*)>/i, `<html$1><head>${styleTag}</head>`);
            }
        }
        return `<!DOCTYPE html>${styleTag}${raw}`;
    }

    autoSizeFrame(ev) {
        const frame = ev.target;
        const size = () => {
            try {
                const doc = frame.contentDocument;
                if (!doc || !doc.body) return;
                const h = Math.max(doc.body.scrollHeight, doc.documentElement.scrollHeight);
                if (h > 20) frame.style.height = h + 4 + "px";
            } catch (e) { /* detached: keep current height */ }
        };
        requestAnimationFrame(size);
        [150, 400, 1000, 2000].forEach((t) => setTimeout(size, t));
        try {
            const doc = frame.contentDocument;
            if (doc && doc.body && window.ResizeObserver) {
                if (frame._ntibResizeObs) frame._ntibResizeObs.disconnect();
                frame._ntibResizeObs = new ResizeObserver(size);
                frame._ntibResizeObs.observe(doc.body);
            }
        } catch (e) { /* observer is best-effort; timers above still run */ }
    }

    attachmentUrl(id) {
        return `/web/content/${id}?download=true`;
    }

    formatFileSize(bytes) {
        const size = Number(bytes) || 0;
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    fileExt(name) {
        const parts = (name || "").split(".");
        return parts.length > 1 ? parts.pop().toUpperCase().slice(0, 4) : "FILE";
    }

    showToast(msg) {
        this.state.toast = msg;
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => { this.state.toast = ""; }, 2200);
    }
}

registry.category("actions").add("northlight_teaminbox.TeamInboxBasic", TeamInboxBasic);
