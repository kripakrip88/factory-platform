# -*- coding: utf-8 -*-
"""Правила в.2 — развёртки и размеры деталей опор по чертежам И. Бутова (27.10.2026).

Одно место для всех формул: генераторы чертежей (draw_*.py) и проверка (test_v2.py) берут размеры
только отсюда. Здесь нет рисования и нет Odoo — только math. Таблицы ОСТ (h, B, S, B1, M, …)
сюда приходят аргументами (их загружает drawings.py из pmk_opora/tools).

Источник правил — ~/Projects/opory_ost36-146/razvertki_2710/RULES.md: по одному набору правил
сходятся все 19 развёрток Игоря (8 полухомутов, 9 корпусов КХ/КП, 2 корпуса ОПП1) до 0,001 мм.

Открытые вопросы к Игорю (RULES.md, раздел 6) вынесены константами ниже: поменял константу —
перестроились все чертежи. Тексты допущений для чертежей — функция assumptions().
"""
import math

RULES = "v2"
RULES_TITLE = "Правила в.2 (по чертежам И. Бутова)"

# ─── Открытые вопросы: одна правка — все чертежи ─────────────────────────
H_TO = "pipe"          # КХ, h из табл. 5: "pipe" — до низа трубы (так у Игоря), "clamp" — до низа хомута (ОСТ). Вопрос 1
KP_H1 = "ost"          # КП, высота стенки: "ost" — табл. 4, "contact" — по касанию трубы вниз до мм. Вопрос 8
K = 0.4                # нейтральный слой на гибах корпуса и лапок хомута (КОМПАС по умолчанию). Вопрос 3
K_CLAMP = 0.4          # нейтральный слой на дуге хомута (при 0,5 хомут 219 длиннее на 2,7 мм). Вопрос 3
CORPUS_R = 1.5         # внутренний радиус гиба корпуса = 1,5·S (радиус «в» табл. 4 Игорь не берёт). Вопрос 2
LUG_R = 1.0            # внутренний радиус гиба лапки хомута = 1·S. Вопрос 2
RIB_CLEARANCE = 3.0    # КХ: ребро ниже хомута по оси трубы, мм (у Игоря 2–5, у 219 касание). Вопрос 4
RIB_CLEARANCE_KP = 0.0  # КП: дуга ребра концентрична трубе и касается её (КП 57 Игоря)
RIB_CHAMFER_ADD = 2    # фаска нижних углов ребра = S + 2
RIB_OFFSET = 1.0       # ребро стоит на RIB_OFFSET·S от торца корпуса (занимает S…2S)
RIB_WIDTH_GAP = {50: 1, 80: 1, 200: 3, 300: 4}   # ребро уже внутренней ширины B − 2S на столько, мм. Вопрос 5
RIB_WIDTH_GAP_OTHER = 4    # B = 500 (КП Дн 1020–1420) у Игоря нет — взято как у B 300
OPP1_RIB_GAP = 3       # ОПП1: ребро 91 при L − 2S = 94
OPP1_RIB_HOLES = False  # ОПП1: 2 отв. Ø10 в ребре (п. 5 ОСТ, по требованию заказчика) — у Игоря нет. Вопрос 7
ANGLES_MAX_B = 80      # B ≤ 80 — корпус из двух уголков, шов по оси дна. Вопрос 6
MARK_LEN = 10          # риска гиба — 10 мм от кромки (слой BEND), отступ 1 мм
MARK_GAP = 10          # разметка ребра прерывается на ±10 мм от оси гиба

# Табл. 15 ОСТ 36-146-88, f — расстояние от оси трубы до лапки полухомута (в pmk_opora/tools нет).
CLAMP_F = {57: 4, 76: 4, 89: 6, 108: 6, 133: 8, 159: 8, 219: 10, 273: 10, 325: 10, 377: 10, 426: 10,
           530: 12, 630: 12}

# ОПП1 (ОСТ 36-94-83, черт. 1): толщина, длина вдоль трубы, ширина низа стенки и дна.
OPP1_S, OPP1_L, OPP1_W0 = 3, 100, 70
OPP1_HOLE_D, OPP1_HOLE_Y, OPP1_HOLE_X = 10, 20, 25

DENSITY = 7.85e-6      # кг/мм³


