// Доборные элементы — конструктор сечения. Порт утверждённого прототипа в Frappe Page.
// Геометрия/рисование — как в прототипе; данные (шаблоны/покрытия/заказ) — в DocTypes через API.

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
		--ink:#e6ebf2;--muted:#8a97a8;--faint:#5b6675;--accent:#5b8def;--accent-soft:#1e3050;--bend:#3ed0b8;--grid:#1f2632;
		color:var(--ink);font-size:13px}
	.dobor-wrap .layout{display:grid;grid-template-columns:1fr 360px;gap:16px}
	@media(max-width:920px){.dobor-wrap .layout{grid-template-columns:1fr}}
	.dobor-wrap .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
	.dobor-wrap .panel-head{padding:10px 14px;border-bottom:1px solid var(--line);background:var(--bg2);font-size:12px;font-weight:650;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);display:flex;justify-content:space-between;align-items:center}
	.dobor-wrap .canvas-wrap{position:relative;background:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:20px 20px;background-color:#161b24}
	.dobor-wrap svg#dcanvas{display:block;width:100%;height:440px;touch-action:none;cursor:crosshair}
	.dobor-wrap .toolbar{display:flex;gap:6px;padding:10px 14px;border-bottom:1px solid var(--line);flex-wrap:wrap;align-items:center;background:var(--bg2)}
	.dobor-wrap button{font-family:inherit;font-size:12.5px;border:1px solid var(--line2);background:var(--panel2);color:var(--ink);padding:6px 12px;border-radius:7px;cursor:pointer;font-weight:550;transition:all .12s}
	.dobor-wrap button:hover{border-color:var(--accent);background:#28323f}
	.dobor-wrap button.on{background:var(--accent);color:#fff;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
	.dobor-wrap button.ghost{color:var(--muted);background:transparent}
	.dobor-wrap button.danger:hover{border-color:#ff5a6e;color:#ff5a6e;background:#3a1f24}
	.dobor-wrap .hint{font-size:11.5px;color:var(--muted);padding:8px 14px;background:var(--bg2);border-top:1px solid var(--line)}
	.dobor-wrap .seg-list{padding:6px 0;max-height:230px;overflow-y:auto}
	.dobor-wrap .seg{display:grid;grid-template-columns:22px 1fr 1fr 26px;gap:8px;align-items:center;padding:6px 14px;font-size:12.5px}
	.dobor-wrap .seg + .seg{border-top:1px solid var(--line)}
	.dobor-wrap .seg-tag{width:22px;height:22px;border-radius:6px;background:var(--accent);color:#fff;font-size:11px;font-weight:650;display:flex;align-items:center;justify-content:center}
	.dobor-wrap .seg label{font-size:10px;color:var(--muted);display:block;margin-bottom:1px;text-transform:uppercase}
	.dobor-wrap .seg input{width:100%;font-family:inherit;font-size:12.5px;border:1px solid var(--line2);background:var(--bg2);border-radius:5px;padding:3px 6px;color:var(--ink)}
	.dobor-wrap .seg input:focus{outline:none;border-color:var(--accent)}
	.dobor-wrap .seg .del{background:none;border:none;color:var(--faint);cursor:pointer;font-size:15px;padding:0}
	.dobor-wrap .angle-row{padding:6px 14px;font-size:12px;color:var(--bend);display:flex;align-items:center;gap:8px;background:#14211f}
	.dobor-wrap .angle-row input{width:64px;font-size:12px;border:1px solid #1f4a43;border-radius:5px;padding:2px 6px;color:var(--bend);background:#0f1a18}
	.dobor-wrap .res-row{display:flex;justify-content:space-between;align-items:baseline;padding:9px 14px;font-size:13px}
	.dobor-wrap .res-row + .res-row{border-top:1px solid var(--line)}
	.dobor-wrap .res-row .k{color:var(--muted)}
	.dobor-wrap .res-row .v{font-weight:650;font-variant-numeric:tabular-nums;color:var(--ink)}
	.dobor-wrap .res-row.big .v{font-size:18px;color:var(--accent)}
	.dobor-wrap .res-row.big{background:var(--accent-soft)}
	.dobor-wrap .inputs{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:10px 14px;border-top:1px solid var(--line)}
	.dobor-wrap .field label{font-size:10px;color:var(--muted);text-transform:uppercase;display:block;margin-bottom:2px}
	.dobor-wrap .field input,.dobor-wrap .field select{width:100%;font-size:12.5px;border:1px solid var(--line2);background:var(--bg2);border-radius:6px;padding:5px 7px;color:var(--ink)}
	.dobor-wrap .empty{padding:24px 14px;text-align:center;color:var(--faint);font-size:12.5px}
	.dobor-wrap .preset-bar{display:flex;gap:6px;padding:8px 14px;border-top:1px solid var(--line);flex-wrap:wrap;background:var(--bg2);align-items:center}
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
      <button id="d_undo" class="ghost">↶ Отменить точку</button>
      <button id="d_clear" class="ghost danger">Очистить</button>
      <span style="flex:1"></span>
      <span style="font-size:11.5px;color:var(--muted)">наведи на точку — тащи; клик по полю — новая полка</span>
    </div>
    <div class="canvas-wrap"><svg id="dcanvas" viewBox="0 0 760 440"></svg></div>
    <div class="hint">Кликай по полю — добавляется полка. Наведи на точку — тащи. Клик по числу на чертеже — правка размера.</div>
    <div class="preset-bar" style="border-top:1px solid var(--line)">
      <span style="font-size:11px;color:var(--muted)">Завальцовка:</span>
      <button id="d_hemL">◧ Слева</button><button id="d_hemLflip" title="Перевернуть">⮃</button>
      <button id="d_hemR">◨ Справа</button><button id="d_hemRflip" title="Перевернуть">⮃</button>
      <span style="font-size:11.5px;color:var(--muted)">длина</span>
      <input id="d_hemLen" type="number" value="15" min="1" style="width:56px;border:1px solid var(--line);border-radius:6px;padding:4px 6px;background:var(--bg2);color:var(--ink)">
      <span style="font-size:11.5px;color:var(--muted)">мм</span><span style="flex:1"></span>
      <span style="font-size:11px;color:var(--muted)">Краска:</span>
      <button id="d_paint">🎨 Сменить сторону</button><button id="d_lock">🔒 Замок</button>
    </div>
    <div class="preset-bar">
      <span style="font-size:11px;color:var(--muted)">Шаблон:</span>
      <select id="d_tplSel" style="border:1px solid var(--line2);background:var(--bg2);color:var(--ink);border-radius:7px;padding:5px 8px;min-width:200px"><option value="">— выбрать шаблон —</option></select>
      <input id="d_tplName" type="text" placeholder="имя нового шаблона" style="border:1px solid var(--line2);background:var(--bg2);color:var(--ink);border-radius:7px;padding:5px 8px;width:150px">
      <button id="d_tplAdd" title="Сохранить как шаблон">＋ В шаблоны</button>
      <button id="d_tplDel" class="ghost" title="Удалить шаблон">🗑</button>
    </div>
    <div class="panel" style="margin-top:14px">
      <div class="panel-head">Расчёт</div>
      <div class="results">
        <div class="res-row big"><span class="k">Развёртка (ширина заготовки)<br><span style="font-size:10.5px;color:var(--muted);font-weight:400" id="d_devNote"></span></span><span class="v" id="d_dev">— мм</span></div>
        <div class="res-row"><span class="k">Полок / гибов</span><span class="v" id="d_count">0 / 0</span></div>
        <div class="res-row"><span class="k">Площадь 1 планки</span><span class="v" id="d_area">— м²</span></div>
        <div class="res-row"><span class="k">Вес 1 планки</span><span class="v" id="d_w1">— кг</span></div>
        <div class="res-row"><span class="k">Вес всего</span><span class="v" id="d_wall">— кг</span></div>
      </div>
      <div class="inputs">
        <div class="field"><label>Толщина, мм</label><select id="d_thick"><option>0.45</option><option selected>0.5</option><option>0.55</option><option>0.7</option><option>1</option></select></div>
        <div class="field"><label>Цвет / покрытие</label><select id="d_color"></select></div>
        <div class="field"><label>Длина планки, мм</label><input id="d_len" type="number" value="2500" min="1"></div>
        <div class="field"><label>Количество, шт</label><input id="d_qty" type="number" value="1" min="1"></div>
        <div class="field"><label>Ширина рулона/листа, мм</label><input id="d_coil" type="number" value="1250" min="1"></div>
      </div>
      <div class="res-row" style="border-top:1px solid var(--line)"><span class="k">Полос из ширины <span id="d_coilEcho">1250</span></span><span class="v" id="d_strips">—</span></div>
    </div>
  </div>
  <div>
    <div class="panel" style="margin-bottom:14px">
      <div class="panel-head"><span>Полки и гибы</span><span id="d_segCount">0</span></div>
      <div id="d_segList" class="seg-list"><div class="empty">Профиль пуст — нарисуй его на холсте слева</div></div>
    </div>
    <div class="panel">
      <div style="padding:10px 14px;background:var(--bg2);display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line)">
        <button id="d_save" style="border-color:#2f9e6e;color:#5fe0a8;background:#15281f;font-weight:600">💾 Сохранить в заказ</button>
        <button id="d_new" style="border-color:#2f9e6e;color:#5fe0a8;background:#15281f;font-weight:600">＋ Новая доборка</button>
      </div>
      <div class="panel-head"><span>Доборки в заказе</span><span id="d_savedCount" style="color:#ff9a4d">0</span></div>
      <div id="d_savedList" style="padding:8px 14px 12px"><div class="empty" style="padding:14px 0">Пока пусто — собери профиль и нажми «Сохранить в заказ»</div></div>
    </div>
  </div>
</div></div>`;

function init_dobor(page) {
	const SVGNS = "http://www.w3.org/2000/svg";
	const G = (id) => document.getElementById(id);
	const svg = G("dcanvas");
	const canvasWrap = document.querySelector(".dobor-wrap .canvas-wrap");

	let start = { x: 180, y: 300 }, segs = [], started = false;
	let hemLeft = false, hemRight = false, hemLeftDir = 1, hemRightDir = -1, hemLen = 15;
	let paintSide = 1, lockOn = false, dragIdx = -1, hoverIdx = -1;
	const GRAB = 14;
	const massPerSqm = (t) => t * 7.85;

	function verts() {
		const v = [{ x: start.x, y: start.y }]; let cur = { ...start };
		for (const s of segs) { const r = s.dir * Math.PI / 180; cur = { x: cur.x + s.len * Math.cos(r), y: cur.y - s.len * Math.sin(r) }; v.push({ x: cur.x, y: cur.y }); }
		return v;
	}
	function bendAngle(i) { let d = segs[i].dir - segs[i - 1].dir; while (d > 180) d -= 360; while (d < -180) d += 360; return d; }
	function svgPt(e) { const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY; const ctm = svg.getScreenCTM(); if (!ctm) return { x: 0, y: 0 }; const inv = pt.matrixTransform(ctm.inverse()); return { x: inv.x, y: inv.y }; }
	const snap = (v) => Math.round(v / 10) * 10;
	function addPoint(p) { const v = verts(); const last = v[v.length - 1]; const dx = p.x - last.x, dy = -(p.y - last.y); const len = Math.round(Math.hypot(dx, dy)); if (len < 5) return; let dir = Math.round(Math.atan2(dy, dx) * 180 / Math.PI); segs.push({ len, dir }); render(); }

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

	let editKind = null, editIdx = -1;
	const inlineEdit = document.createElement("input");
	inlineEdit.type = "number";
	inlineEdit.style.cssText = "position:absolute;display:none;width:62px;font-size:12px;padding:3px 5px;border:1.5px solid #5b8def;border-radius:6px;background:#1a1f29;color:#e6ebf2;z-index:20";
	canvasWrap.appendChild(inlineEdit);
	function openEdit(kind, idx, sx, sy, val) { editKind = kind; editIdx = idx; inlineEdit.value = val; inlineEdit.style.left = (sx - 31) + "px"; inlineEdit.style.top = (sy - 12) + "px"; inlineEdit.style.display = "block"; setTimeout(() => { inlineEdit.focus(); inlineEdit.select(); }, 0); }
	function applyEdit() { if (editKind == null) return; if (editKind === "len") { segs[editIdx].len = Math.max(1, parseFloat(inlineEdit.value) || segs[editIdx].len); } else if (editKind === "bend") { const want = parseFloat(inlineEdit.value) || 0; const delta = want - bendAngle(editIdx); for (let k = editIdx; k < segs.length; k++) segs[k].dir += delta; } inlineEdit.style.display = "none"; editKind = null; render(); }
	inlineEdit.addEventListener("keydown", (e) => { if (e.key === "Enter") applyEdit(); if (e.key === "Escape") { inlineEdit.style.display = "none"; editKind = null; } });
	inlineEdit.addEventListener("blur", applyEdit);
	function labelScreenPos(el) { const r = el.getBoundingClientRect(), wr = canvasWrap.getBoundingClientRect(); return { x: r.left - wr.left + r.width / 2, y: r.top - wr.top + r.height / 2 }; }

	function render() { drawCanvas(); buildSegList(); updateResults(); }
	function renderLight() { drawCanvas(); updateResults(); }

	function mk(tag, attrs) { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }

	function drawCanvas() {
		if (dragIdx < 0) computeFit();
		while (svg.firstChild) svg.removeChild(svg.firstChild);
		const v = verts().map(D);
		if (v.length >= 2) {
			const colorRaw = (G("d_color") || {}).value || "Цинк|#b9c2cc";
			const paintHex = colorRaw.split("|")[1] || "#ff6a8a";
			const off = v.map((p, i) => { let nx = 0, ny = 0; if (i < v.length - 1) { const dx = v[i + 1].x - p.x, dy = v[i + 1].y - p.y, l = Math.hypot(dx, dy) || 1; nx += -dy / l; ny += dx / l; } if (i > 0) { const dx = p.x - v[i - 1].x, dy = p.y - v[i - 1].y, l = Math.hypot(dx, dy) || 1; nx += -dy / l; ny += dx / l; } const l = Math.hypot(nx, ny) || 1; return (p.x + nx / l * 5 * paintSide) + "," + (p.y + ny / l * 5 * paintSide); }).join(" ");
			svg.appendChild(mk("polyline", { points: off, fill: "none", stroke: paintHex, "stroke-width": "3", "stroke-dasharray": "5 4", "stroke-linejoin": "round", opacity: "0.95" }));
			const HALF = 1.3, FOLDGAP = 6, norms = [], dirs = [];
			for (let i = 0; i < segs.length; i++) { const a = v[i], b = v[i + 1]; let dx = b.x - a.x, dy = b.y - a.y; const l = Math.hypot(dx, dy) || 1; norms.push({ x: -dy / l, y: dx / l }); dirs.push({ x: dx / l, y: dy / l }); }
			const isFold = (i) => i >= 1 && i < segs.length && Math.abs(bendAngle(i)) > 150;
			function offV(i, side) {
				const hasP = i > 0, hasN = i < segs.length;
				if (hasP && hasN) {
					if (isFold(i)) { const n = norms[i - 1], tipx = v[i].x + dirs[i - 1].x * FOLDGAP, tipy = v[i].y + dirs[i - 1].y * FOLDGAP; return { x: tipx + side * n.x * (HALF + FOLDGAP * 0.6), y: tipy + side * n.y * (HALF + FOLDGAP * 0.6) }; }
					let mx = norms[i - 1].x + norms[i].x, my = norms[i - 1].y + norms[i].y; const ml = Math.hypot(mx, my); if (ml < 0.2) return { x: v[i].x + side * norms[i].x * HALF, y: v[i].y + side * norms[i].y * HALF }; mx /= ml; my /= ml; let sc = HALF / Math.max(0.34, (mx * norms[i].x + my * norms[i].y)); sc = Math.min(sc, HALF * 3.5); return { x: v[i].x + side * mx * sc, y: v[i].y + side * my * sc };
				} else if (hasN) return { x: v[i].x + side * norms[i].x * HALF, y: v[i].y + side * norms[i].y * HALF };
				else return { x: v[i].x + side * norms[i - 1].x * HALF, y: v[i].y + side * norms[i - 1].y * HALF };
			}
			const left = [], right = []; for (let i = 0; i < v.length; i++) { left.push(offV(i, 1)); right.push(offV(i, -1)); }
			let d = "M " + left.map((p) => p.x + " " + p.y).join(" L ") + " L " + right.slice().reverse().map((p) => p.x + " " + p.y).join(" L ") + " Z";
			svg.appendChild(mk("path", { d, fill: "#46566b", stroke: "#9fb0c4", "stroke-width": "1", "stroke-linejoin": "round" }));
			for (let i = 1; i < segs.length; i++) {
				if (!isFold(i)) continue; const tipx = v[i].x + dirs[i - 1].x * FOLDGAP, tipy = v[i].y + dirs[i - 1].y * FOLDGAP, n = norms[i - 1];
				const a = { x: tipx + n.x * (HALF + FOLDGAP * 0.6), y: tipy + n.y * (HALF + FOLDGAP * 0.6) }, b = { x: tipx - n.x * (HALF + FOLDGAP * 0.6), y: tipy - n.y * (HALF + FOLDGAP * 0.6) };
				svg.appendChild(mk("path", { d: `M ${a.x} ${a.y} Q ${tipx + dirs[i - 1].x * FOLDGAP * 0.9} ${tipy + dirs[i - 1].y * FOLDGAP * 0.9} ${b.x} ${b.y}`, fill: "none", stroke: "#7fd4ff", "stroke-width": "2", "stroke-linecap": "round", opacity: "0.9" }));
				const lt = mk("text", { x: tipx + dirs[i - 1].x * 12, y: tipy + dirs[i - 1].y * 12 + 3, "text-anchor": "middle", "font-size": "9", "font-weight": "700", fill: "#7fd4ff" }); lt.textContent = "подгиб 180°"; svg.appendChild(lt);
			}
			function drawHem(edgeV, u, flip) {
				const nx = -u.y * flip, ny = u.x * flip, L = 14, gap = 4.5, sx = edgeV.x, sy = edgeV.y, bx = sx + nx * gap, by = sy + ny * gap, ex = bx + u.x * L, ey = by + u.y * L, sweep = flip > 0 ? 1 : 0;
				svg.appendChild(mk("path", { d: `M ${sx} ${sy} A ${gap / 1.5} ${gap / 1.5} 0 0 ${sweep} ${bx} ${by} L ${ex} ${ey}`, fill: "none", stroke: "#ffac4d", "stroke-width": (2 * HALF).toFixed(1), "stroke-linecap": "round", "stroke-linejoin": "round" }));
				svg.appendChild(mk("circle", { cx: sx, cy: sy, r: "3", fill: "#ffac4d" }));
				const t = mk("text", { x: (bx + ex) / 2 + nx * 11, y: (by + ey) / 2 + ny * 11 + 3, "text-anchor": "middle", "font-size": "10", "font-weight": "700", fill: "#ffc278" }); t.textContent = "завальц. " + hemLen; svg.appendChild(t);
			}
			const unit = (a, b) => { const dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy) || 1; return { x: dx / l, y: dy / l }; };
			if (hemLeft && segs.length >= 1) drawHem(v[0], unit(v[0], v[1]), hemLeftDir);
			if (hemRight && segs.length >= 1) drawHem(v[v.length - 1], unit(v[v.length - 1], v[v.length - 2]), hemRightDir);
			if (lockOn && segs.length >= 1) {
				const a = v[0], b = v[1], dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy) || 1, ux = dx / l, uy = dy / l, nx = -uy, ny = ux, cx = a.x - ux * 26 + nx * 4, cy = a.y - uy * 26 + ny * 4;
				svg.appendChild(mk("rect", { x: cx - 13, y: cy - 14, width: "26", height: "26", rx: "6", fill: "#ffffff", stroke: "#1a1f29", "stroke-width": "1.4" }));
				svg.appendChild(mk("path", { d: `M ${cx - 4} ${cy - 3} v -3 a 4 4 0 0 1 8 0 v 3`, fill: "none", stroke: "#111", "stroke-width": "1.6" }));
				svg.appendChild(mk("rect", { x: cx - 6, y: cy - 3, width: "12", height: "9", rx: "1.5", fill: "#111" }));
				const lt = mk("text", { x: cx, y: cy - 18, "text-anchor": "middle", "font-size": "9", "font-weight": "700", fill: "#e6ebf2" }); lt.textContent = "ЗАМОК"; svg.appendChild(lt);
			}
		}
		for (let i = 0; i < segs.length; i++) {
			const a = v[i], b = v[i + 1], mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, nx = -(b.y - a.y), ny = (b.x - a.x), nl = Math.hypot(nx, ny) || 1;
			const t = mk("text", { x: mx + nx / nl * 16, y: my + ny / nl * 16 + 4, "text-anchor": "middle", "font-size": "12", "font-weight": "600", fill: "#cdd7e3" }); t.style.cursor = "text"; t.textContent = segs[i].len;
			t.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); const sp = labelScreenPos(t); openEdit("len", i, sp.x, sp.y, segs[i].len); }); svg.appendChild(t);
		}
		for (let i = 1; i < segs.length; i++) {
			const ba = bendAngle(i); if (Math.abs(ba) < 1) continue; const p = v[i];
			svg.appendChild(mk("circle", { cx: p.x, cy: p.y, r: "11", fill: "#3ed0b8", opacity: "0.14" }));
			const t = mk("text", { x: p.x, y: p.y - 15, "text-anchor": "middle", "font-size": "10.5", "font-weight": "700", fill: "#3ed0b8" }); t.style.cursor = "text"; t.textContent = Math.round(Math.abs(ba)) + "°";
			t.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); const sp = labelScreenPos(t); openEdit("bend", i, sp.x, sp.y, Math.round(bendAngle(i))); }); svg.appendChild(t);
		}
		v.forEach((p, i) => {
			const hov = (i === hoverIdx);
			if (hov) svg.appendChild(mk("circle", { cx: p.x, cy: p.y, r: "10", fill: "#5b8def", opacity: "0.25" }));
			const c = mk("circle", { cx: p.x, cy: p.y, r: hov ? (i === 0 ? 6 : 5.5) : (i === 0 ? 3 : 2.3), fill: i === 0 ? "#5b8def" : (hov ? "#26334a" : "#1a1f29"), stroke: i === 0 ? "#9bbcff" : (hov ? "#5b8def" : "#7e8da0"), "stroke-width": hov ? "2.4" : "1.4" }); c.style.cursor = "grab"; svg.appendChild(c);
		});
	}

	function buildSegList() {
		G("d_segCount").textContent = segs.length;
		const list = G("d_segList");
		if (segs.length === 0) { list.innerHTML = '<div class="empty">Профиль пуст — нарисуй его на холсте слева</div>'; return; }
		let html = "";
		for (let i = 0; i < segs.length; i++) {
			html += `<div class="seg"><div class="seg-tag">${i + 1}</div><div><label>Длина полки, мм</label><input type="number" data-len="${i}" value="${segs[i].len}"></div><div><label>Направление, °</label><input type="number" data-dir="${i}" value="${Math.round(segs[i].dir)}"></div><button class="del" data-del="${i}" title="Удалить">×</button></div>`;
			if (i < segs.length - 1) html += `<div class="angle-row">↳ гиб ${i + 1}: <input type="number" data-bend="${i + 1}" value="${Math.round(bendAngle(i + 1))}"> ° <span style="color:var(--muted)">(отклонение)</span></div>`;
		}
		list.innerHTML = html;
	}

	function updateResults() {
		const polki = segs.reduce((s, x) => s + x.len, 0);
		const hemCount = (hemLeft ? 1 : 0) + (hemRight ? 1 : 0), hem = hemCount * hemLen, dev = polki + hem;
		const thick = parseFloat(G("d_thick").value), len = parseFloat(G("d_len").value) || 0, qty = parseInt(G("d_qty").value) || 0, coil = parseFloat(G("d_coil").value) || 0;
		G("d_dev").textContent = dev > 0 ? dev + " мм" : "— мм";
		G("d_devNote").textContent = hem > 0 ? `(полки ${polki} + завальцовка ${hem})` : "";
		G("d_count").textContent = segs.length + " / " + (Math.max(0, segs.length - 1) + hemCount);
		if (dev > 0 && len > 0) { const area = (dev / 1000) * (len / 1000), w1 = area * massPerSqm(thick); G("d_area").textContent = area.toFixed(3) + " м²"; G("d_w1").textContent = w1.toFixed(2) + " кг"; G("d_wall").textContent = (w1 * qty).toFixed(2) + " кг"; }
		else { G("d_area").textContent = "— м²"; G("d_w1").textContent = "— кг"; G("d_wall").textContent = "— кг"; }
		G("d_coilEcho").textContent = coil;
		G("d_strips").textContent = (dev > 0 && coil > 0) ? Math.floor(coil / dev) + " полос/лист, отход " + (coil - Math.floor(coil / dev) * dev) + " мм" : "—";
	}

	// ── события сегментов ──
	G("d_segList").addEventListener("input", (e) => {
		const t = e.target;
		if (t.dataset.len != null) { segs[+t.dataset.len].len = Math.max(1, parseFloat(t.value) || 0); renderLight(); }
		else if (t.dataset.dir != null) { segs[+t.dataset.dir].dir = parseFloat(t.value) || 0; renderLight(); }
		else if (t.dataset.bend != null) { const i = +t.dataset.bend, want = parseFloat(t.value) || 0, delta = want - bendAngle(i); for (let k = i; k < segs.length; k++) segs[k].dir += delta; renderLight(); }
	});
	G("d_segList").addEventListener("change", () => render());
	G("d_segList").addEventListener("click", (e) => { if (e.target.dataset.del != null) { segs.splice(+e.target.dataset.del, 1); render(); } });
	["d_thick", "d_len", "d_qty", "d_coil"].forEach((id) => G(id).addEventListener("input", updateResults));
	G("d_thick").addEventListener("change", drawCanvas);
	G("d_color").addEventListener("change", () => { drawCanvas(); updateResults(); });

	// ── рисование/перетаскивание ──
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
	G("d_undo").onclick = () => { segs.pop(); render(); };
	G("d_clear").onclick = () => { segs = []; start = { x: 180, y: 300 }; started = false; hoverIdx = -1; render(); };
	G("d_hemL").onclick = () => { hemLeft = !hemLeft; G("d_hemL").classList.toggle("on", hemLeft); render(); };
	G("d_hemR").onclick = () => { hemRight = !hemRight; G("d_hemR").classList.toggle("on", hemRight); render(); };
	G("d_hemLflip").onclick = () => { hemLeftDir *= -1; render(); };
	G("d_hemRflip").onclick = () => { hemRightDir *= -1; render(); };
	G("d_paint").onclick = () => { paintSide *= -1; render(); };
	G("d_lock").onclick = () => { lockOn = !lockOn; G("d_lock").classList.toggle("on", lockOn); render(); };
	G("d_hemLen").addEventListener("input", (e) => { hemLen = Math.max(1, parseFloat(e.target.value) || 0); render(); });

	function snapshot() { return { start: { ...start }, segs: segs.map((s) => ({ ...s })), hemLeft, hemRight, hemLeftDir, hemRightDir, hemLen, lockOn, paintSide, colorRaw: G("d_color").value }; }
	function loadSnap(s) {
		start = { ...s.start }; segs = s.segs.map((x) => ({ ...x })); started = true;
		hemLeft = !!s.hemLeft; hemRight = !!s.hemRight; hemLeftDir = s.hemLeftDir || 1; hemRightDir = s.hemRightDir || -1; hemLen = s.hemLen || 15; lockOn = !!s.lockOn; paintSide = s.paintSide || 1;
		if (s.colorRaw) G("d_color").value = s.colorRaw;
		G("d_hemL").classList.toggle("on", hemLeft); G("d_hemR").classList.toggle("on", hemRight); G("d_lock").classList.toggle("on", lockOn); G("d_hemLen").value = hemLen;
		render();
	}

	// ── покрытия ──
	frappe.call({ method: "metal_calculator.dobor.api.list_coatings", callback: (r) => {
		const opts = (r.message || []).map((c) => `<option value="${frappe.utils.escape_html(c.coating_name)}|${frappe.utils.escape_html(c.hex || "#b9c2cc")}">${frappe.utils.escape_html(c.coating_name)}</option>`).join("");
		G("d_color").innerHTML = opts || '<option value="Цинк|#b9c2cc">Цинк</option>';
		drawCanvas();
	} });

	// ── шаблоны (Dobor Profile) ──
	let templates = [];
	function refreshTemplates(sel) {
		frappe.call({ method: "metal_calculator.dobor.api.list_templates", callback: (r) => {
			templates = r.message || [];
			G("d_tplSel").innerHTML = '<option value="">— выбрать шаблон —</option>' + templates.map((t, i) => `<option value="${i}">${frappe.utils.escape_html(t.profile_name)}</option>`).join("");
			if (sel != null) G("d_tplSel").value = sel;
		} });
	}
	refreshTemplates();
	G("d_tplSel").addEventListener("change", () => {
		const i = G("d_tplSel").value; if (i === "") return; const t = templates[+i];
		let flanges = []; try { flanges = JSON.parse(t.flanges_json || "[]"); } catch (e) { flanges = []; }
		loadSnap({ start: { x: 180, y: 300 }, segs: flanges, hemLeft: t.hem_left, hemRight: t.hem_right, hemLeftDir: t.hem_left_dir, hemRightDir: t.hem_right_dir, hemLen: t.hem_len, lockOn: t.lock, paintSide: t.paint_side });
	});
	G("d_tplAdd").onclick = () => {
		if (segs.length < 1) return; const name = (G("d_tplName").value || "").trim() || ("Шаблон " + (templates.length + 1));
		frappe.call({ method: "metal_calculator.dobor.api.save_template", args: { profile_name: name, snapshot: JSON.stringify(snapshot()) }, callback: () => { G("d_tplName").value = ""; refreshTemplates(); frappe.show_alert({ message: __("Шаблон сохранён"), indicator: "green" }); } });
	};
	G("d_tplDel").onclick = () => { const i = G("d_tplSel").value; if (i === "") return; frappe.call({ method: "metal_calculator.dobor.api.delete_template", args: { name: templates[+i].name }, callback: () => refreshTemplates() }); };

	// ── доборки в заказе (Dobor Order Item) ──
	let saved = [];
	function renderSaved() {
		G("d_savedCount").textContent = saved.length;
		const box = G("d_savedList");
		if (!saved.length) { box.innerHTML = '<div class="empty" style="padding:14px 0">Пока пусто — собери профиль и нажми «Сохранить в заказ»</div>'; return; }
		box.innerHTML = saved.map((s, i) => {
			let snap = {}; try { snap = JSON.parse(s.profile_snapshot_json || "{}"); } catch (e) {}
			const hex = (snap.colorRaw || "|#b9c2cc").split("|")[1] || "#b9c2cc";
			return `<div style="border:1px solid #c9701e;background:#241a10;border-radius:8px;padding:8px 11px;margin-bottom:7px;display:flex;align-items:center;gap:10px">
				<div style="width:22px;height:22px;border-radius:6px;background:#c9701e;color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0">${i + 1}</div>
				<div style="flex:1;min-width:0">
					<div style="font-size:12.5px;font-weight:600;color:#e6ebf2;display:flex;align-items:center;gap:6px"><span style="width:11px;height:11px;border-radius:3px;flex-shrink:0;border:1px solid rgba(255,255,255,.25);background:${hex}"></span>${frappe.utils.escape_html(s.title || "Доборка")}${snap.lockOn ? " · 🔒" : ""}</div>
					<div style="font-size:11px;color:#8a97a8">${frappe.utils.escape_html(s.coating || "Цинк")} · ${s.thickness}мм · развёртка ${s.developed_width} · ${s.plank_length}мм · ${s.qty}шт · ${(s.weight_total || 0).toFixed(1)}кг</div>
				</div>
				<button data-load="${i}" title="Открыть" style="padding:3px 8px;font-size:11px">✎</button>
				<button data-rem="${i}" title="Удалить" style="padding:3px 8px;font-size:11px;border-color:#7a3030;color:#ff8a8a;background:transparent">×</button>
			</div>`;
		}).join("");
	}
	function refreshSaved() { frappe.call({ method: "metal_calculator.dobor.api.list_order_items", callback: (r) => { saved = r.message || []; renderSaved(); } }); }
	refreshSaved();
	G("d_save").onclick = () => {
		if (segs.length < 1) return;
		const coatingName = (G("d_color").value || "").split("|")[0];
		frappe.call({ method: "metal_calculator.dobor.api.save_order_item", args: { snapshot: JSON.stringify(snapshot()), thickness: G("d_thick").value, plank_length: G("d_len").value, qty: G("d_qty").value, coating: coatingName }, callback: (r) => { if (r.message) { frappe.show_alert({ message: __("В заказ: {0} ({1} кг)", [r.message.name, r.message.weight_total]), indicator: "green" }); refreshSaved(); } } });
	};
	G("d_new").onclick = () => { segs = []; start = { x: 180, y: 300 }; started = false; hoverIdx = -1; hemLeft = hemRight = lockOn = false; hemLeftDir = 1; hemRightDir = -1; G("d_hemL").classList.remove("on"); G("d_hemR").classList.remove("on"); G("d_lock").classList.remove("on"); render(); };
	G("d_savedList").addEventListener("click", (e) => {
		const t = e.target;
		if (t.dataset.rem != null) { frappe.call({ method: "metal_calculator.dobor.api.delete_order_item", args: { name: saved[+t.dataset.rem].name }, callback: () => refreshSaved() }); }
		if (t.dataset.load != null) { let snap = {}; try { snap = JSON.parse(saved[+t.dataset.load].profile_snapshot_json || "{}"); } catch (e2) {} if (snap.segs) loadSnap(snap); }
	});

	render();
}
