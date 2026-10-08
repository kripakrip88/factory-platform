/** @odoo-module **/
/**
 * Колонки у каждого (шаг 55): настройки списков этой страницы.
 *
 * Настройки приходят вместе со страницей (session_info, ключ
 * pmk_list_prefs — models/ir_http.py): список рисуется сразу как надо, без
 * мигания и лишних запросов. Дальше — кэш в памяти страницы: правка видна
 * сразу (оптимистично), на сервер уходит в фоне.
 *
 * ⚠️ ЗАПРОСЫ — ЧЕРЕЗ env.services.orm, НЕ useService: промис, защищённый
 * компонентом, не разрешается после его уничтожения (грабля шага 31,
 * воронка) — список закрыли, пока шло сохранение, и цепочка повисла бы.
 *
 * Сохранения одного списка идут по очереди: человек тянет две колонки
 * подряд — второй запрос не обгоняет первый и не создаёт вторую запись.
 * Вместе с настройкой уходит сама правка — сервер сливает её с хранимой
 * (models/list_prefs.py, pmk_save), так что старый кэш другой вкладки не
 * затирает чужие ширины и порядок.
 *
 * Не сохранилось (сеть, сервер) — своя настройка остаётся на экране до
 * перезагрузки, человеку — предупреждение. Сигнал, а не запрет: список
 * работает как работал.
 */
import { session } from "@web/session";

const MODEL = "pmk.list.prefs";

const initial = session.pmk_list_prefs || {};
const cache = {
    own: { ...(initial.own || {}) },
    common: { ...(initial.common || {}) },
};
const queues = {};

function enqueue(key, job) {
    const previous = queues[key] || Promise.resolve();
    const next = previous.catch(() => {}).then(job);
    queues[key] = next;
    return next;
}

function warn(env, message) {
    const notification = env.services && env.services.notification;
    if (notification) {
        notification.add(message, { type: "warning" });
    }
}

const NOT_SAVED =
    "Настройка колонок не сохранилась на сервере — она действует до перезагрузки страницы.";

export const listPrefsStore = {
    /** Своя настройка списка или null. */
    own(key) {
        return cache.own[key] || null;
    },

    /** Общая («у всех по умолчанию») или null. */
    common(key) {
        return cache.common[key] || null;
    },

    /**
     * Своя настройка: в кэш сразу, на сервер — в фоне.
     *
     * change — сама правка (что поменял человек). Есть в базе своя
     * настройка — сервер сливает правку с ней, а не заменяет её целиком:
     * другая вкладка браузера могла сохранить своё, а кэш этой вкладки —
     * со времени загрузки страницы. Ответ сервера (то, что теперь хранится)
     * встаёт в кэш, если за это время человек не сделал новую правку.
     * Промис отдаёт сохранённую настройку, при ошибке — prefs как есть.
     */
    saveOwn(env, key, resModel, prefs, change = null) {
        cache.own[key] = prefs;
        const orm = env.services && env.services.orm;
        if (!orm) {
            return Promise.resolve(prefs);
        }
        return enqueue(key, () =>
            orm.silent.call(MODEL, "pmk_save", [key, resModel || false, prefs, change || false])
        ).then(
            (saved) => {
                if (saved && typeof saved === "object" && cache.own[key] === prefs) {
                    cache.own[key] = saved;
                    return saved;
                }
                return prefs;
            },
            () => {
                warn(env, NOT_SAVED);
                return prefs;
            }
        );
    },

    /** Вернуть общую (или штатную, если общей нет). */
    resetOwn(env, key) {
        const before = cache.own[key];
        delete cache.own[key];
        const orm = env.services && env.services.orm;
        if (!orm || !before) {
            return Promise.resolve(true);
        }
        return enqueue(key, () => orm.silent.call(MODEL, "pmk_reset", [key])).catch(() => {
            warn(env, NOT_SAVED);
            return false;
        });
    },

    /**
     * «Сделать так у всех» — только администратор (проверяет сервер).
     * Своя настройка администратора по этому списку при этом снимается: он
     * сразу видит то, что увидят все. Возвращает {prefs, users_on_common}
     * или null, если не вышло (кэш тогда возвращается как был).
     */
    async saveCommon(env, key, resModel, prefs) {
        const before = { own: cache.own[key], common: cache.common[key] };
        cache.common[key] = prefs;
        delete cache.own[key];
        try {
            return await enqueue(key, () =>
                env.services.orm.silent.call(MODEL, "pmk_save_common", [
                    key,
                    resModel || false,
                    prefs,
                ])
            );
        } catch {
            if (before.own) {
                cache.own[key] = before.own;
            }
            if (before.common) {
                cache.common[key] = before.common;
            } else {
                delete cache.common[key];
            }
            warn(env, "Не получилось сохранить настройку колонок для всех.");
            return null;
        }
    },

    /** «Убрать общую» — только администратор. */
    async resetCommon(env, key) {
        const before = cache.common[key];
        delete cache.common[key];
        try {
            await enqueue(key, () =>
                env.services.orm.silent.call(MODEL, "pmk_reset_common", [key])
            );
            return true;
        } catch {
            if (before) {
                cache.common[key] = before;
            }
            warn(env, "Не получилось убрать общую настройку колонок.");
            return false;
        }
    },
};