# ─── Общие формулы ───────────────────────────────────────────────────────
def bend(angle_deg, r, s, k=None):
    """Длина зоны гиба по нейтральному слою: α·(r + K·S)."""
    return math.radians(angle_deg) * (r + (K if k is None else k) * s)


def corpus(B, h1, S, angles_allowed=True):
    """Корпус-«П» (КП, КХ, ОПП1): дно B (наружное), стенки h1, гибы 90° внутренним радиусом 1,5·S.
    L = 2·(h1 − 2,5S) + (B − 5S) + 2·(π/2)(1,5S + 0,4S). При B ≤ 80 — два уголка, шов по оси дна."""
    r = CORPUS_R * S
    wall = h1 - (r + S)
    bottom = B - 2 * (r + S)
    z = bend(90, r, S)
    total = 2 * wall + 2 * z + bottom
    return dict(r=r, wall=wall, bottom=bottom, zone=z, total=total,
                angles=bool(angles_allowed and B <= ANGLES_MAX_B),
                angle=wall + z + bottom / 2.0,          # развёртка одного уголка
                bend_mark=wall + z / 2.0)               # ось гиба (риска) от торца стенки


def wall_contact(axis, radius, B, S):
    """Высота точки, где окружность radius (центр на axis) касается внутренних кромок стенок."""
    half = B / 2.0 - S
    return axis - math.sqrt(radius * radius - half * half)


def clamp(dn, S, f, B1, M, k_arc=None):
    """Полухомут: дуга по трубе (внутр. R = Дн/2), лапки на f от оси, гиб лапки r = S.
    a = asin((f + 2S)/(R + 2S)); xc = √((R + 2S)² − (f + 2S)²);
    L = 2·(B1/2 − xc) + 2·(90° − a)·1,4S + (180° − 2a)(R + 0,4S); отверстия (B1 − M)/2 от торца."""
    R = dn / 2.0
    r = LUG_R * S
    rA = r + S
    a = math.asin((f + rA) / (R + rA))
    xc = math.sqrt((R + rA) ** 2 - (f + rA) ** 2)
    arc = (math.pi - 2 * a) * (R + (K_CLAMP if k_arc is None else k_arc) * S)
    z = (math.pi / 2 - a) * (r + K * S)
    flat = B1 / 2.0 - xc
    return dict(R=R, Ro=R + S, S=S, f=f, r=r, a=math.degrees(a), xc=xc, arc=arc, zone=z, flat=flat,
                total=2 * flat + 2 * z + arc, hole=(B1 - M) / 2.0, bend_mark=flat + z / 2.0, B1=B1, M=M)


def rib_width(B, S):
    return B - 2 * S - RIB_WIDTH_GAP.get(B, RIB_WIDTH_GAP_OTHER)


def rib_chamfer(S):
    return S + RIB_CHAMFER_ADD


def segment_area(r, d):
    """Площадь кругового сегмента, отсечённого хордой на расстоянии d от центра."""
    return r * r * math.acos(d / r) - d * math.sqrt(r * r - d * d)


def end_rib(B, S, h1, center, radius):
    """Торцевое ребро: стоит на дне (низ на S), ширина B − 2S − зазор, фаски S + 2,
    верх — дуга radius с центром на высоте center (от низа корпуса), не выше стенки.
    Высоты возвращаются и от низа корпуса (*_abs), и от низа ребра (для DXF)."""
    w = rib_width(B, S)
    ch = rib_chamfer(S)
    if radius <= w / 2.0:
        raise ValueError("дуга ребра R%s уже ребра %s" % (radius, w))
    d = math.sqrt(radius * radius - (w / 2.0) ** 2)     # центр — хорда по верхним углам
    edge_abs = min(center - d, h1)
    mid_abs = center - radius
    edge, mid, cy = edge_abs - S, mid_abs - S, center - S
    area = w * edge - ch * ch - segment_area(radius, cy - edge) if radius > abs(cy - edge) else w * edge - ch * ch
    return dict(w=w, ch=ch, R=radius, center_abs=center, cy=cy, edge=edge, mid=mid, edge_abs=edge_abs,
                mid_abs=mid_abs, offset=RIB_OFFSET * S, area=area, clipped=center - d > h1)


def sheet_mass(area_mm2, s):
    return round(area_mm2 * s * DENSITY, 3)


