<?php
// Выгрузка проектов pmkpark.ru (ИБ32) в Markdown — для Claude в Телеграме (образцы текста, 16.11.2026).
// Запуск в контейнере site-web:  php export-md.php /tmp/out
//   <out>/projects/<код>.md   — по файлу на активный проект (текст, свойства, подписи фото)
//   <out>/_справочник.md      — разделы ИБ32, дерево каталога ИБ37, услуги ИБ33 (выбирать только из них)
// Только чтение базы.
require __DIR__ . '/_boot.php';
$out = rtrim($argv[1] ?? '/tmp/pmkproj/out', '/');
@mkdir("$out/projects", 0755, true);

function txt($html) {
    $s = preg_replace('~<br\s*/?>|</p>|</li>|</h\d>~i', "\n", (string)$html);
    $s = preg_replace('~<li[^>]*>~i', '- ', $s);
    $s = html_entity_decode(strip_tags($s), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $s = preg_replace("~[ \t]+~u", ' ', $s);
    return trim(preg_replace("~\n\s*\n\s*\n+~", "\n\n", $s));
}
function names($ib, $ids) {
    $ids = array_filter((array)$ids); if (!$ids) return [];
    $r = CIBlockElement::GetList([], ['IBLOCK_ID' => $ib, 'ID' => $ids], false, false, ['ID', 'NAME']);
    $n = []; while ($x = $r->Fetch()) $n[] = $x['NAME']; return $n;
}
function sectionPath($id) {
    if (!$id) return '';
    $p = []; $r = CIBlockSection::GetNavChain(false, $id, ['NAME', 'CODE']);
    while ($x = $r->Fetch()) $p[] = "{$x['NAME']} ({$x['CODE']})";
    return implode(' → ', $p);
}
$sections = [];
$r = CIBlockSection::GetList([], ['IBLOCK_ID' => PMK_PROJECTS_IB], false, ['ID', 'CODE', 'NAME']);
while ($x = $r->Fetch()) $sections[$x['ID']] = $x;

$res = CIBlockElement::GetList(['ACTIVE_FROM' => 'DESC', 'SORT' => 'ASC'], ['IBLOCK_ID' => PMK_PROJECTS_IB, 'ACTIVE' => 'Y'], false, false,
    ['ID', 'NAME', 'CODE', 'IBLOCK_SECTION_ID', 'ACTIVE_FROM', 'PREVIEW_TEXT', 'DETAIL_TEXT', 'DETAIL_PICTURE', 'PREVIEW_PICTURE']);
$n = 0; $index = [];
while ($e = $res->Fetch()) {
    $props = [];
    $pr = CIBlockElement::GetProperty(PMK_PROJECTS_IB, $e['ID'], ['sort' => 'asc'], []);
    while ($p = $pr->Fetch()) {
        $v = $p['VALUE']; if ($v === null || $v === '' || $v === false) continue;
        if (is_array($v) && isset($v['TEXT'])) $v = $v['TEXT'];
        $props[$p['CODE']]['name'] = $p['NAME'];
        $props[$p['CODE']]['type'] = $p['PROPERTY_TYPE'];
        $props[$p['CODE']]['values'][] = ['v' => $v, 'desc' => $p['DESCRIPTION'], 'enum' => $p['VALUE_ENUM']];
    }
    $sec = $sections[$e['IBLOCK_SECTION_ID']] ?? null;
    $url = 'https://pmkpark.ru/projects/' . ($sec ? $sec['CODE'] . '/' : '') . $e['CODE'] . '/';
    $date = $e['ACTIVE_FROM'] ? FormatDate('f Y', MakeTimeStamp($e['ACTIVE_FROM'])) : '';
    $L = ["# {$e['NAME']}", '', "- Ссылка: $url", "- Раздел сайта: " . ($sec ? "{$sec['NAME']} ({$sec['CODE']})" : '—'), "- Дата на сайте: $date", "- ID: {$e['ID']}, код: {$e['CODE']}"];
    $simple = ['OBJECT_TYPE', 'CITY', 'ORDERER', 'RESULT', 'STAT_1_VALUE', 'STAT_1_LABEL', 'STAT_2_VALUE', 'STAT_2_LABEL',
        'CH_OBJECT', 'CH_QTY', 'CH_DIAM', 'CH_MASS', 'CH_MAT', 'CH_THICK', 'CH_SECT', 'CH_HEIGHT', 'CH_LENGTH', 'CH_AREA', 'CH_RAL', 'CH_COATING',
        'SEO_H1', 'SEO_TITLE', 'SEO_DESC'];
    foreach ($simple as $c) if (isset($props[$c])) $L[] = "- {$props[$c]['name']} [$c]: " . txt($props[$c]['values'][0]['v']);
    if (isset($props['CATEGORY'])) $L[] = "- Категория [CATEGORY]: " . $props['CATEGORY']['values'][0]['enum'];
    if (isset($props['LINK_CATALOG_SECTION'])) $L[] = "- Раздел каталога [LINK_CATALOG_SECTION]: " . sectionPath($props['LINK_CATALOG_SECTION']['values'][0]['v']);
    if (isset($props['LINK_SERVICES'])) $L[] = "- Услуги [LINK_SERVICES]: " . implode('; ', names(33, array_column($props['LINK_SERVICES']['values'], 'v')));
    if (isset($props['BENEFITS'])) { $L[] = "- Выгоды [BENEFITS]:"; foreach ($props['BENEFITS']['values'] as $b) $L[] = "  - " . txt($b['v']); }
    if ($e['PREVIEW_TEXT']) { $L[] = ''; $L[] = '## Анонс (PREVIEW_TEXT)'; $L[] = txt($e['PREVIEW_TEXT']); }
    if (isset($props['TASK_PROJECT'])) { $L[] = ''; $L[] = '## Задача (TASK_PROJECT)'; $L[] = txt($props['TASK_PROJECT']['values'][0]['v']); }
    if ($e['DETAIL_TEXT']) { $L[] = ''; $L[] = '## Описание (DETAIL_TEXT)'; $L[] = txt($e['DETAIL_TEXT']); }
    $ph = [];
    if ($e['DETAIL_PICTURE']) { $f = CFile::GetFileArray($e['DETAIL_PICTURE']); $ph[] = "- главное фото: " . ($f['DESCRIPTION'] ?: '(без подписи)'); }
    foreach (($props['PHOTOS']['values'] ?? []) as $i => $p) { $f = CFile::GetFileArray($p['v']); $ph[] = "- галерея " . ($i + 1) . ": " . (($p['desc'] ?: ($f['DESCRIPTION'] ?? '')) ?: '(без подписи)'); }
    if ($ph) { $L[] = ''; $L[] = '## Фото и подписи (alt)'; array_push($L, ...$ph); }
    file_put_contents("$out/projects/{$e['CODE']}.md", implode("\n", $L) . "\n");
    $index[] = "- $date — [{$e['NAME']}](projects/{$e['CODE']}.md)" . ($sec ? " · {$sec['NAME']}" : '');
    $n++;
}

// Справочник: только эти значения допустимы в новом проекте
$R = ['# Справочник для проектов pmkpark.ru', '', 'Выгружено ' . date('d.m.Y H:i') . '. Выбирать значения ТОЛЬКО отсюда, не придумывать.', '', '## Разделы проектов (ИБ32) — обязателен один'];
foreach ($sections as $s) $R[] = "- {$s['CODE']} — {$s['NAME']}";
$R[] = ''; $R[] = '## Каталог изделий (ИБ37) — поле «Тип изделия», указывать КОД раздела';
$r = CIBlockSection::GetList(['left_margin' => 'asc'], ['IBLOCK_ID' => 37, 'ACTIVE' => 'Y'], false, ['ID', 'CODE', 'NAME', 'DEPTH_LEVEL']);
while ($x = $r->Fetch()) $R[] = str_repeat('  ', $x['DEPTH_LEVEL'] - 1) . "- {$x['CODE']} — {$x['NAME']}";
$R[] = ''; $R[] = '## Услуги (ИБ33) — можно несколько, указывать названия как здесь';
$r = CIBlockElement::GetList(['SORT' => 'ASC', 'NAME' => 'ASC'], ['IBLOCK_ID' => 33, 'ACTIVE' => 'Y'], false, false, ['ID', 'NAME']);
while ($x = $r->Fetch()) $R[] = "- {$x['NAME']}";
$R[] = ''; $R[] = "## Все проекты ($n, новые сверху)"; array_push($R, ...$index);
file_put_contents("$out/_справочник.md", implode("\n", $R) . "\n");
echo "проектов: $n → $out\n";
