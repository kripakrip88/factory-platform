// node vendor/mail_client/static/tests/avatar.test.mjs — правила аватаров строки.
import assert from "node:assert/strict";
import { avatarInitials, avatarTone, AVATAR_TONES } from "../src/panes/avatar.js";

const cases = [
    [["Попова Вероника Андреевна", "v.popova@example.org"], "ПВ"],
    [["ООО «Первое Грузовое Такси»", "taxi@example.org"], "ПГ"],
    [["ИП Чулков В.В.", "a@example.org"], "ЧВ"],
    [["Оксана", "oksana@example.org"], "О"],
    [["", "u.pyankova@example.org"], "U"],
    [["u.pyankova@example.org", "u.pyankova@example.org"], "U"],
    [["ООО", "zakaz@example.org"], "Z"],
    [["", ""], "?"],
];
let n = 0;
for (const [[name, address], want] of cases) {
    assert.equal(avatarInitials(name, address), want, `${name} / ${address}`);
    n++;
}
const tone = avatarTone("v.popova@example.org");
assert.equal(tone, avatarTone("V.Popova@example.org"));
assert.ok(tone >= 0 && tone < AVATAR_TONES);
n += 2;
console.log(`${n} проверок аватаров прошло`);
