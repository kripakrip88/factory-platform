// Доборные элементы — конструктор сечения (v2). Порт финального прототипа в Frappe Page.
// Геометрия/рисование/UX — строго по прототипу dobor-profile-builder. Данные (цвета/шаблоны/заказ) —
// в DocTypes через metal_calculator.dobor.api. Тема берётся из ERPNext Desk (своего тумблера нет).

frappe.pages["dobor_builder"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Доборные элементы"), single_column: true });
	inject_dobor_styles();
	$(page.body).html(DOBOR_HTML);
	init_dobor(page);
};

function inject_dobor_styles() {
	if (document.getElementById("dobor-styles")) return;
	const css = `
	.dobor-wrap{--bg:#12161d;--bg2:#1a1f29;--panel:#1e2530;--panel2:#232b38;--line:#2d3645;--line2:#3a4555;
		--ink:#e6ebf2;--muted:#8a97a8;--faint:#5b6675;--accent:#5b8def;--accent-soft:#1e3050;--bend:#3ed0b8;
		--grid:#1f2632;--canvas-bg:#161b24;color:var(--ink);font-size:13px}
	.dobor-wrap.light{--bg:#eef1f4;--bg2:#e4e9ee;--panel:#fff;--panel2:#f2f5f8;--line:#d6dce2;--line2:#c3ccd5;
		--ink:#1a232c;--muted:#5f6b78;--faint:#9aa6b2;--accent:#2563eb;--accent-soft:#dbe6fb;--grid:#e6ebf0;--canvas-bg:#fbfcfd}
	.dobor-wrap .layout{display:grid;grid-template-columns:1fr 360px;gap:16px}
	@media(max-width:920px){.dobor-wrap .layout{grid-template-columns:1fr}}
	.dobor-wrap .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
	.dobor-wrap .panel-head{padding:10px 14px;border-bottom:1px solid var(--line);background:var(--bg2);font-size:12px;font-weight:650;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);display:flex;justify-content:space-between;align-items:center}
	.dobor-wrap .canvas-wrap{position:relative;background:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:20px 20px;background-color:var(--canvas-bg)}
	.dobor-wrap svg#db_canvas{display:block;width:100%;height:440px;touch-action:none;cursor:crosshair}
	.dobor-wrap .toolbar{display:flex;gap:6px;padding:10px 14px;border-bottom:1px solid var(--line);flex-wrap:wrap;align-items:center;background:var(--bg2)}
	.dobor-wrap button{font-family:inherit;font-size:12.5px;border:1px solid var(--line2);background:var(--panel2);color:var(--ink);padding:6px 12px;border-radius:7px;cursor:pointer;font-weight:550;transition:all .12s}
	.dobor-wrap button:hover{border-color:var(--accent)}
	.dobor-wrap button.on{background:var(--accent);color:#fff;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
	.dobor-wrap button.ghost{color:var(--muted);background:transparent}
	.dobor-wrap button.danger:hover{border-color:#ff5a6e;color:#ff5a6e}
	.dobor-wrap .hint{font-size:11.5px;color:var(--muted);padding:8px 14px;background:var(--bg2);border-top:1px solid var(--line)}
	.dobor-wrap .seg-list{padding:6px 0;max-height:230px;overflow-y:auto}
	.dobor-wrap .seg{display:grid;grid-template-columns:22px 1fr 1fr 26px;gap:8px;align-items:center;padding:6px 14px;font-size:12.5px}
	.dobor-wrap .seg + .seg{border-top:1px solid var(--line)}
	.dobor-wrap .seg-tag{width:22px;height:22px;border-radius:6px;background:var(--accent);color:#fff;font-size:11px;font-weight:650;display:flex;align-items:center;justify-content:center}
	.dobor-wrap .seg label{font-size:10px;color:var(--muted);display:block;margin-bottom:1px;text-transform:uppercase}
	.dobor-wrap .seg input{width:100%;font-family:inherit;font-size:12.5px;border:1px solid var(--line2);background:var(--bg2);border-radius:5px;padding:3px 6px;color:var(--ink)}
	.dobor-wrap .seg input:focus{outline:none;border-color:var(--accent)}
	.dobor-wrap .seg .del{background:none;border:none;color:var(--faint);cursor:pointer;font-size:15px;padding:0}
	.dobor-wrap .angle-row{padding:6px 14px;font-size:12px;color:var(--bend);display:flex;align-items:center;gap:8px;background:rgba(62,208,184,.08)}
	.dobor-wrap .angle-row input{width:64px;font-size:12px;border:1px solid rgba(62,208,184,.4);border-radius:5px;padding:2px 6px;color:var(--bend);background:transparent}
	.dobor-wrap .res-row{display:flex;justify-content:space-between;align-items:baseline;padding:9px 14px;font-size:13px}
	.dobor-wrap .res-row + .res-row{border-top:1px solid var(--line)}
	.dobor-wrap .res-row .k{color:var(--muted)}
	.dobor-wrap .res-row .v{font-weight:650;font-variant-numeric:tabular-nums;color:var(--ink)}
	.dobor-wrap .res-row.big .v{font-size:18px;color:var(--accent)}
	.dobor-wrap .res-row.big{background:var(--accent-soft)}
	.dobor-wrap .inputs{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:10px 14px;border-top:1px solid var(--line)}
	.dobor-wrap .field label{font-size:10px;color:var(--muted);text-transform:uppercase;display:block;margin-bottom:2px}
	.dobor-wrap .field input,.dobor-wrap .field select{width:100%;font-family:inherit;font-size:12.5px;border:1px solid var(--line2);background:var(--bg2);border-radius:6px;padding:5px 7px;color:var(--ink)}
	.dobor-wrap .field input:focus,.dobor-wrap .field select:focus{outline:none;border-color:var(--accent)}
	.dobor-wrap .empty{padding:24px 14px;text-align:center;color:var(--faint);font-size:12.5px}
	.dobor-wrap .preset-bar{display:flex;gap:6px;padding:8px 14px;border-top:1px solid var(--line);flex-wrap:wrap;background:var(--bg2);align-items:center}
	.dobor-wrap .bar-div{width:1px;align-self:stretch;background:var(--line);margin:0 2px}
	.dobor-wrap .knob{position:absolute;width:42px;height:42px;border-radius:50%;border:1.5px solid var(--line2);background:var(--panel2);color:var(--ink);z-index:15;display:flex;align-items:center;justify-content:center;user-select:none;box-shadow:0 2px 8px rgba(0,0,0,.25)}
	.dobor-wrap select,.dobor-wrap input[type=number],.dobor-wrap input[type=text]{font-family:inherit}
	`;
	const el = document.createElement("style");
	el.id = "dobor-styles";
	el.textContent = css;
	document.head.appendChild(el);
}

