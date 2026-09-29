/**
 * ПРАВКА ПМК (шаг 22 плана, «Почта: новые письма быстрее», 30.09.2026):
 * список писем после синхронизации — без сброса к началу (Б2).
 *
 * Раньше каждый сигнал синхронизации перегружал список с первой страницы:
 * догруженные «Загрузить ещё» страницы терялись, прокрутка прыгала вверх.
 * При проходе раз в 2 минуты это стало бы постоянным. Теперь корень почты
 * (mail_client_action.js, refreshList) перечитывает НАЧАЛО списка — столько
 * строк, сколько на экране, и ещё страницу про запас (не больше 200), — и
 * сводит его с тем, что на экране, этой функцией:
 *
 * - список целиком (messages): свежее начало в пределах того, что было
 *   загружено, — до последней строки экрана. Запас в запросе нужен, чтобы
 *   начало дошло до неё, даже когда сверху пришли новые строки, и чтобы у
 *   полностью загруженного списка ответ был короче запроса (has_more ложно
 *   — «Загрузить ещё» не появляется зря). Строки ниже последней строки
 *   экрана не берутся — за ними «Загрузить ещё». Если начало всё же не
 *   дошло до конца загруженного (пришло больше строк, чем запас, или
 *   загружено больше 200), список обрезается по ответу, а остальное
 *   догрузит «Загрузить ещё»: приклеить к ответу уже загруженный хвост
 *   нельзя — письма, пришедшие внутрь хвоста (переложенные из Спама,
 *   ставшие подходить под фильтр), в нём не появились бы никогда, а между
 *   ответом и хвостом осталась бы дыра. Корень ставит список, только если
 *   пользователь в начале: иначе вставка сверху сдвинула бы строки у него
 *   под курсором;
 * - обновления на месте (updates): та же строка (тот же ключ и то же
 *   письмо), у которой что-то поменялось — отметки, число писем, «ждёт
 *   ответа». Ничего не сдвигают, их корень применяет и в прокрученном
 *   списке;
 * - fresh — сколько строк встанет НАД верхней строкой экрана: новые письма
 *   и переписки, в которые пришло письмо. Для плашки «N новых писем»;
 * - structural — поменялся ли состав или порядок строк (что-то пришло,
 *   ушло, переехало): в прокрученном списке это откладывается до возврата
 *   наверх;
 * - selectedIds — отмеченные галочкой после сведения: у переписки сменилось
 *   письмо-представитель — галочка переезжает на новое, строка пропала —
 *   галочка снимается (иначе «N выбрано» считало бы призраков).
 *
 * Ключ строки (rowKey): в режиме переписок — переписка (thread_key): когда
 * приходит ответ, её строку представляет уже другое письмо; без переписок —
 * письмо (id). Порядок — как у сервера: дата по убыванию, при равной дате —
 * id по убыванию.
 *
 * Чистая функция без Owl и сервисов — её проверяют hoot-тест
 * static/tests/list_refresh.test.js и node-стенд.
 */

export function rowKey(row, threaded) {
    return threaded && row.thread_key ? `t:${row.thread_key}` : `m:${row.id}`;
}

/** Строка a стоит в списке выше строки b. */
export function isAbove(a, b) {
    const da = a.date || "";
    const db = b.date || "";
    return da > db || (da === db && a.id > b.id);
}

function differs(was, row) {
    return Object.keys(row).some(
        (field) => JSON.stringify(was[field]) !== JSON.stringify(row[field])
    );
}

/**
 * current — строки на экране (state.messages); head — ответ get_messages
 * с начала списка; hasMore — state.hasMore; selectedIds — отмеченные.
 */
export function mergeListHead(
    current,
    head,
    { threaded = false, hasMore = false, selectedIds = [] } = {}
) {
    const rows = head.messages || [];
    const key = (row) => rowKey(row, threaded);
    const onScreen = new Map(current.map((row) => [key(row), row]));
    const top = current[0];

    let fresh = 0;
    const updates = [];
    for (const row of rows) {
        const was = onScreen.get(key(row));
        if (was && was.id === row.id) {
            if (differs(was, row)) {
                updates.push([was, row]);
            }
        } else if (!top || isAbove(row, top)) {
            fresh++;
        }
    }

    // Докуда брать ответ.
    // - Ответ дошёл до последней строки экрана: берём его до неё
    //   включительно — загруженное не растёт само. Строки ниже — следующая
    //   страница или новые для этого места (письмо со старой датой): их
    //   принесёт «Загрузить ещё». Ответ кончился ровно на ней — продолжение
    //   прежнее, если сервер сказал has_more (при 200 строках это значит
    //   только «строк столько, сколько просили»), и никакого, если нет.
    // - Не дошёл, и has_more ложно: это и есть весь список — строк,
    //   которых в нём нет, нет и на сервере.
    // - Не дошёл, has_more истинно (пришло больше строк, чем запас, или
    //   загружено больше 200): список — ответ, за ним «Загрузить ещё».
    //   Хвост экрана не приклеиваем — см. шапку.
    // Экран пуст — ответ как есть.
    const bottom = current[current.length - 1];
    const last = rows[rows.length - 1];
    let messages = rows;
    let more = Boolean(head.has_more);
    if (bottom && last && !isAbove(last, bottom)) {
        messages = rows.filter((row) => !isAbove(bottom, row));
        if (messages.length < rows.length) {
            more = true;
        } else if (head.has_more) {
            more = Boolean(hasMore);
        }
    }

    const structural =
        messages.length !== current.length ||
        messages.some((row, index) => {
            const was = current[index];
            return key(row) !== key(was) || row.id !== was.id;
        });

    const byId = new Set(messages.map((row) => row.id));
    const byKey = new Map(messages.map((row) => [key(row), row]));
    const wasById = new Map(current.map((row) => [row.id, row]));
    const ticked = [];
    for (const id of selectedIds) {
        let now = byId.has(id) ? id : null;
        if (now === null) {
            const was = wasById.get(id);
            now = was && byKey.has(key(was)) ? byKey.get(key(was)).id : null;
        }
        if (now !== null && !ticked.includes(now)) {
            ticked.push(now);
        }
    }

    return {
        messages,
        hasMore: more,
        updates,
        fresh,
        structural,
        selectedIds: ticked,
    };
}
