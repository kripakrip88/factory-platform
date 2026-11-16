<?php
// Проекты pmkpark.ru (ИБ32) из командной строки — публикация из Телеграма (16.11.2026).
// Вызывается ТОЛЬКО через gate.sh (контейнер site-web). Удаления нет: снять = hide.
//   php project.php add  <папка>   — папка: project.json + фото; создаёт АКТИВНЫЙ проект
//   php project.php hide <id>      — снять с сайта (ACTIVE=N)
//   php project.php show <id>      — вернуть на сайт
//   php project.php list           — последние 15
// Вывод — одна строка JSON: {"ok":true,...} или {"ok":false,"error":"..."}.
//
// project.json:
// { "name": "...", "section": "metallokonstruktsii", "date": "2026-10",
//   "object_type": "...", "city": "...", "orderer": "...", "result": "...",
//   "stat_1": ["50 000", "колец за год"], "stat_2": ["500", "штук в смену"],
//   "benefits": ["Заголовок|подпись", ...], "ch": {"CH_MAT": "Ст3", "CH_MASS": "12 т", ...},
//   "catalog_section": "vintovye-svai", "services": ["Лазерная резка металла", ...],
//   "preview_text": "...", "task": "...", "detail_text": "абзац\n\nабзац",
//   "seo_h1": "...", "seo_title": "...", "seo_desc": "...",
//   "photos": [{"file": "1.jpg", "alt": "..."}, ...],      // 1 — шапка, 2 — «что сделали»/превью, далее галерея
//   "draft": true }                                         // необязательно: создать скрытым (проверка)
require __DIR__ . '/_boot.php';

