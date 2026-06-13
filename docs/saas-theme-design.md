# saas_theme — дизайн оболочки ERPNext (как должно быть)

Справочник по UI-решениям темы `services/erp/saas_theme`. Сверяться при откатах
и регрессиях. Все решения проверены вживую на сервере (Frappe v16).

Реперные теги:
- `saas-theme-horizontal-nav-v1` — горизонтальная навигация (стабильно)
- `saas-theme-dual-sidebar-v1` — старый dual sidebar (точка полного отката)

Маркер сборки: `SAAS_THEME_BUILD` в `public/js/saas_theme.js` + `?v=N` в
`hooks.py`. Меняются ВМЕСТЕ при любой правке JS/CSS. CI сверяет маркер с тем,
что отдаёт nginx (см. `docs/deploy-assets.md`).

---

## 1. Горизонтальная навигация (вместо dual sidebar)

Два бара вместо вертикального рейла + сайдбара:
- **Модуль-бар** (`.fp-module-bar`) — тёмный, sticky сверху: иконки+подписи
  воркспейсов из `frappe.boot.desktop_icons`.
- **Подменю-бар** (`.fp-submenu-bar`) — разделы активного модуля из
  `frappe.boot.workspace_sidebar_item[label.toLowerCase()].items`.

Грабли Frappe (ключевое):
- На desk-страницах **нет `.navbar`** — вставлять UI через
  `$('.main-section').prepend()`. `.main-section` сделана `display:flex;
  flex-direction:column`, бары `flex-shrink:0; width:100%`.
- Frappe перерисовывает шапку и сносит наш бар — `build_module_bar()` проверяет
  наличие по DOM (`if ($('.fp-module-bar').length) return`), флаг ставится
  только после фактической вставки, есть retry на `sidebar_setup`/`page-change`
  + таймеры.
- Маршрут пункта строится в `get_route_for_item()` по `link_type`:
  - `Workspace` → `frappe.router.slug(link_to)` (иначе «Главная» → ошибка
    «страница не найдена»: маршрут воркспейса слагифицируется, `Frappe CRM` →
    `/desk/frappe-crm`)
  - `DocType` → `['List', link_to]`, `Dashboard` → `['dashboard-view', link_to]`,
    `Report` → `['query-report', link_to]`, `Page` → `[link_to]`
  - непостроимые пункты не рендерятся.
- Активный пункт подменю — **точное совпадение или префикс** маршрута, НЕ
  `includes()` (пустая строка матчит всё → подсвечивались все пункты).
- Подменю-бар **переносит** пункты (`flex-wrap:wrap; overflow-x:visible`), не
  уезжает за экран.

Цветной активный модуль — **индивидуальный цвет на каждый модуль** (палитра
`WORKSPACE_COLORS`, как у старого левого рейла: CRM индиго, Продажи синий,
Закупки янтарный, Запасы зелёный, Производство красный и т.д.).
`update_module_bar_active()` ставит инлайн: фон `color + '2e'` (~18% тонировка,
`!important` — иначе ядро перебивает), иконку в цвет, и кастомное свойство
`--fp-active-color`, которым `.active::after` красит подчёркивание. Цвет берётся
из `get_workspace_color(label)`.

Действия в баре справа: поиск, уведомления, переключатель темы (иконки
`es-line-search`, `es-line-notifications`, `moon`/`sun`).

Уведомления: родной dropdown живёт внутри **скрытого** сайдбара. По клику его
переносим в `body` (`.fp-notifications-dropdown`, fixed top-right), иначе
`display:none` родителя его прячет.

Тема: `data-theme-mode` — источник правды у Frappe, `data-theme` производный.
`toggle_theme()` ставит `data-theme-mode`, зовёт `frappe.ui.set_theme()`,
сохраняет в localStorage + профиль. Иконка луна↔солнце по текущей теме.

## 2. Тёмная тема — цвета и контраст

Палитра (НЕ менять, только через `var(--...)`):
- `--bg-color: #0D1117`, `--fg-color: #161B22`, `--primary: #4D94FF`
- светлая: `--bg-color: #F6F9FC`, `--fg-color: #FFFFFF`, `--primary: #0052FF`

