import { Component, onWillDestroy, onWillUpdateProps, useEffect, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

import { formatMessageDate, senderName } from "../utils";
import { MessageCard } from "./message_card";

/** Новее ли письмо a письма b: по дате, при равной — по id. */
function isNewer(a, b) {
    const da = a.date || "";
    const db = b.date || "";
    return da > db || (da === db && a.id > b.id);
}

/** Самое новое письмо переписки или null. Одно правило с thread_seen.js. */
export function newestOf(thread) {
    let best = null;
    for (const item of thread || []) {
        if (!best || isNewer(item, best)) {
            best = item;
        }
    }
    return best;
}

/** Open conversation cards, oldest first. Include the selected message if the thread omits it. */
export function conversationItems(detail, thread) {
    const items = [...(thread || [])];
    if (!items.some((item) => item.id === detail.id)) {
        items.push(detail);
    }
    return items.sort((a, b) => (isNewer(a, b) ? 1 : isNewer(b, a) ? -1 : 0));
}

export class Conversation extends Component {
    static template = "mail_client.Conversation";
    static components = { MessageCard };
    static props = {
        detail: { type: Object },
        thread: { type: Array },
        getScroller: { type: Function },
        onReply: { type: Function },
        onAllowImages: { type: Function },
        onDownloadAttachment: { type: Function },
        onShown: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.conversationRef = useRef("conversation");
        this.state = useState({ details: {}, loading: {}, failed: {} });
        this.pending = new Set();
        this.epoch = 0;
        onWillUpdateProps((next) => {
            if (next.detail.id !== this.props.detail.id) {
                this.clearRequests();
                Object.assign(this.state, { details: {}, loading: {}, failed: {} });
            }
        });
        onWillDestroy(() => this.clearRequests());
        useEffect(
            (element) => {
                if (element) {
                    return this.observeCards(element);
                }
            },
            () => [this.conversationRef.el, this.props.detail.id, this.items.map((item) => item.id).join(",")]
        );
    }

    clearRequests() {
        this.epoch++;
        this.pending.clear();
    }

    get items() {
        return conversationItems(this.props.detail, this.props.thread);
    }

    get oursTitle() {
        return _t("Our message");
    }

    senderName(emailFrom) {
        return senderName(emailFrom);
    }

    formatDate(value) {
        return formatMessageDate(value);
    }

    cardDetail(item) {
        return item.id === this.props.detail.id ? this.props.detail : this.state.details[item.id];
    }

    observeCards(element) {
        const cards = element.children;
        const items = this.items;
        const epoch = this.epoch;
        const observer = new IntersectionObserver(
            (entries) => {
                if (epoch !== this.epoch) {
                    return;
                }
                for (const entry of entries) {
                    const id = Number(entry.target.dataset.messageId);
                    if (entry.isIntersecting) {
                        this.pending.add(id);
                    } else {
                        this.pending.delete(id);
                    }
                }
                void this.fetchPending();
            },
            { root: element.closest(".o_mail_client_reading_scroll"), rootMargin: "400px 0px" }
        );
        for (const [index, item] of items.entries()) {
            if (!item.body_unavailable && !this.cardDetail(item)) {
                observer.observe(cards[index]);
            }
        }
        return () => observer.disconnect();
    }

    /** Fetch at most one history message at a time as cards approach the reading area. */
    async fetchPending() {
        if (this.fetching) {
            return;
        }
        this.fetching = true;
        try {
            for (const id of this.pending) {
                this.pending.delete(id);
                if (!this.state.details[id] && !this.state.failed[id] && !this.state.loading[id]) {
                    await this.load(id);
                }
            }
        } finally {
            this.fetching = false;
        }
    }

    async load(messageId) {
        const epoch = this.epoch;
        this.state.loading[messageId] = true;
        delete this.state.failed[messageId];
        try {
            const detail = await this.orm.call("mail.client.message", "get_message_detail", [messageId]);
            if (epoch === this.epoch) {
                if (detail.body_state === "fetched") {
                    this.state.details[messageId] = detail;
                    return true;
                }
                this.state.failed[messageId] = true;
            }
        } catch {
            if (epoch === this.epoch) {
                this.state.failed[messageId] = true;
            }
        } finally {
            if (epoch === this.epoch) {
                delete this.state.loading[messageId];
            }
        }
        return false;
    }

    async retry(messageId) {
        // Background loading alone should not mark a newer message as read.
        if (await this.load(messageId)) {
            await this.props.onShown?.(messageId);
        }
    }

    async allowImages(item) {
        if (item.id === this.props.detail.id) {
            return this.props.onAllowImages();
        }
        const epoch = this.epoch;
        const detail = await this.orm.call("mail.client.message", "allow_images", [item.id]);
        if (epoch === this.epoch) {
            this.state.details[item.id] = detail;
        }
    }
}