const DOBOR_HTML = `
<div class="dobor-wrap"><div class="layout">
  <div class="panel">
    <div class="toolbar">
      <button id="db_undo" class="ghost">↶ Отменить точку</button>
      <button id="db_clear" class="ghost danger">Очистить</button>
      <span style="flex:1"></span>
      <span style="font-size:11.5px;color:var(--muted)">наведи на точку — тащи; клик по полю — новая полка; клик по числу — правка</span>
    </div>
    <div class="canvas-wrap"><svg id="db_canvas" viewBox="0 0 760 440"></svg></div>
    <div class="hint">Кликай по полю — добавляется полка. Поворот ⟳ (клик 5°, зажми — свободно), выравнивание ▭, переворот ⥯, направление наращивания ⤙/⤚ — кнопки в углу холста.</div>
    <div class="preset-bar">
      <span style="font-size:11px;color:var(--muted);margin-right:2px">Завальцовка:</span>
      <button id="db_hemL">◧ Слева</button><button id="db_hemLflip" title="Перевернуть левую">⮃</button>
      <button id="db_hemR">◨ Справа</button><button id="db_hemRflip" title="Перевернуть правую">⮃</button>
      <input id="db_hemLen" type="number" value="15" min="1" title="Длина завальцовки, мм" style="width:50px;border:1px solid var(--line);border-radius:6px;padding:4px 6px;background:var(--bg2);color:var(--ink)">
      <span style="font-size:11px;color:var(--muted)">мм</span>
      <span class="bar-div"></span>
      <span style="font-size:11px;color:var(--muted);margin-right:2px">Краска:</span>
      <button id="db_paintToggle">🎨 выкл</button><button id="db_paintSide" title="Сторона окраски">↔ Сторона</button>
      <span class="bar-div"></span>
      <button id="db_lock">🤝 Замок</button>
    </div>
    <div class="preset-bar">
      <span style="font-size:11px;color:var(--muted);margin-right:2px">Шаблон:</span>
      <select id="db_tplSel" style="border:1px solid var(--line2);background:var(--bg2);color:var(--ink);border-radius:7px;padding:5px 8px;min-width:200px"><option value="">— выбрать шаблон —</option></select>
      <input id="db_tplName" type="text" placeholder="имя нового шаблона" style="border:1px solid var(--line2);background:var(--bg2);color:var(--ink);border-radius:7px;padding:5px 8px;width:150px">
      <button id="db_tplAdd" title="Сохранить текущий профиль как шаблон">＋ В шаблоны</button>
      <button id="db_tplDel" class="ghost" title="Удалить выбранный шаблон">🗑</button>
    </div>
    <div class="panel" style="margin-top:14px">
      <div class="panel-head">Расчёт</div>
      <div class="results">
        <div class="res-row big"><span class="k">Развёртка (ширина заготовки)<br><span style="font-size:10.5px;color:var(--muted);font-weight:400" id="db_devNote"></span></span><span class="v" id="db_dev">— мм</span></div>
        <div class="res-row"><span class="k">Полок / гибов</span><span class="v" id="db_count">0 / 0</span></div>
        <div class="res-row"><span class="k">Площадь 1 планки</span><span class="v" id="db_area">— м²</span></div>
        <div class="res-row"><span class="k">Вес 1 планки</span><span class="v" id="db_w1">— кг</span></div>
        <div class="res-row"><span class="k">Вес всего</span><span class="v" id="db_wall">— кг</span></div>
        <div class="res-row" style="border-top:1px solid var(--line)"><span class="k">Полос из ширины <span id="db_coilEcho">1250</span></span><span class="v" id="db_strips">—</span></div>
      </div>
    </div>
    <div class="panel" style="margin-top:14px">
      <div class="panel-head"><span>Заказ доборок</span><span id="db_savedCount" style="color:#ff9a4d">0</span></div>
      <div class="preset-bar" style="border-top:none">
        <span style="font-size:11px;color:var(--muted)">Заказ:</span>
        <select id="db_orderSel" style="border:1px solid var(--line2);background:var(--bg2);color:var(--ink);border-radius:7px;padding:5px 8px;min-width:170px"><option value="">— новый заказ —</option></select>
        <input id="db_customer" type="text" placeholder="клиент / изделие" style="border:1px solid var(--line2);background:var(--bg2);color:var(--ink);border-radius:7px;padding:5px 8px;width:160px">
        <button id="db_orderSave" style="border-color:#2f9e6e;color:#5fe0a8;font-weight:600">💾 Сохранить заказ</button>
        <button id="db_orderPrint" title="Производственный лист PDF">🖨 Печать листа</button>
        <button id="db_orderNew" class="ghost" title="Очистить заказ">🗑 Новый</button>
      </div>
      <div id="db_savedList" style="padding:8px 14px 12px"><div class="empty" style="padding:14px 0">Пусто — собери профиль и нажми «В заказ»</div></div>
      <div class="res-row" style="border-top:1px solid var(--line)"><span class="k">Итого: планок / вес</span><span class="v"><span id="db_ordQty">0</span> шт / <span id="db_ordW">0</span> кг</span></div>
    </div>
  </div>
  <div>
    <div class="panel" style="margin-bottom:14px">
      <div class="panel-head"><span>Полки и гибы</span><span id="db_segCount">0</span></div>
      <div id="db_segList" class="seg-list"><div class="empty">Профиль пуст — нарисуй его на холсте слева</div></div>
    </div>
    <div class="panel">
      <div class="panel-head">Параметры доборки</div>
      <div class="inputs">
        <div class="field"><label>Толщина, мм</label><select id="db_thick"><option selected>0.45</option><option>0.5</option><option>0.55</option><option>0.7</option><option>1</option></select></div>
        <div class="field"><label>Цвет / покрытие</label><select id="db_color"></select></div>
        <div class="field"><label>Длина планки, мм</label><input id="db_len" type="number" value="2500" min="1"></div>
        <div class="field"><label>Количество, шт</label><input id="db_qty" type="number" value="1" min="1"></div>
        <div class="field"><label>Ширина рулона/листа, мм</label><input id="db_coil" type="number" value="1250" min="1"></div>
      </div>
      <div style="padding:10px 14px;background:var(--bg2);display:flex;gap:8px;flex-wrap:wrap;border-top:1px solid var(--line)">
        <button id="db_save" style="border-color:#2f9e6e;color:#5fe0a8;font-weight:600">＋ В заказ</button>
        <button id="db_new" style="border-color:#2f9e6e;color:#5fe0a8;font-weight:600">Новая доборка</button>
      </div>
    </div>
  </div>
</div></div>`;

