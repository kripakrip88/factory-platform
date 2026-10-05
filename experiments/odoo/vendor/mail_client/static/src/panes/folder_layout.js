/** @odoo-module **/
/**
 * ПРАВКА ПМК (шаг 41 разбора удобства, А8, 05.10.2026): дерево папок как в
 * Mail.ru — правила без Owl и без сервисов (node-тест
 * static/tests/step41_rules.test.mjs).
 *
 * Было: плоский список в порядке сервера (роль, имя). Стало:
 * - подпапки — с отступом под родителем (у pmkpark@ под «Входящими» лежат
 *   «Авито Фарпост Юла», «Рассылки», «Чеки»), в порядке сервера: сначала
 *   свои папки, потом сортировщики mail.ru — они у сервера в конце;
 * - служебные папки (Входящие, Черновики, Отправленные, Спам, Корзина) —
 *   всегда верхним уровнем, даже если на сервере они вложены (у zakaz@ все
 *   служебные — INBOX.Sent, INBOX.Junk…), и всегда видны, даже пустые;
 * - пустые прочие и архив (0 писем в Odoo — в окне синхронизации) — под
 *   раскрывающимся «Ещё папки», у pmkpark@ их 11. Пустой родитель видимой
 *   подпапки не прячется. Открытая папка из «Ещё» не переезжает наверх —
 *   «Ещё папки» раскрываются сами, пока она открыта (folder_tree.js);
 * - узкая полоса значков — только служебные папки (railFolders).
 *
 * Вернуть прежнее: nest: false и hideEmpty: false (folder_tree.js) — список
 * снова плоский и без «Ещё папки».
 *
 * Папка — как её отдаёт get_inbox_state: {id, name, role, parent_id,
 * unread, quiet, total}. total нет (старый сервер) — папка не пустая.
 */

export const SERVICE_ROLES = ["inbox", "drafts", "sent", "spam", "trash"];
const HIDEABLE_ROLES = ["other", "archive"];

export function isServiceFolder(folder) {
    return SERVICE_ROLES.includes(folder.role);
}

/** Пустая и не служебная: таких — под «Ещё папки». */
export function isEmptyFolder(folder) {
    return HIDEABLE_ROLES.includes(folder.role) && folder.total === 0;
}

/**
 * Раскладка папок одного ящика: {main: [{folder, depth}], more: [{folder,
 * depth: 0, parentName}]}. Порядок — как у сервера, дети сразу после
 * родителя (обход в глубину).
 */
export function layoutFolders(folders, { nest = true, hideEmpty = true } = {}) {
    const list = folders || [];
    const byId = new Map(list.map((folder) => [folder.id, folder]));
    const children = new Map();
    const roots = [];
    for (const folder of list) {
        const parent = nest && !isServiceFolder(folder) ? byId.get(folder.parent_id) : null;
        if (parent && parent.id !== folder.id) {
            if (!children.has(parent.id)) {
                children.set(parent.id, []);
            }
            children.get(parent.id).push(folder);
        } else {
            roots.push(folder);
        }
    }

    const visible = new Map();
    const seen = new Set();
    const isVisible = (folder) => {
        if (visible.has(folder.id)) {
            return visible.get(folder.id);
        }
        visible.set(folder.id, true); // защита от петли в parent_id
        const kids = children.get(folder.id) || [];
        const shown = !hideEmpty || !isEmptyFolder(folder) || kids.some(isVisible);
        visible.set(folder.id, shown);
        return shown;
    };

    const main = [];
    const more = [];
    const walk = (folder, depth, parentName) => {
        if (seen.has(folder.id)) {
            return;
        }
        seen.add(folder.id);
        if (isVisible(folder)) {
            main.push({ folder, depth });
        } else {
            more.push({ folder, depth: 0, parentName });
        }
        for (const kid of children.get(folder.id) || []) {
            walk(kid, depth + 1, folder.name);
        }
    };
    for (const folder of roots) {
        walk(folder, 0, "");
    }
    return { main, more };
}

/** Узкая полоса значков: служебные папки ящика, в порядке сервера. */
export function railFolders(folders) {
    return (folders || []).filter(isServiceFolder);
}

/** Число на значке полосы: до 99, дальше «99+». */
export function railCount(count) {
    const value = Number(count) || 0;
    if (value <= 0) {
        return "";
    }
    return value > 99 ? "99+" : String(value);
}