Переменные тёмной темы заданы на `html[data-theme="dark"]` (а не
`[data-theme="dark"]`) — иначе одноимённые правила ядра Frappe, загружаемые
позже, перебивают наши «тёмно-синие» значения чёрными.

Грабли контраста:
- Ховер строки списка: ядро красит `.list-row-container:hover` через
  `var(--highlight-color)`, который в тёмной теме НЕ переопределён и равен
  светлому `#F6F9FC` (слепящая белая строка). Фикс: переопределить
  `--highlight-color: rgba(255,255,255,0.05)` в `html[data-theme="dark"]`.
- Заголовки виджетов дашборда: `.widget-title` вычисляется в `#30363D`
  (нечитаемо на тёмном) → переопределяем в `var(--text-color)`.

## 3. Контролы шапки списка (стиль МойСклад)

Источник правды — родные API Frappe ListView, наш слой меняет только
представление. Только для `cur_list.view_name === 'List'` (не отчёты/kanban/
форма). Graceful fallback: класс скрытия родного контрола вешается ТОЛЬКО после
успешного рендера нашего.

- **Фильтры:** родная кнопка переименована в «Фильтры • N ▾» (счётчик из
  `filter_area.get().length`, `MutationObserver` переустанавливает после
  перерисовок). Опасный крестик `.filter-x-button` скрыт — сброс всех фильтров
  только внутри родного popover. Панель = родной popover (там же удаление по
  одному и «+ Добавить фильтр»).
- **Сортировка:** одна кнопка «<поле> ↑/↓ ▾», меню со списком полей из
  `sort_selector.args.options` (не хардкод) + иконка-стрелка направления рядом с
  «Сортировать по:» (клик меняет asc/desc, меню не закрывается). Применение:
  `sort_selector.set_value(by, order)` меняет состояние, **рефреш делает
  `onchange(by, order)`**.
- **Вторичные кнопки → иконки:** «Представление списка» (текст в
  `.custom-btn-group-label` скрыт CSS, иконка+каретка остаются) и «Сохранённые
  фильтры» (голый текстовый узел обёрнут+скрыт, добавлена иконка
  `icon-bookmark`). Tooltip с полным названием. «+ Добавить …» — единственная
  текстовая кнопка.
- **Выравнивание:** обе кнопки `align-self:flex-start` — иначе при переносе
  фильтр-полей на 2 строки кнопки «проваливаются» в вертикальную середину.
- **Высота/обводка:** высота 28px как у полей; бордер `var(--border-color)`
  (приглушённый, не яркий `#E3E8EE`) на filter/sort/`.st-cancel-btn`/
  `.match-type-dropdown-btn` (значки `≈`)/`.icon-btn` (⟳)/`.menu-more-button`.

## 4. Кнопка «Отмена» на новых документах

Глобально через `$(document).on('form-refresh', (e, frm) => ...)` (событие
отдаёт `frm`), НЕ per-doctype Client Script.

- На `frm.is_new()` — своя кнопка `.st-cancel-btn` (вторичный стиль) перед
  `frm.page.btn_primary`. **Не** через `set_secondary_action`: тяжёлые формы
  (Quotation/BOM/Purchase Order) прячут `btn_secondary` в позднем цикле refresh.
  Своя кнопка переживает перерисовки.
- Вставка отложена на 50ms (после рендера шапки Frappe).
- Сохранён/существующий документ → кнопка удаляется.
- Клик → `frappe.set_route('List', frm.doctype)`.

## 5. Корень `/` → `/desk`

`hooks home_page = "desk"` покрывает только website-роуты; для залогиненных `/`
отдаёт легаси-лаунчер. Фикс — патч nginx-шаблона во frontend-образе (Dockerfile):
`location = / { return 302 /desk; }`.

---

## Связанные документы

- `docs/deploy-assets.md` — как ассеты доезжают до браузера, smoke-тест, запрет
  ручных копий в контейнеры.
- `CLAUDE.md` → «Версии frappe/erpnext» — пин версий парой (прецедент дрейфа
  16.22/16.20, из-за которого Work Order рендерился пустым).