function init_dobor(page) {
	const SVGNS = "http://www.w3.org/2000/svg";
	// page.body во Frappe — jQuery-объект; берём DOM-ноду для querySelector
	const body = (page.body && page.body.jquery) ? page.body[0] : (page.body[0] || page.body);
	const root = body.querySelector(".dobor-wrap");
	const G = (id) => body.querySelector("#" + id);
	const svg = G("db_canvas");
	const canvasWrap = body.querySelector(".dobor-wrap .canvas-wrap");
	const esc = frappe.utils.escape_html;

	// состояние профиля
	let start = { x: 180, y: 300 }, segs = [], started = false;
	let hemLeft = false, hemRight = false, hemLeftDir = 1, hemRightDir = -1, hemLen = 15;
	let paintSide = 1, paintOn = false, lockOn = false, growEnd = true;
	let isLight = false, dragIdx = -1, hoverIdx = -1;
	const GRAB = 14;
	const massPerSqm = (t) => t * 7.85;

	// ── тема из ERPNext Desk (свой тумблер не нужен) ──
	function readTheme() {
		const t = (document.documentElement.getAttribute("data-theme") || document.documentElement.getAttribute("data-theme-mode") || "").toLowerCase();
		isLight = t !== "dark";
		root.classList.toggle("light", isLight);
	}
	readTheme();
	const themeObs = new MutationObserver(() => { readTheme(); drawCanvas(); });
	themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-theme-mode"] });

	// ── геометрия ──
	function verts() {
		const v = [{ x: start.x, y: start.y }]; let cur = { ...start };
		for (const s of segs) { const r = s.dir * Math.PI / 180; cur = { x: cur.x + s.len * Math.cos(r), y: cur.y - s.len * Math.sin(r) }; v.push({ x: cur.x, y: cur.y }); }
		return v;
	}
	function bendAngle(i) { let d = segs[i].dir - segs[i - 1].dir; while (d > 180) d -= 360; while (d < -180) d += 360; return d; } // знаковое отклонение
	function flangeAngle(i) { return 180 - Math.abs(bendAngle(i)); }       // угол МЕЖДУ полками 0..180 (для UI)
	function applyFlangeAngle(i, want) {                                    // задать угол между полками → поворот хвоста
		want = Math.max(0, Math.min(180, want));
		const cur = bendAngle(i), sign = cur < 0 ? -1 : 1, newDev = sign * (180 - want), delta = newDev - cur;
		for (let k = i; k < segs.length; k++) segs[k].dir += delta;
	}
	function svgPt(e) { const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY; const ctm = svg.getScreenCTM(); if (!ctm) return { x: 0, y: 0 }; const inv = pt.matrixTransform(ctm.inverse()); return { x: inv.x, y: inv.y }; }
	const snap = (v) => Math.round(v / 5) * 5; // шаг привязки 5 мм

	function addPoint(p) {
		const v = verts();
		if (growEnd) {
			const last = v[v.length - 1]; const dx = p.x - last.x, dy = -(p.y - last.y); const len = Math.round(Math.hypot(dx, dy)); if (len < 5) return;
			segs.push({ len, dir: Math.round(Math.atan2(dy, dx) * 180 / Math.PI) });
		} else {
			const first = v[0]; const dx = first.x - p.x, dy = -(first.y - p.y); const len = Math.round(Math.hypot(dx, dy)); if (len < 5) return;
			start = { x: p.x, y: p.y }; segs.unshift({ len, dir: Math.round(Math.atan2(dy, dx) * 180 / Math.PI) });
		}
		render();
	}

	// ── вписывание чертежа (мир → viewBox 760×440) ──
	let view = { k: 1, cx: 380, cy: 220 };
	function computeFit() {
		const v = verts(); if (v.length < 1) { view = { k: 1, cx: 380, cy: 220 }; return; }
		let minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
		v.forEach((p) => { if (p.x < minx) minx = p.x; if (p.y < miny) miny = p.y; if (p.x > maxx) maxx = p.x; if (p.y > maxy) maxy = p.y; });
		const cx = (minx + maxx) / 2, cy = (miny + maxy) / 2, bw = Math.max(1, maxx - minx), bh = Math.max(1, maxy - miny), pad = 100;
		let k = Math.min((760 - pad) / bw, (440 - pad) / bh); k = Math.max(0.05, Math.min(1.8, k)); view = { k, cx, cy };
	}
	const D = (p) => ({ x: (p.x - view.cx) * view.k + 380, y: (p.y - view.cy) * view.k + 220 });
	const Dinv = (d) => ({ x: (d.x - 380) / view.k + view.cx, y: (d.y - 220) / view.k + view.cy });

	// ── инлайн-редактор размера на чертеже ──
	let editKind = null, editIdx = -1;
	const inlineEdit = document.createElement("input");
	inlineEdit.type = "number";
	inlineEdit.style.cssText = "position:absolute;display:none;width:62px;font-size:12px;padding:3px 5px;border:1.5px solid #5b8def;border-radius:6px;background:#1a1f29;color:#e6ebf2;z-index:20;box-shadow:0 4px 12px rgba(0,0,0,.4)";
	canvasWrap.appendChild(inlineEdit);
	function openEdit(kind, idx, sx, sy, val) { editKind = kind; editIdx = idx; inlineEdit.value = val; inlineEdit.style.left = (sx - 31) + "px"; inlineEdit.style.top = (sy - 12) + "px"; inlineEdit.style.display = "block"; setTimeout(() => { inlineEdit.focus(); inlineEdit.select(); }, 0); }
	function applyEdit() { if (editKind == null) return; if (editKind === "len") { segs[editIdx].len = Math.max(1, parseFloat(inlineEdit.value) || segs[editIdx].len); } else if (editKind === "bend") { applyFlangeAngle(editIdx, parseFloat(inlineEdit.value) || 0); } inlineEdit.style.display = "none"; editKind = null; render(); }
	inlineEdit.addEventListener("keydown", (e) => { if (e.key === "Enter") applyEdit(); if (e.key === "Escape") { inlineEdit.style.display = "none"; editKind = null; } });
	inlineEdit.addEventListener("blur", applyEdit);
	function labelScreenPos(el) { const r = el.getBoundingClientRect(), wr = canvasWrap.getBoundingClientRect(); return { x: r.left - wr.left + r.width / 2, y: r.top - wr.top + r.height / 2 }; }

	// ── 4 круглые кнопки в углу холста ──
	function mkKnob(top, txt, title) { const k = document.createElement("div"); k.className = "knob"; k.style.top = top + "px"; k.style.right = "8px"; k.style.fontSize = "17px"; k.textContent = txt; k.title = title; canvasWrap.appendChild(k); return k; }
	// 1) поворот: клик = 5°, зажатие + движение = свободно
	const rotKnob = mkKnob(8, "⟳", "Повернуть добор для выравнивания"); rotKnob.style.cursor = "grab";
	let rotDragging = false, rotPrev = 0, rotMoved = false;
	const knobAngle = (e) => { const r = rotKnob.getBoundingClientRect(); return Math.atan2(e.clientY - (r.top + r.height / 2), e.clientX - (r.left + r.width / 2)) * 180 / Math.PI; };
	rotKnob.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); if (segs.length < 1) return; rotDragging = true; rotMoved = false; rotPrev = knobAngle(e); rotKnob.setPointerCapture(e.pointerId); rotKnob.style.cursor = "grabbing"; });
	rotKnob.addEventListener("pointermove", (e) => { if (!rotDragging) return; const a = knobAngle(e); let d = a - rotPrev; if (Math.abs(d) > 0.3) rotMoved = true; rotPrev = a; for (const s of segs) s.dir -= d; if (rotMoved) drawCanvas(); });
	rotKnob.addEventListener("pointerup", () => { if (rotDragging && !rotMoved) { for (const s of segs) s.dir -= 5; drawCanvas(); } rotDragging = false; rotKnob.style.cursor = "grab"; });
	// 2) выравнивание: длинная полка горизонтально; симметричный домик — по оси симметрии
	const alignBtn = mkKnob(58, "▭", "Выровнять эскиз"); alignBtn.style.cursor = "pointer"; alignBtn.style.fontSize = "16px";
	function alignMinBox() {
		if (segs.length < 1) return;
		let maxLen = -1; for (const s of segs) if (s.len > maxLen) maxLen = s.len;
		const longIdx = []; for (let i = 0; i < segs.length; i++) if (Math.abs(segs[i].len - maxLen) < 0.5) longIdx.push(i);
		if (longIdx.length === 2 && longIdx[1] === longIdx[0] + 1) { // симметрия (домик/конёк) → по биссектрисе
			const i = longIdx[0], a1 = (segs[i].dir + 180) * Math.PI / 180, a2 = segs[i + 1].dir * Math.PI / 180;
			const bx = Math.cos(a1) + Math.cos(a2), by = Math.sin(a1) + Math.sin(a2); let bis = Math.atan2(by, bx) * 180 / Math.PI;
			const delta = -90 - bis; for (const s of segs) s.dir += delta; render(); return;
		}
		const degr = segs[longIdx[0]].dir; for (const s of segs) s.dir -= degr; render(); // длинную — горизонтально
	}
	alignBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); });
	alignBtn.addEventListener("click", (e) => { e.stopPropagation(); alignMinBox(); });
	// 3) переворот по вертикали (зеркало верх↔низ)
	const flipBtn = mkKnob(108, "⥯", "Перевернуть эскиз по вертикали"); flipBtn.style.cursor = "pointer";
	flipBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); });
	flipBtn.addEventListener("click", (e) => { e.stopPropagation(); if (segs.length < 1) return; for (const s of segs) s.dir = -s.dir; hemLeftDir *= -1; hemRightDir *= -1; paintSide *= -1; render(); }); // зеркало: завальцовка и краска тоже меняют сторону
	// 4) направление наращивания (в конец/в начало)
	const growKnob = mkKnob(158, "⤙", ""); growKnob.style.cursor = "pointer"; growKnob.style.fontSize = "16px"; growKnob.style.fontWeight = "700";
	function updateGrowKnob() { growKnob.title = growEnd ? "Полки добавляются в КОНЕЦ (нажми — в начало)" : "Полки добавляются в НАЧАЛО (нажми — в конец)"; growKnob.textContent = growEnd ? "⤙" : "⤚"; growKnob.style.borderColor = growEnd ? "var(--line2)" : "var(--accent)"; growKnob.style.color = growEnd ? "var(--ink)" : "var(--accent)"; }
	updateGrowKnob();
	growKnob.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); });
	growKnob.addEventListener("click", (e) => { e.stopPropagation(); growEnd = !growEnd; updateGrowKnob(); });

	function render() { drawCanvas(); buildSegList(); updateResults(); }
	function renderLight() { drawCanvas(); updateResults(); } // живой ввод — без пересборки списка
	function mk(tag, attrs) { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }

	function drawCanvas() {
		if (dragIdx < 0) computeFit();
		while (svg.firstChild) svg.removeChild(svg.firstChild);
		const v = verts().map(D);
		const INK = isLight ? "#111111" : "#f0f4f8"; // монохромный контур по теме

		if (v.length >= 2) {
			// слой краски — пунктир со смещением по нормали (отключаемый)
			if (paintOn) {
				const colorRaw = (G("db_color") || {}).value || "Цинк|#b9c2cc";
				const paintHex = colorRaw.split("|")[1] || "#ff6a8a";
				const darken = (hex, f) => { const m = hex.replace("#", ""); const r = Math.round(parseInt(m.slice(0, 2), 16) * f), g = Math.round(parseInt(m.slice(2, 4), 16) * f), b = Math.round(parseInt(m.slice(4, 6), 16) * f); return "#" + [r, g, b].map((x) => x.toString(16).padStart(2, "0")).join(""); };
				const paintDark = darken(paintHex, 0.62);
				const off = v.map((p, i) => { let nx = 0, ny = 0; if (i < v.length - 1) { const dx = v[i + 1].x - p.x, dy = v[i + 1].y - p.y, l = Math.hypot(dx, dy) || 1; nx += -dy / l; ny += dx / l; } if (i > 0) { const dx = p.x - v[i - 1].x, dy = p.y - v[i - 1].y, l = Math.hypot(dx, dy) || 1; nx += -dy / l; ny += dx / l; } const l = Math.hypot(nx, ny) || 1; return (p.x + nx / l * 6 * paintSide) + "," + (p.y + ny / l * 6 * paintSide); }).join(" ");
				svg.appendChild(mk("polyline", { points: off, fill: "none", stroke: paintDark, "stroke-width": "1.8", "stroke-dasharray": "4 3", "stroke-linejoin": "round" }));
			}

			const FOLDGAP = 7, norms = [], dirs = [];
			for (let i = 0; i < segs.length; i++) { const a = v[i], b = v[i + 1]; let dx = b.x - a.x, dy = b.y - a.y; const l = Math.hypot(dx, dy) || 1; norms.push({ x: -dy / l, y: dx / l }); dirs.push({ x: dx / l, y: dy / l }); }
			const isFold = (i) => i >= 1 && i < segs.length && Math.abs(bendAngle(i)) > 150;

			// контур: монохром, одна линия; на загибе 180° — округлая петля наружу
			let dPath = "M " + v[0].x + " " + v[0].y;
			for (let i = 1; i < v.length; i++) {
				if (i < segs.length && isFold(i)) {
					const n = norms[i - 1], tipx = v[i].x + dirs[i - 1].x * FOLDGAP, tipy = v[i].y + dirs[i - 1].y * FOLDGAP;
					const a = { x: tipx + n.x * FOLDGAP * 0.7, y: tipy + n.y * FOLDGAP * 0.7 }, b = { x: tipx - n.x * FOLDGAP * 0.7, y: tipy - n.y * FOLDGAP * 0.7 };
					dPath += ` L ${a.x} ${a.y} Q ${tipx + dirs[i - 1].x * FOLDGAP} ${tipy + dirs[i - 1].y * FOLDGAP} ${b.x} ${b.y} L ${v[i].x} ${v[i].y}`;
				} else dPath += ` L ${v[i].x} ${v[i].y}`;
			}
			svg.appendChild(mk("path", { d: dPath, fill: "none", stroke: INK, "stroke-width": "3.2", "stroke-linejoin": "round", "stroke-linecap": "round" }));

			// метка загиба 180°
			for (let i = 1; i < segs.length; i++) {
				if (!isFold(i)) continue; const tipx = v[i].x + dirs[i - 1].x * FOLDGAP, tipy = v[i].y + dirs[i - 1].y * FOLDGAP;
				const lt = mk("text", { x: tipx + dirs[i - 1].x * 13, y: tipy + dirs[i - 1].y * 13 + 3, "text-anchor": "middle", "font-size": "9", "font-weight": "700", fill: "#3ea0c9" }); lt.textContent = "подгиб 180°"; svg.appendChild(lt);
			}

			// завальцовка — чистый полукруг в цвет контура
			function drawHem(edgeV, u, flip) {
				const nx = -u.y * flip, ny = u.x * flip, r = 4.5, L = 16, sx = edgeV.x, sy = edgeV.y, bx = sx + nx * 2 * r, by = sy + ny * 2 * r, ex = bx + u.x * L, ey = by + u.y * L, k = r * 4 / 3, c1x = sx - u.x * k, c1y = sy - u.y * k, c2x = bx - u.x * k, c2y = by - u.y * k;
				svg.appendChild(mk("path", { d: `M ${sx} ${sy} C ${c1x} ${c1y} ${c2x} ${c2y} ${bx} ${by} L ${ex} ${ey}`, fill: "none", stroke: INK, "stroke-width": "3.2", "stroke-linecap": "round", "stroke-linejoin": "round" }));
				const t = mk("text", { x: (bx + ex) / 2 + nx * 12, y: (by + ey) / 2 + ny * 12 + 3, "text-anchor": "middle", "font-size": "9.5", "font-weight": "700", fill: isLight ? "#666" : "#9fb0c4" }); t.textContent = "завальц. " + hemLen; svg.appendChild(t);
			}
			const unit = (a, b) => { const dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy) || 1; return { x: dx / l, y: dy / l }; };
			if (hemLeft && segs.length >= 1) drawHem(v[0], unit(v[0], v[1]), hemLeftDir);
			if (hemRight && segs.length >= 1) drawHem(v[v.length - 1], unit(v[v.length - 1], v[v.length - 2]), hemRightDir);

			// символ «Замок» (рукопожатие) — ч/б, фиксированная зона снизу по центру
			if (lockOn && segs.length >= 1) {
				const cx = 380, cy = 372;
				svg.appendChild(mk("rect", { x: cx - 26, y: cy - 22, width: "52", height: "44", rx: "9", fill: "#ffffff", stroke: "#1a1f29", "stroke-width": "1.4" }));
				const g = mk("g", { transform: `translate(${cx},${cy}) scale(0.95)`, stroke: "#111", "stroke-width": "2.4", "stroke-linecap": "round", "stroke-linejoin": "round", fill: "none" });
				g.appendChild(mk("path", { d: "M -20 7 L -8 -3" }));
				g.appendChild(mk("path", { d: "M 20 7 L 8 -3" }));
				g.appendChild(mk("path", { d: "M -8 -3 Q -1 2 3 -1 Q 7 -4 9 -2", "stroke-width": "2.8" }));
				g.appendChild(mk("path", { d: "M -3 0 l 3 5" }));
				g.appendChild(mk("path", { d: "M 1 -1 l 3 5" }));
				g.appendChild(mk("path", { d: "M 5 -2 l 2 5" }));
				svg.appendChild(g);
				const lt = mk("text", { x: cx, y: cy + 34, "text-anchor": "middle", "font-size": "9", "font-weight": "700", fill: isLight ? "#444" : "#e6ebf2" }); lt.textContent = "ЗАМОК"; svg.appendChild(lt);
			}
		}

		// подписи длин полок — кликабельные
		for (let i = 0; i < segs.length; i++) {
			const a = v[i], b = v[i + 1], mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, nx = -(b.y - a.y), ny = (b.x - a.x), nl = Math.hypot(nx, ny) || 1;
			const t = mk("text", { x: mx + nx / nl * 16, y: my + ny / nl * 16 + 4, "text-anchor": "middle", "font-size": "12", "font-weight": "600", fill: isLight ? "#222" : "#cdd7e3" }); t.style.cursor = "text"; t.textContent = segs[i].len;
			t.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); const sp = labelScreenPos(t); openEdit("len", i, sp.x, sp.y, segs[i].len); }); svg.appendChild(t);
		}
		// углы между полками — кликабельные; подпись выносится НАРУЖУ по биссектрисе (не наезжает на профиль)
		for (let i = 1; i < segs.length; i++) {
			if (Math.abs(bendAngle(i)) < 1) continue; const p = v[i], a = v[i - 1], b = v[i + 1];
			let t1x = a.x - p.x, t1y = a.y - p.y; const l1 = Math.hypot(t1x, t1y) || 1; t1x /= l1; t1y /= l1;
			let t2x = b.x - p.x, t2y = b.y - p.y; const l2 = Math.hypot(t2x, t2y) || 1; t2x /= l2; t2y /= l2;
			let bx = t1x + t2x, by = t1y + t2y; const bl = Math.hypot(bx, by);
			let ox, oy; if (bl < 0.15) { ox = -t2y; oy = t2x; } else { ox = -bx / bl; oy = -by / bl; } // наружу от внутренней биссектрисы
			const lx = p.x + ox * 20, ly = p.y + oy * 20 + 3.5;
			svg.appendChild(mk("circle", { cx: p.x, cy: p.y, r: "11", fill: "#3ed0b8", opacity: "0.14" }));
			const t = mk("text", { x: lx, y: ly, "text-anchor": "middle", "font-size": "10.5", "font-weight": "700", fill: "#3ed0b8" }); t.style.cursor = "text"; t.textContent = Math.round(flangeAngle(i)) + "°";
			t.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); const sp = labelScreenPos(t); openEdit("bend", i, sp.x, sp.y, Math.round(flangeAngle(i))); }); svg.appendChild(t);
		}
		// вершины
		v.forEach((p, i) => {
			const hov = (i === hoverIdx);
			if (hov) svg.appendChild(mk("circle", { cx: p.x, cy: p.y, r: "10", fill: "#5b8def", opacity: "0.25" }));
			const c = mk("circle", { cx: p.x, cy: p.y, r: hov ? (i === 0 ? 6 : 5.5) : (i === 0 ? 3 : 2.3), fill: i === 0 ? "#5b8def" : (hov ? "#26334a" : "#1a1f29"), stroke: i === 0 ? "#9bbcff" : (hov ? "#5b8def" : "#7e8da0"), "stroke-width": hov ? "2.4" : "1.4" }); c.style.cursor = "grab"; svg.appendChild(c);
		});
	}

	function buildSegList() {
		G("db_segCount").textContent = segs.length;
		const list = G("db_segList");
		if (segs.length === 0) { list.innerHTML = '<div class="empty">Профиль пуст — нарисуй его на холсте слева</div>'; return; }
		let html = "";
		for (let i = 0; i < segs.length; i++) {
			html += `<div class="seg"><div class="seg-tag">${i + 1}</div><div><label>Длина полки, мм</label><input type="number" data-len="${i}" value="${segs[i].len}"></div><div><label>Направление, °</label><input type="number" data-dir="${i}" value="${Math.round(segs[i].dir)}"></div><button class="del" data-del="${i}" title="Удалить полку">×</button></div>`;
			if (i < segs.length - 1) html += `<div class="angle-row">↳ гиб ${i + 1}: <input type="number" data-bend="${i + 1}" value="${Math.round(flangeAngle(i + 1))}"> ° <span style="color:var(--muted)">(угол между полками)</span></div>`;
		}
		list.innerHTML = html;
	}

	function updateResults() {
		const polki = segs.reduce((s, x) => s + x.len, 0);
		const hemCount = (hemLeft ? 1 : 0) + (hemRight ? 1 : 0), hem = hemCount * hemLen, dev = polki + hem;
		const thick = parseFloat(G("db_thick").value), len = parseFloat(G("db_len").value) || 0, qty = parseInt(G("db_qty").value) || 0, coil = parseFloat(G("db_coil").value) || 0;
		G("db_dev").textContent = dev > 0 ? dev + " мм" : "— мм";
		G("db_devNote").textContent = hem > 0 ? `(полки ${polki} + завальцовка ${hem})` : "";
		G("db_count").textContent = segs.length + " / " + (Math.max(0, segs.length - 1) + hemCount + (lockOn ? 2 : 0)); // завальцовка = гиб; замок = +2 гиба
		if (dev > 0 && len > 0) { const area = (dev / 1000) * (len / 1000), w1 = area * massPerSqm(thick); G("db_area").textContent = area.toFixed(3) + " м²"; G("db_w1").textContent = w1.toFixed(2) + " кг"; G("db_wall").textContent = (w1 * qty).toFixed(2) + " кг"; }
		else { G("db_area").textContent = "— м²"; G("db_w1").textContent = "— кг"; G("db_wall").textContent = "— кг"; }
		G("db_coilEcho").textContent = coil;
		G("db_strips").textContent = (dev > 0 && coil > 0) ? Math.floor(coil / dev) + " полос/лист, отход " + (coil - Math.floor(coil / dev) * dev) + " мм" : "—";
	}

	// ── события панели полок ──
	G("db_segList").addEventListener("input", (e) => {
		const t = e.target;
		if (t.dataset.len != null) { segs[+t.dataset.len].len = Math.max(1, parseFloat(t.value) || 0); renderLight(); }
		else if (t.dataset.dir != null) { segs[+t.dataset.dir].dir = parseFloat(t.value) || 0; renderLight(); }
		else if (t.dataset.bend != null) { applyFlangeAngle(+t.dataset.bend, parseFloat(t.value) || 0); renderLight(); }
	});
	G("db_segList").addEventListener("change", () => render());
	G("db_segList").addEventListener("click", (e) => { if (e.target.dataset.del != null) { segs.splice(+e.target.dataset.del, 1); render(); } });
	["db_thick", "db_len", "db_qty", "db_coil"].forEach((id) => G(id).addEventListener("input", updateResults));
	G("db_thick").addEventListener("change", drawCanvas);
	G("db_color").addEventListener("change", () => { drawCanvas(); updateResults(); });

	// ── рисование / перетаскивание ──
	function nearestVertex(pv) { const dv = verts().map(D); let best = -1, bd = GRAB; dv.forEach((q, i) => { const d = Math.hypot(q.x - pv.x, q.y - pv.y); if (d < bd) { bd = d; best = i; } }); return best; }
	let dragAbs = null;
	svg.addEventListener("pointerdown", (e) => { const pv = svgPt(e); const hit = started ? nearestVertex(pv) : -1; if (hit >= 0) { dragIdx = hit; dragAbs = verts(); svg.setPointerCapture(e.pointerId); } else if (!started) { const w = Dinv(pv); start = { x: snap(w.x), y: snap(w.y) }; started = true; render(); } else { const w = Dinv(pv); addPoint({ x: snap(w.x), y: snap(w.y) }); } });
	svg.addEventListener("pointermove", (e) => {
		const pv = svgPt(e);
		if (dragIdx < 0) { const h = started ? nearestVertex(pv) : -1; if (h !== hoverIdx) { hoverIdx = h; svg.style.cursor = h >= 0 ? "grab" : "crosshair"; drawCanvas(); } return; }
		const w = Dinv(pv), np = { x: snap(w.x), y: snap(w.y) }; dragAbs[dragIdx] = { x: np.x, y: np.y }; start = { x: dragAbs[0].x, y: dragAbs[0].y };
		for (let i = 0; i < segs.length; i++) { const a = dragAbs[i], b = dragAbs[i + 1], dx = b.x - a.x, dy = -(b.y - a.y); segs[i].len = Math.max(1, Math.round(Math.hypot(dx, dy))); segs[i].dir = Math.atan2(dy, dx) * 180 / Math.PI; }
		drawCanvas(); updateResults();
	});
	svg.addEventListener("pointerup", () => { dragIdx = -1; dragAbs = null; render(); });

	// ── кнопки ──
	G("db_undo").onclick = () => { segs.pop(); render(); };
	G("db_clear").onclick = () => { segs = []; start = { x: 180, y: 300 }; started = false; hoverIdx = -1; render(); };
	G("db_hemL").onclick = () => { hemLeft = !hemLeft; G("db_hemL").classList.toggle("on", hemLeft); render(); };
	G("db_hemR").onclick = () => { hemRight = !hemRight; G("db_hemR").classList.toggle("on", hemRight); render(); };
	G("db_hemLflip").onclick = () => { hemLeftDir *= -1; render(); };
	G("db_hemRflip").onclick = () => { hemRightDir *= -1; render(); };
	G("db_paintSide").onclick = () => { paintSide *= -1; render(); };
	const paintToggle = G("db_paintToggle");
	paintToggle.onclick = () => { paintOn = !paintOn; paintToggle.classList.toggle("on", paintOn); paintToggle.textContent = paintOn ? "🎨 вкл" : "🎨 выкл"; render(); };
	G("db_lock").onclick = () => { lockOn = !lockOn; G("db_lock").classList.toggle("on", lockOn); render(); };
	G("db_hemLen").addEventListener("input", (e) => { hemLen = Math.max(1, parseFloat(e.target.value) || 0); render(); });

	function snapshot() { return { start: { ...start }, segs: segs.map((s) => ({ ...s })), hemLeft, hemRight, hemLeftDir, hemRightDir, hemLen, lockOn, paintSide, paintOn, colorRaw: G("db_color").value }; }
	function loadSnap(s) {
		start = { ...s.start }; segs = s.segs.map((x) => ({ ...x })); started = true;
		hemLeft = !!s.hemLeft; hemRight = !!s.hemRight; hemLeftDir = s.hemLeftDir || 1; hemRightDir = s.hemRightDir || -1; hemLen = s.hemLen || 15; lockOn = !!s.lockOn; paintSide = s.paintSide || 1; paintOn = !!s.paintOn;
		if (s.colorRaw) G("db_color").value = s.colorRaw;
		G("db_hemL").classList.toggle("on", hemLeft); G("db_hemR").classList.toggle("on", hemRight); G("db_lock").classList.toggle("on", lockOn);
		paintToggle.classList.toggle("on", paintOn); paintToggle.textContent = paintOn ? "🎨 вкл" : "🎨 выкл";
		G("db_hemLen").value = hemLen;
		render();
	}

	// ── покрытия (Dobor Coating) ──
	frappe.call({ method: "metal_calculator.dobor.api.list_coatings", callback: (r) => {
		const opts = (r.message || []).map((c) => `<option value="${esc(c.coating_name)}|${esc(c.hex || "#b9c2cc")}">${esc(c.coating_name)}</option>`).join("");
		G("db_color").innerHTML = opts || '<option value="Цинк|#b9c2cc">Цинк</option>';
		// по умолчанию — Цинк
		const zinc = Array.from(G("db_color").options).find((o) => /цинк/i.test(o.textContent));
		if (zinc) G("db_color").value = zinc.value;
		drawCanvas();
	} });

	// ── шаблоны (Dobor Profile) ──
	let templates = [];
	function refreshTemplates(sel) {
		frappe.call({ method: "metal_calculator.dobor.api.list_templates", callback: (r) => {
			templates = r.message || [];
			G("db_tplSel").innerHTML = '<option value="">— выбрать шаблон —</option>' + templates.map((t, i) => `<option value="${i}">${esc(t.profile_name)}</option>`).join("");
			if (sel != null) G("db_tplSel").value = sel;
		} });
	}
	refreshTemplates();
	G("db_tplSel").addEventListener("change", () => {
		const i = G("db_tplSel").value; if (i === "") return; const t = templates[+i];
		let flanges = []; try { flanges = JSON.parse(t.flanges_json || "[]"); } catch (e) { flanges = []; }
		loadSnap({ start: { x: 180, y: 300 }, segs: flanges, hemLeft: t.hem_left, hemRight: t.hem_right, hemLeftDir: t.hem_left_dir, hemRightDir: t.hem_right_dir, hemLen: t.hem_len, lockOn: t.lock, paintSide: t.paint_side });
		alignMinBox();
	});
	G("db_tplAdd").onclick = () => {
		if (segs.length < 1) return; const name = (G("db_tplName").value || "").trim() || ("Шаблон " + (templates.length + 1));
		frappe.call({ method: "metal_calculator.dobor.api.save_template", args: { profile_name: name, snapshot: JSON.stringify(snapshot()) }, callback: () => { G("db_tplName").value = ""; refreshTemplates(); frappe.show_alert({ message: __("Шаблон сохранён"), indicator: "green" }); } });
	};
	G("db_tplDel").onclick = () => { const i = G("db_tplSel").value; if (i === "") return; frappe.call({ method: "metal_calculator.dobor.api.delete_template", args: { name: templates[+i].name }, callback: () => refreshTemplates() }); };

	// ── заказ доборок (Dobor Order): позиции копятся в памяти, сохраняются целиком ──
	let order = [];          // позиции текущего заказа (в памяти)
	let orderName = "";      // имя редактируемого Dobor Order ("" = новый)

	// расчёт чисел позиции на клиенте (тот же, что серверный compute — для превью)
	function itemCalc(snp, thick, plank, qty) {
		const polki = (snp.segs || []).reduce((s, x) => s + x.len, 0);
		const hemCount = (snp.hemLeft ? 1 : 0) + (snp.hemRight ? 1 : 0);
		const dev = polki + hemCount * (snp.hemLen || 0);
		const w1 = (dev / 1000) * (plank / 1000) * massPerSqm(thick);
		return { dev, w1, weight_total: w1 * qty };
	}

	function renderOrder() {
		G("db_savedCount").textContent = order.length;
		let qtySum = 0, wSum = 0;
		const box = G("db_savedList");
		if (!order.length) { box.innerHTML = '<div class="empty" style="padding:14px 0">Пусто — собери профиль и нажми «В заказ»</div>'; }
		else {
			box.innerHTML = order.map((s, i) => {
				const snp = s.snapshot || {};
				qtySum += s.qty; wSum += s.weight_total || 0;
				return `<div style="border:1px solid var(--line);background:rgba(127,127,127,.06);border-radius:8px;padding:8px 11px;margin-bottom:7px;display:flex;align-items:center;gap:10px">
					<div style="width:22px;height:22px;border-radius:6px;background:#c9701e;color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0">${i + 1}</div>
					<div style="flex:1;min-width:0">
						<div style="font-size:12.5px;font-weight:600;color:var(--ink)">${esc(s.title || "Доборка")}${snp.lockOn ? " · 🤝" : ""}</div>
						<div style="font-size:11px;color:var(--muted)">${esc(s.coating || "Цинк")} · ${s.thickness}мм · развёртка ${Math.round(s.developed_width)} · ${s.plank_length}мм · ${s.qty}шт · ${(s.weight_total || 0).toFixed(1)}кг${snp.hemLeft || snp.hemRight ? " · завальц." : ""}</div>
					</div>
					<button data-load="${i}" title="Открыть в конструкторе" style="padding:3px 8px;font-size:11px">✎</button>
					<button data-rem="${i}" title="Убрать из заказа" style="padding:3px 8px;font-size:11px;border-color:#7a3030;color:#ff8a8a;background:transparent">×</button>
				</div>`;
			}).join("");
		}
		G("db_ordQty").textContent = qtySum;
		G("db_ordW").textContent = wSum.toFixed(1);
	}

	// список существующих заказов
	let orders = [];
	function refreshOrders(sel) {
		frappe.call({ method: "metal_calculator.dobor.api.list_orders", callback: (r) => {
			orders = r.message || [];
			G("db_orderSel").innerHTML = '<option value="">— новый заказ —</option>' + orders.map((o) => `<option value="${esc(o.name)}">${esc(o.name)} · ${esc(o.customer || "без клиента")} (${o.total_positions || 0})</option>`).join("");
			if (sel != null) G("db_orderSel").value = sel;
		} });
	}
	refreshOrders();

	// «В заказ» — добавить текущую доборку в список (в памяти)
	G("db_save").onclick = () => {
		if (segs.length < 1) { frappe.show_alert({ message: __("Сначала нарисуй профиль"), indicator: "orange" }); return; }
		const snp = snapshot();
		const thick = parseFloat(G("db_thick").value), plank = parseFloat(G("db_len").value) || 2500, qty = parseInt(G("db_qty").value) || 1;
		const c = itemCalc(snp, thick, plank, qty);
		order.push({ title: (G("db_color").value || "").split("|")[0] + " доборка", coating: (G("db_color").value || "").split("|")[0], thickness: thick, plank_length: plank, qty, snapshot: snp, developed_width: c.dev, weight_total: c.weight_total });
		renderOrder();
		frappe.show_alert({ message: __("Добавлено в заказ"), indicator: "green" });
	};
	// «Новая доборка» — очистить холст (заказ не трогаем)
	G("db_new").onclick = () => { segs = []; start = { x: 180, y: 300 }; started = false; hoverIdx = -1; hemLeft = hemRight = lockOn = false; hemLeftDir = 1; hemRightDir = -1; G("db_hemL").classList.remove("on"); G("db_hemR").classList.remove("on"); G("db_lock").classList.remove("on"); render(); };

	// убрать позицию / открыть в конструкторе
	G("db_savedList").addEventListener("click", (e) => {
		const t = e.target;
		if (t.dataset.rem != null) { order.splice(+t.dataset.rem, 1); renderOrder(); }
		if (t.dataset.load != null) { const it = order[+t.dataset.load]; if (it && it.snapshot && it.snapshot.segs) { loadSnap(it.snapshot); G("db_thick").value = it.thickness; G("db_len").value = it.plank_length; G("db_qty").value = it.qty; updateResults(); } }
	});

	// «Сохранить заказ» — записать весь Dobor Order
	G("db_orderSave").onclick = () => {
		if (!order.length) { frappe.show_alert({ message: __("Заказ пуст"), indicator: "orange" }); return; }
		const items = order.map((s) => ({ title: s.title, coating: s.coating, thickness: s.thickness, plank_length: s.plank_length, qty: s.qty, snapshot: JSON.stringify(s.snapshot) }));
		frappe.call({ method: "metal_calculator.dobor.api.save_order", args: { items: JSON.stringify(items), customer: G("db_customer").value || null, order_name: orderName || null }, callback: (r) => {
			if (r.message) { orderName = r.message.name; frappe.show_alert({ message: __("Заказ {0} сохранён ({1} кг)", [r.message.name, (r.message.total_weight || 0).toFixed(1)]), indicator: "green" }); refreshOrders(orderName); }
		} });
	};
	// «Печать листа» — производственный лист PDF по сохранённому заказу
	G("db_orderPrint").onclick = () => {
		if (!orderName) { frappe.show_alert({ message: __("Сначала сохрани заказ"), indicator: "orange" }); return; }
		window.open("/api/method/metal_calculator.dobor.report.render_pdf?order_name=" + encodeURIComponent(orderName), "_blank");
	};
	// «Новый» — очистить заказ
	G("db_orderNew").onclick = () => { order = []; orderName = ""; G("db_customer").value = ""; G("db_orderSel").value = ""; renderOrder(); };

	// выбор существующего заказа → загрузить позиции
	G("db_orderSel").addEventListener("change", () => {
		const name = G("db_orderSel").value;
		if (!name) { G("db_orderNew").onclick(); return; }
		frappe.call({ method: "metal_calculator.dobor.api.get_order", args: { name }, callback: (r) => {
			const o = r.message; if (!o) return;
			orderName = o.name; G("db_customer").value = o.customer || "";
			order = (o.items || []).map((it) => { let snp = {}; try { snp = JSON.parse(it.profile_snapshot_json || "{}"); } catch (e) {} return { title: it.title, coating: it.coating, thickness: it.thickness, plank_length: it.plank_length, qty: it.qty, snapshot: snp, developed_width: it.developed_width, weight_total: it.weight_total }; });
			renderOrder();
		} });
	});

	renderOrder();
	render();
}
