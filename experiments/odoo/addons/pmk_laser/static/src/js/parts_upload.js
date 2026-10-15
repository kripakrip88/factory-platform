/** @odoo-module **/
/**
 * Задание на резку → «Детали и чертежи»: чертежи .dxf пачкой перетаскиванием (15.10.2026).
 *
 * Поле над таблицей деталей: перетащить файлы или папку (или щёлкнуть и выбрать). Ничего
 * не пишется сразу: сервер разбирает имена («пл1 10мм 20шт» → пл1, 10 мм, 20 шт) и
 * совпадения (models/task.py, pmk_upload_preview), окно «Загружено N файлов» показывает,
 * что получится из каждого файла; инженер правит имя, толщину, штуки и решение по
 * совпадению, «Добавить» — pmk_upload_apply, таблица перечитывается.
 *
 * Папка изделия: имя ближайшей папки файла приходит в разбор — при совпадении имени
 * детали у разных изделий подставляется «Изделие · пл1».
 * Запросы — через env.services.orm (useService в поле вешает вид — грабли Odoo 19).
 */
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Dialog } from "@web/core/dialog/dialog";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

function readFile(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsArrayBuffer(file);
    });
}

function toBase64(buf) {
    const bytes = new Uint8Array(buf);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
}

async function sha1(buf) {
    const digest = await crypto.subtle.digest("SHA-1", buf);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Файлы из перетаскивания, с папками: [{file, folder}]. */
async function filesFromDrop(dataTransfer) {
    const out = [];
    const items = [...(dataTransfer.items || [])];
    const entries = items.map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null)).filter(Boolean);
    if (!entries.length) {
        return [...(dataTransfer.files || [])].map((file) => ({ file, folder: "" }));
    }
    const walk = async (entry, folder) => {
        if (entry.isFile) {
            const file = await new Promise((res, rej) => entry.file(res, rej));
            out.push({ file, folder });
        } else if (entry.isDirectory) {
            const reader = entry.createReader();
            let batch;
            do {
                batch = await new Promise((res, rej) => reader.readEntries(res, rej));
                for (const child of batch) {
                    await walk(child, entry.name);
                }
            } while (batch.length);
        }
    };
    for (const entry of entries) {
        await walk(entry, "");
    }
    return out;
}

export class PartsUploadDialog extends Component {
    static template = "pmk_laser.PartsUploadDialog";
    static components = { Dialog };
    static props = ["rows", "onApply", "close"];

    setup() {
        this.state = useState({ rows: this.props.rows, busy: false, error: "" });
    }

    get loaded() {
        return this.state.rows.filter((r) => !r.skip).length;
    }

    get unresolved() {
        return this.state.rows.filter((r) => !r.skip && r.conflict === "name" && !r.decided);
    }

    setAction(row, action) {
        row.action = action;
        row.decided = true;
        this.state.error = "";
    }

    fmtThick(t) {
        return t ? String(t).replace(".", ",") : "";
    }

    async apply() {
        if (this.unresolved.length) {
            this.state.error = `Решите, что делать с совпадениями: ${this.unresolved.map((r) => r.name).join(", ")}`;
            return;
        }
        const bad = this.state.rows.filter((r) => !r.skip && r.action !== "skip" && !(Number(r.qty) > 0));
        if (bad.length) {
            this.state.error = `Укажите количество больше нуля: ${bad.map((r) => r.name).join(", ")}`;
            return;
        }
        this.state.busy = true;
        try {
            await this.props.onApply(this.state.rows);
            this.props.close();
        } catch (e) {
            this.state.busy = false;
            this.state.error = (e && e.data && e.data.message) || String(e);
        }
    }
}

export class PartsUploadField extends X2ManyField {
    static template = "pmk_laser.PartsUploadField";

    setup() {
        super.setup();
        this.upload = useState({ over: false, busy: false, note: "" });
    }

    get canUpload() {
        return !this.props.readonly;
    }

    onDragOver(ev) {
        if (!this.canUpload) {
            return;
        }
        ev.preventDefault();
        this.upload.over = true;
    }

    onDragLeave() {
        this.upload.over = false;
    }

    async onDrop(ev) {
        if (!this.canUpload) {
            return;
        }
        ev.preventDefault();
        this.upload.over = false;
        const files = await filesFromDrop(ev.dataTransfer);
        await this.start(files);
    }

    async onPick(ev) {
        const files = [...ev.target.files].map((file) => ({
            file, folder: (file.webkitRelativePath || "").split("/").slice(-2, -1)[0] || "",
        }));
        ev.target.value = "";
        await this.start(files);
    }

    async start(items) {
        if (!items.length) {
            return;
        }
        this.upload.busy = true;
        this.upload.note = "";
        try {
            const record = this.props.record;
            if (record.isNew || record.dirty) {
                const saved = await record.save();
                if (saved === false) {
                    this.upload.note = "Сначала сохраните задание — не заполнены обязательные поля.";
                    return;
                }
            }
            const read = [];
            for (const { file, folder } of items) {
                const buf = await readFile(file);
                read.push({ name: file.name, size: file.size, folder, sha1: await sha1(buf), data: toBase64(buf) });
            }
            const orm = this.env.services.orm;
            const rows = await orm.call("pmk.laser.task", "pmk_upload_preview",
                [[record.resId], read.map(({ data, ...meta }) => meta)]);
            rows.forEach((row, i) => {
                row.data = read[i].data;
                row.decided = row.conflict !== "name";
            });
            this.env.services.dialog.add(PartsUploadDialog, {
                rows,
                onApply: async (finalRows) => {
                    const res = await orm.call("pmk.laser.task", "pmk_upload_apply", [[record.resId], finalRows
                        .filter((r) => !r.skip)
                        .map((r) => ({
                            file: r.file, data: r.data, name: r.name, alt_name: r.action === "new" ? r.alt_name : "",
                            thickness: Number(String(r.thickness || "").replace(",", ".")) || 0,
                            qty: Number(r.qty) || 1, action: r.action,
                        }))]);
                    await record.load();
                    this.upload.note = `Добавлено деталей: ${res.created}, заменено чертежей: ${res.replaced}` +
                        (res.errors.length ? ` · ${res.errors.join("; ")}` : "");
                },
            });
        } finally {
            this.upload.busy = false;
        }
    }
}

registry.category("fields").add("pmk_laser_parts_upload", {
    ...x2ManyField,
    component: PartsUploadField,
});
