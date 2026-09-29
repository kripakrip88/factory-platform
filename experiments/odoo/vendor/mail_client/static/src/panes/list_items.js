/**
 * ПРАВКА ПМК (шаг 18 плана, «Почта как в Mail.ru», 30.09.2026): из чего
 * состоит список писем на экране.
 *
 * Строки писем (или переписок) идут, как пришли с сервера, — дата по
 * убыванию. Между ними:
 * - заголовки групп «Сегодня / Вчера / Раньше» — перед первой строкой
 *   группы; группу строке даёт bucketOf(дата);
 * - строки рассылок (digests, крючок _list_digests на сервере) — по дате
 *   своего последнего письма. Строка рассылок старше последней загруженной
 *   строки при hasMore не показывается: её место — после «Загрузить ещё»,
 *   иначе она встала бы в конец, над письмами, которые ещё не пришли.
 *
 * Чистая функция без Owl и без сервисов — её проверяют hoot-тест
 * static/tests/list_items.test.js и node-стенд. Выделение, «выбрать все» и
 * счётчики по-прежнему работают по state.messages: заголовки и рассылки —
 * только вид.
 *
 * Ответ — [{type: "group", key, bucket} | {type: "row", key, message} |
 * {type: "digest", key, digest}]. Ключи уникальны (t-key в шаблоне).
 */
export function buildListItems(messages, digests, { hasMore = false, bucketOf = () => "earlier" } = {}) {
    const items = [];
    // Дата сервера — «ГГГГ-ММ-ДД ЧЧ:ММ:СС», строкой она сравнивается верно.
    const pending = [...(digests || [])].sort((a, b) =>
        (b.date || "").localeCompare(a.date || "")
    );
    let bucket = null;
    let groups = 0;
    const push = (item, date) => {
        const current = bucketOf(date);
        if (current !== bucket) {
            bucket = current;
            // Номер в ключе: при строках без даты группа может повториться.
            items.push({ type: "group", key: `group-${current}-${groups++}`, bucket: current });
        }
        items.push(item);
    };
    const pushDigest = (digest) =>
        push({ type: "digest", key: `digest-${digest.folder_id}`, digest }, digest.date);

    let next = 0;
    for (const message of messages || []) {
        while (next < pending.length && (pending[next].date || "") >= (message.date || "")) {
            pushDigest(pending[next++]);
        }
        push({ type: "row", key: `row-${message.id}`, message }, message.date);
    }
    if (!hasMore) {
        while (next < pending.length) {
            pushDigest(pending[next++]);
        }
    }
    return items;
}