# ─── КХ А12 (ОСТ 36-146-88, черт. 5) ─────────────────────────────────────
def kx(dn, h, B, S, L, cs, m, B1, M, d, f, bolt_d, bolt_l, bolt_kg=0.0, nut_kg=0.0, h_to=None):
    """Размеры КХ по правилам в.2. h — табл. 5 (по H_TO — до низа трубы или хомута)."""
    h_to = h_to or H_TO
    R = dn / 2.0
    Ro = R + cs
    axis = h + R + (cs if h_to == "clamp" else 0)       # ось трубы над основанием
    h1 = math.floor(wall_contact(axis, Ro, B, S) + 1e-9)
    c = corpus(B, h1, S)
    cl = clamp(dn, cs, f, B1, M)
    rib = end_rib(B, S, h1, axis - RIB_CLEARANCE, Ro)
    axis_contact = h1 + math.sqrt(Ro * Ro - (B / 2.0 - S) ** 2)  # хомут лёг на кромки стенок
    parts = [
        dict(key="corpus", pos="1", S=S, qty=2 if c["angles"] else 1,
             unit_mass=sheet_mass((c["angle"] if c["angles"] else c["total"]) * L, S)),
        dict(key="rib", pos="2", S=S, qty=2, unit_mass=sheet_mass(rib["area"], S)),
        dict(key="clamp", pos="3", S=cs, qty=4, unit_mass=sheet_mass(cl["total"] * m - 2 * math.pi * d * d / 4.0, cs)),
        dict(key="bolt", pos="4", S=0, qty=4, unit_mass=bolt_kg),
        dict(key="nut", pos="5", S=0, qty=4, unit_mass=nut_kg),
    ]
    mass = round(sum(p["qty"] * p["unit_mass"] for p in parts), 2)
    return dict(kind="kx", dn=dn, h=h, h_to=h_to, B=B, S=S, L=L, R=R, Ro=Ro, axis=axis, axis_contact=axis_contact,
                h1=h1, corpus=c, clamp=dict(cl, m=m, d=d), rib=rib, bolt=dict(d=bolt_d, l=bolt_l),
                pipe_bottom=axis - R, clamp_bottom=axis - Ro, parts=parts, mass=mass)


# ─── КП А12 (ОСТ 36-146-88, черт. 3) ─────────────────────────────────────
def kp(dn, h, h1_ost, B, S, L, h1_mode=None):
    """Размеры КП по правилам в.2. h — табл. 4, до низа трубы."""
    h1_mode = h1_mode or KP_H1
    R = dn / 2.0
    axis = h + R
    h1_contact = math.floor(wall_contact(axis, R, B, S) + 1e-9)
    h1 = h1_ost if h1_mode == "ost" else h1_contact
    c = corpus(B, h1, S)
    rib = end_rib(B, S, h1, axis - RIB_CLEARANCE_KP, R)
    parts = [
        dict(key="corpus", pos="1", S=S, qty=2 if c["angles"] else 1,
             unit_mass=sheet_mass((c["angle"] if c["angles"] else c["total"]) * L, S)),
        dict(key="rib", pos="2", S=S, qty=2, unit_mass=sheet_mass(rib["area"], S)),
    ]
    mass = round(sum(p["qty"] * p["unit_mass"] for p in parts), 2)
    return dict(kind="kp", dn=dn, h=h, B=B, S=S, L=L, R=R, axis=axis, h1=h1, h1_ost=h1_ost, h1_contact=h1_contact,
                h1_mode=h1_mode, corpus=c, rib=rib, pipe_bottom=axis - R, parts=parts, mass=mass)


