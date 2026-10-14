/**
 * ПРАВКА ПМК (редизайн почты, 14.10.2026, просьба Антона «аватары для
 * отправителей»): кружок с инициалами в строке списка — как в Mail.ru.
 *
 * Чистые функции, без Odoo: их же гоняет node-тест avatar.test.mjs.
 *
 * - Инициалы: первые буквы двух первых слов имени; правовая форма (ООО, ИП,
 *   АО…) и кавычки не в счёт — «ООО «Первое Грузовое Такси»» → «ПГ». Имени
 *   нет — первая буква адреса.
 * - Тон: от адреса (не от имени) — у одного отправителя всегда один цвет,
 *   как бы он ни подписывался. Восемь бледных тонов (mail_client.scss,
 *   .o_mc_av_0…7): лаймом и яркими заливками не красим.
 */
export const AVATAR_TONES = 8;

const LEGAL = new Set(["ооо", "оао", "зао", "пао", "ао", "ип", "нао", "ано", "фгуп", "муп", "гуп", "llc", "ltd", "inc"]);

export function avatarInitials(name, address) {
    // Вместо имени адрес — инициалы по адресу.
    const words = (/@/.test(name || "") ? "" : name || "")
        .replace(/["«»“”„'()]/g, " ")
        .split(/[\s,.]+/)
        .filter((word) => /[\p{L}\p{N}]/u.test(word) && !LEGAL.has(word.toLowerCase()));
    if (!words.length) {
        const local = (address || name || "").trim();
        const letter = local.match(/[\p{L}\p{N}]/u);
        return letter ? letter[0].toUpperCase() : "?";
    }
    return words
        .slice(0, 2)
        .map((word) => word.match(/[\p{L}\p{N}]/u)[0].toUpperCase())
        .join("");
}

export function avatarTone(key) {
    let hash = 0;
    for (const char of (key || "").toLowerCase()) {
        hash = (hash * 31 + char.codePointAt(0)) >>> 0;
    }
    return hash % AVATAR_TONES;
}