function out($a) { echo json_encode($a, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n"; exit(empty($a['ok']) ? 1 : 0); }
function fail($m) { out(['ok' => false, 'error' => $m]); }
function esc($s) { return htmlspecialchars(trim((string)$s), ENT_QUOTES, 'UTF-8'); }
function paras($t) {
    $t = trim(str_replace("\r", '', (string)$t)); if ($t === '') return '';
    return implode("\n", array_map(fn($p) => '<p>' . nl2br(esc($p), false) . '</p>', preg_split("~\n\s*\n~", $t)));
}
function clear_cache() {
    BXClearCache(true, '/');
    if (isset($GLOBALS['CACHE_MANAGER'])) $GLOBALS['CACHE_MANAGER']->CleanAll();
    if (isset($GLOBALS['stackCacheManager'])) $GLOBALS['stackCacheManager']->CleanAll();
    CIBlock::clearIblockTagCache(PMK_PROJECTS_IB);
}
function url_of($id) {   // шаблон ИБ32 «#SECTION_CODE#/#ELEMENT_CODE#/» без /projects/ — собираем сами
    $e = CIBlockElement::GetList([], ['IBLOCK_ID' => PMK_PROJECTS_IB, 'ID' => $id], false, false, ['ID', 'CODE', 'IBLOCK_SECTION_ID'])->Fetch();
    if (!$e) return null;
    $s = $e['IBLOCK_SECTION_ID'] ? CIBlockSection::GetByID($e['IBLOCK_SECTION_ID'])->Fetch() : null;
    return 'https://pmkpark.ru/projects/' . ($s ? $s['CODE'] . '/' : '') . $e['CODE'] . '/';
}
const MONTHS = ['январь'=>1,'февраль'=>2,'март'=>3,'апрель'=>4,'май'=>5,'июнь'=>6,'июль'=>7,'август'=>8,'сентябрь'=>9,'октябрь'=>10,'ноябрь'=>11,'декабрь'=>12];

$cmd = $argv[1] ?? '';
if ($cmd === 'list') {
    $r = CIBlockElement::GetList(['ID' => 'DESC'], ['IBLOCK_ID' => PMK_PROJECTS_IB], false, ['nTopCount' => 15], ['ID', 'NAME', 'ACTIVE', 'ACTIVE_FROM']);
    $a = []; while ($e = $r->Fetch()) $a[] = ['id' => (int)$e['ID'], 'active' => $e['ACTIVE'] === 'Y', 'date' => $e['ACTIVE_FROM'], 'name' => $e['NAME'], 'url' => url_of($e['ID'])];
    out(['ok' => true, 'projects' => $a]);
}
if ($cmd === 'hide' || $cmd === 'show') {
    $id = (int)($argv[2] ?? 0);
    $e = CIBlockElement::GetList([], ['IBLOCK_ID' => PMK_PROJECTS_IB, 'ID' => $id], false, false, ['ID', 'NAME'])->Fetch();
    if (!$e) fail("нет проекта $id в ИБ32");
    $el = new CIBlockElement;
    if (!$el->Update($id, ['ACTIVE' => $cmd === 'show' ? 'Y' : 'N'])) fail($el->LAST_ERROR);
    clear_cache();
    out(['ok' => true, 'id' => $id, 'active' => $cmd === 'show', 'name' => $e['NAME'], 'url' => url_of($id)]);
}
if ($cmd !== 'add') fail('команда: add <папка> | hide <id> | show <id> | list');

// ---------- add ----------
$dir = rtrim($argv[2] ?? '', '/');
$j = json_decode(@file_get_contents("$dir/project.json"), true);
if (!is_array($j)) fail('нет или битый project.json');
$name = trim($j['name'] ?? ''); if ($name === '' || mb_strlen($name) > 250) fail('name: пусто или длиннее 250');

// Заказчика на сайте не называем (Антон 16.11.2026: «эти данные мы на сайт не выкладываем»).
// Ловим юрлица в любом тексте карточки, включая подписи фото. Сфера заказчика (orderer) — можно.
$texts = [];
array_walk_recursive($j, function ($v, $k) use (&$texts) { if (is_string($v) && $k !== 'file' && $k !== 'section' && $k !== 'catalog_section') $texts[] = $v; });
$legal = '~(?<![\p{L}])(ООО|ОАО|ЗАО|ПАО|НАО|АО|ИП|ГУП|МУП|ФГУП|ГКУ|МКУ|ГБУ|МБУ|ФГБУ|АНО|LLC|Ltd|GmbH)(?![\p{L}])~u';
foreach ($texts as $t) if (preg_match($legal, $t, $m)) fail("заказчика называть нельзя: в тексте «{$m[1]}» — уберите юрлицо, пишите сферу («застройщик», «промышленное предприятие»)");

// SEO обязательно (Антон 16.11.2026: «сразу готовил под сео — тайтл, дескрипшен, альты»)
foreach (['seo_title' => [20, 80], 'seo_desc' => [70, 200], 'seo_h1' => [10, 150]] as $sk => [$mn, $mx]) {
    $l = mb_strlen(trim($j[$sk] ?? ''));
    if ($l < $mn || $l > $mx) fail("{$sk}: нужно {$mn}–{$mx} знаков, сейчас {$l}");
}

$sec = CIBlockSection::GetList([], ['IBLOCK_ID' => PMK_PROJECTS_IB, '=CODE' => $j['section'] ?? ''], false, ['ID'])->Fetch();
if (!$sec) fail('section: нет раздела «' . ($j['section'] ?? '') . '» в ИБ32 (см. справочник)');

// дата: "2026-10" или "октябрь 2026" → 1-е число месяца (сортировка и плашка «месяц год» берутся из ACTIVE_FROM)
$d = trim(mb_strtolower($j['date'] ?? ''));
if (preg_match('~^(\d{4})-(\d{1,2})$~', $d, $m)) { $y = (int)$m[1]; $mo = (int)$m[2]; }
elseif (preg_match('~^(\p{L}+)\s+(\d{4})$~u', $d, $m) && isset(MONTHS[$m[1]])) { $y = (int)$m[2]; $mo = MONTHS[$m[1]]; }
else fail('date: нужен формат 2026-10 или «октябрь 2026»');
if ($mo < 1 || $mo > 12 || $y < 2000 || $y > 2100) fail('date: странная дата');
$activeFrom = sprintf('01.%02d.%04d 00:00:00', $mo, $y);
$dateText = array_search($mo, MONTHS) . " $y";

$catId = false;
if (!empty($j['catalog_section'])) {
    $c = CIBlockSection::GetList([], ['IBLOCK_ID' => 37, '=CODE' => $j['catalog_section']], false, ['ID'])->Fetch();
    if (!$c) fail('catalog_section: нет раздела «' . $j['catalog_section'] . '» в каталоге ИБ37');
    $catId = $c['ID'];
}
$services = [];
foreach ((array)($j['services'] ?? []) as $sn) {
    $s = CIBlockElement::GetList([], ['IBLOCK_ID' => 33, '=NAME' => trim($sn)], false, false, ['ID'])->Fetch();
    if (!$s) fail("services: нет услуги «{$sn}» в ИБ33 (названия — из справочника)");
    $services[] = $s['ID'];
}

$photos = (array)($j['photos'] ?? []);
if (!$photos) fail('photos: нужно хотя бы одно фото');
$files = [];
foreach ($photos as $i => $p) {
    $fn = basename((string)($p['file'] ?? ''));
    $path = "$dir/$fn";
    if ($fn === '' || !is_file($path)) fail("photos[$i]: нет файла «{$fn}»");
    $info = @getimagesize($path);
    if (!$info || !in_array($info[2], [IMAGETYPE_JPEG, IMAGETYPE_PNG, IMAGETYPE_WEBP], true)) fail("photos[$i]: «{$fn}» — не jpg/png/webp");
    if (filesize($path) > 15 * 1024 * 1024) fail("photos[$i]: «{$fn}» больше 15 МБ");
    $alt = trim((string)($p['alt'] ?? ''));
    if ($alt === '') fail("photos[$i]: нет подписи alt");
    $f = CFile::MakeFileArray($path); $f['description'] = $alt; $f['MODULE_ID'] = 'iblock';
    $files[] = $f;
}

// символьный код: транслит названия, уникальный в ИБ32
$base = CUtil::translit($name, 'ru', ['max_len' => 90, 'change_case' => 'L', 'replace_space' => '-', 'replace_other' => '-', 'delete_repeat_replace' => true]);
$base = trim($base, '-') ?: 'proekt';
$code = $base; $k = 2;
while (CIBlockElement::GetList([], ['IBLOCK_ID' => PMK_PROJECTS_IB, '=CODE' => $code], [])) $code = $base . '-' . $k++;

$prop = [
    'OBJECT_TYPE' => $j['object_type'] ?? '', 'CITY' => $j['city'] ?? '', 'ORDERER' => $j['orderer'] ?? '',
    'RESULT' => $j['result'] ?? '', 'DATE_DONE' => $dateText,
    'STAT_1_VALUE' => $j['stat_1'][0] ?? '', 'STAT_1_LABEL' => $j['stat_1'][1] ?? '',
    'STAT_2_VALUE' => $j['stat_2'][0] ?? '', 'STAT_2_LABEL' => $j['stat_2'][1] ?? '',
    'BENEFITS' => array_values(array_filter(array_map('trim', (array)($j['benefits'] ?? [])))),
    'LINK_SERVICES' => $services,
    'SEO_H1' => $j['seo_h1'] ?? '', 'SEO_TITLE' => $j['seo_title'] ?? '', 'SEO_DESC' => $j['seo_desc'] ?? '',
    'FORM_ORDER' => 66, 'FORM_QUESTION' => 67,           // кнопки «Заказать» / «Задать вопрос» — как у остальных проектов
];
if ($catId) $prop['LINK_CATALOG_SECTION'] = $catId;
if (trim($j['task'] ?? '') !== '') $prop['TASK_PROJECT'] = ['VALUE' => ['TEXT' => paras($j['task']), 'TYPE' => 'html']];
$chOk = ['CH_QTY','CH_DIAM','CH_MASS','CH_MAT','CH_THICK','CH_SECT','CH_HEIGHT','CH_LENGTH','CH_AREA','CH_RAL','CH_COATING','CH_OBJECT'];
foreach ((array)($j['ch'] ?? []) as $ck => $cv) { if (!in_array($ck, $chOk, true)) fail("ch: нет характеристики $ck"); $prop[$ck] = $cv; }
// Шаблон страницы (karneev-prod …/projects/page_blocks/element_1.php): DETAIL_PICTURE — шапка,
// PREVIEW_PICTURE — блок «что сделали» и превью в списках, PHOTOS — галерея. Одно фото — PREVIEW пустой
// (шаблон сам возьмёт DETAIL и не задвоит).
if (count($files) > 2) {
    $prop['PHOTOS'] = [];
    foreach (array_slice($files, 2) as $n => $f) $prop['PHOTOS']["n$n"] = ['VALUE' => $f, 'DESCRIPTION' => $f['description']];
}

$fields = [
    'IBLOCK_ID' => PMK_PROJECTS_IB, 'IBLOCK_SECTION_ID' => $sec['ID'], 'ACTIVE' => empty($j['draft']) ? 'Y' : 'N',
    'NAME' => $name, 'CODE' => $code, 'ACTIVE_FROM' => $activeFrom, 'SORT' => 500,
    // анонс шаблон выводит экранированным под H1 — только простой текст, без <p> (16.11: на странице были видны теги)
    'PREVIEW_TEXT' => trim(preg_replace('~\s+~u', ' ', (string)($j['preview_text'] ?? ''))), 'PREVIEW_TEXT_TYPE' => 'text',
    'DETAIL_TEXT' => paras($j['detail_text'] ?? ''), 'DETAIL_TEXT_TYPE' => 'html',
    'DETAIL_PICTURE' => $files[0], 'PREVIEW_PICTURE' => $files[1] ?? false,
    'PROPERTY_VALUES' => $prop,
];
$ipt = [];
if (!empty($j['seo_title'])) $ipt['ELEMENT_META_TITLE'] = $j['seo_title'];
if (!empty($j['seo_desc'])) $ipt['ELEMENT_META_DESCRIPTION'] = $j['seo_desc'];
if (!empty($j['seo_h1'])) $ipt['ELEMENT_PAGE_TITLE'] = $j['seo_h1'];
if ($ipt) $fields['IPROPERTY_TEMPLATES'] = $ipt;

$el = new CIBlockElement;
$id = $el->Add($fields, false, true, true);
if (!$id) fail('Bitrix: ' . strip_tags($el->LAST_ERROR));
clear_cache();
out(['ok' => true, 'id' => (int)$id, 'active' => empty($j['draft']), 'code' => $code, 'url' => url_of($id), 'photos' => count($files)]);