# ─── ОПП1 (ОСТ 36-94-83, черт. 1) ────────────────────────────────────────
def opp1(dn, H, H1, H2, B, R):
    """ОПП1: корпус «П» вдоль трубы (дно 100 × 70), стенки-трапеции 70 → B только на прямом участке
    стенки (h1 − 2,5S), в зоне гиба и на дне ширина 70; ложе R на торце глубиной H1 − H."""
    S, L, W0 = OPP1_S, OPP1_L, OPP1_W0
    c = corpus(L, H1, S, angles_allowed=False)
    depth = H1 - H
    chord = 2 * math.sqrt(R * R - (R - depth) ** 2)
    rib_l = L - 2 * S - OPP1_RIB_GAP
    rib_h = H2 - S
    ch = rib_chamfer(S)
    holes = [(OPP1_HOLE_X - S - OPP1_RIB_GAP / 2.0, OPP1_HOLE_Y - S),
             (L - OPP1_HOLE_X - S - OPP1_RIB_GAP / 2.0, OPP1_HOLE_Y - S)] if OPP1_RIB_HOLES else []
    corpus_area = (c["total"] * W0 - 2 * (W0 - B) * c["wall"] / 2.0 - 2 * segment_area(R, R - depth))
    rib_area = rib_l * rib_h - ch * ch - len(holes) * math.pi * OPP1_HOLE_D ** 2 / 4.0
    parts = [dict(key="corpus", pos="1", S=S, qty=1, unit_mass=sheet_mass(corpus_area, S)),
             dict(key="rib", pos="2", S=S, qty=1, unit_mass=sheet_mass(rib_area, S))]
    mass = round(sum(p["qty"] * p["unit_mass"] for p in parts), 2)
    return dict(kind="opp1", dn=dn, H=H, H1=H1, H2=H2, B=B, R=R, S=S, L=L, W0=W0, corpus=c, depth=depth,
                chord=chord, saddle_center=H + R, pipe_axis=H + dn / 2.0,
                rib=dict(l=rib_l, h=rib_h, ch=ch, holes=holes, hole_d=OPP1_HOLE_D, gap=OPP1_RIB_GAP / 2.0),
                parts=parts, mass=mass)


def opp1_half_width(geo, s):
    """Полуширина развёртки корпуса ОПП1 в точке s от левого торца: на прямом участке стенки —
    трапеция от B (торец) до 70 (начало гиба), дальше 70."""
    c, total = geo["corpus"], geo["corpus"]["total"]
    t = min(s, total - s)
    if t >= c["wall"]:
        return geo["W0"] / 2.0
    return (geo["B"] + (geo["W0"] - geo["B"]) * t / c["wall"]) / 2.0


# ─── Допущения — в технические требования и в отчёт ──────────────────────
def assumptions(kind):
    """Открытые вопросы, которые стоят на чертеже текстом (зависят от констант выше)."""
    out = []
    if kind == "kx":
        out.append("h по табл. 5 отсчитана до низа %s; высота стенки — по касанию хомута, вниз до целого мм "
                   "(ждёт подтверждения Игоря)." % ("трубы, как у Игоря (по ОСТ — до низа хомута)"
                                                   if H_TO == "pipe" else "хомута, как в ОСТ"))
        out.append("Ребро ниже хомута на %s мм по оси трубы (у Игоря 2–5 мм, у Дн 219 касание); дуга ребра — "
                   "наружный радиус хомута (у Дн 630 Игоря R302,8)." % fmt(RIB_CLEARANCE))
        out.append("Нейтральный слой K = %s на всех гибах, в т. ч. на дуге хомута (K = %s); пробным гибом не сверено."
                   % (fmt(K), fmt(K_CLAMP)))
        out.append("Гиб лапки хомута внутренним радиусом %sS; развёртка хомута по формуле, а не по табл. 15 ОСТ."
                   % fmt(LUG_R))
    if kind == "kp":
        out.append("Высота стенки — %s; дуга ребра R = Дн/2 касается трубы." %
                   ("по табл. 4 ОСТ" if KP_H1 == "ost" else "по касанию трубы, вниз до целого мм"))
    if kind in ("kx", "kp"):
        out.append("Радиус гиба корпуса %sS (а не «в» табл. 4); ширина ребра — B − 2S минус 1/3/4 мм "
                   "(B 50–80 / 200 / 300), B 500 — как у 300." % fmt(CORPUS_R))
        out.append("При B ≤ %s корпус из двух уголков, шов по оси дна." % ANGLES_MAX_B)
    if kind == "opp1":
        out.append("Радиус гиба корпуса %sS; стенка сужается только на прямом участке." % fmt(CORPUS_R))
        out.append("Ребро %s отверстий Ø%s (п. 5 ОСТ — по требованию заказчика)." %
                   (("с 2", OPP1_HOLE_D) if OPP1_RIB_HOLES else ("без", OPP1_HOLE_D)))
    return out


def fmt(v, nd=3):
    """Число по-русски без лишних нулей: 1.5 → «1,5», 3.0 → «3»."""
    s = ("%." + str(nd) + "f") % v
    s = s.rstrip("0").rstrip(".") if "." in s else s
    return s.replace(".", ",")
