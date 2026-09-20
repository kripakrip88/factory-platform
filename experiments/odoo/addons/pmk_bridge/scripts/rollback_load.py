# -*- coding: utf-8 -*-
"""Откат заливки моста: вернуть базу в то состояние, в котором её застали.

ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ, А НЕ «ВОССТАНОВИТЬ ИЗ ДАМПА». Дамп откатывает базу
целиком, вместе с работой, которую за это время сделали люди. На стенде это
уже стоило бы спецификации СМ-00023 на 9660,440 кг: она заведена ПОСЛЕ того,
как был снят дамп /opt/backups/odoo/odoo_20260920_102418.dump. Откат должен
снимать заливку, а не время.

ЧТО ЗАЛИВКА ДЕЛАЕТ С БАЗОЙ — две разные вещи, и снимаются они по-разному.

  1. ЗАВОДИТ СВОЁ: 752 карточки, 25 категорий, 2 характеристики, 11 значений.
     У каждой такой записи есть внешний идентификатор модуля pmk_bridge —
     по нему она и опознаётся. Замер на копии старого дампа: 790 строк в
     ir_model_data, ровно 752+25+2+11.

  2. ПЕРЕПИСЫВАЕТ ЧУЖОЕ: коды на 17 стандартных единицах Odoo (принадлежат
     модулю uom), точность «Stock Weight» 2 -> 5 знаков (запись модуля
     product), removal_strategy_id у существующей категории «Металлопрокат»,
     имя/категорию/единицу/артикул у существующих карточек, и УДАЛЯЕТ
     строку-дубль из справочника листа (57 -> 56).
     Своих следов мост на этих записях не оставляет. Опознать их после
     заливки невозможно: строка выглядит так, будто её такой и завели.

Отсюда устройство отката: созданное он сносит по внешним идентификаторам, а
чужое возвращает ПО СНИМКУ, который scripts/prepare_environment.py (шаг 0)
снимает ДО первой правки. Без снимка откат неполон, и это не мнение: без
него после «отката» у семнадцати единиц Odoo остаются коды, которых до
заливки не было, а у карточки «Труба профильная 100x100x3» — чужое имя.

ПОРЯДОК ДЕЙСТВИЙ — НЕ ПЕРЕСТАВЛЯТЬ, ЗАМЕРЕНО.

  * Сначала характеристики снимаются с ТОВАРОВ, и только потом удаляются
    значения. Иначе Odoo отказывает дословно:
        You cannot delete the value Марка стали: Ст3сп because it is used on
        the following products: [TPK-100x100x3] ..., [UGR-63x63x5] ...
    (замер: 8 значений марки, каждое стоит на 721 строке товаров).

  * Снимать характеристику с товара, по которому прошли движения, надо
    ПРАВИЛОМ ОДНОГО ЗНАЧЕНИЯ НАОБОРОТ: сузить строку до значения, которое
    носит живой вариант, и только потом удалить строку. Замер на карточке
    TPK-100x100x3 (3621,790 м, 15 движений):

        как есть:            вариант 9  active=True  код=TPK-100x100x3  склад 3621,790
        снести строку разом: вариант 9  active=FALSE код=TPK-100x100x3  склад 3621,790
                             вариант 778 active=True код=нет            склад 0,000
        сузить, потом снять: вариант 9  active=True  код=TPK-100x100x3  склад 3621,790

    То есть «снести разом» отправляет в архив вариант с остатком и заводит
    вместо него пустой. Товар при этом выглядит живым, а 3621,790 м лежат на
    архивном варианте и не видны ни в остатках, ни в подборе.

  * Товары удаляются раньше категорий и раньше значений характеристик.
    Про значения Odoo отказывает явно (сообщение выше). Про категории —
    НЕ отказывает: замер показал, что unlink категории с товарами проходит
    молча и обнуляет у товара обязательное поле categ_id. Значит порядок
    здесь держится не на отказе Odoo, а на нашем знании о нём.

  * Чужое возвращается РАНЬШЕ, чем удаляется своё. Удаление наших категорий
    при усыновлённой карточке внутри не падает — оно МОЛЧА обнуляет у неё
    обязательное поле категории (замер в docstring шага 4: 753 карточки из
    753 остались без категории). Возврат карточки в её прежнюю категорию
    убирает и эту ловушку.

ЧЕГО ЭТОТ ОТКАТ НЕ УМЕЕТ, И ЭТО НАДО ЗНАТЬ ЗАРАНЕЕ. Он возвращает то, что
описано снимком. Если загрузчик начнёт править чужую запись в таблице, о
которой снимок не знает, откат её не вернёт — он лишь заметит чужую модель
среди своих внешних идентификаторов и закричит. Список таблиц снимка и
порядок его расширения — в prepare_environment.py, раздел «ДОГОВОР С
ЗАГРУЗЧИКОМ».

КАК ЗАПУСКАТЬ (после prepare_environment.py и load_products.py, на той же копии):

    docker exec -u root odoo-app sh -c 'cat /tmp/pmk_rb/scripts/rollback_load.py |
        odoo shell -d odoo_rollback --no-http -c /etc/odoo/odoo.conf
        --db_host=db --db_user=$USER --db_password=$PASSWORD'

Повторный прогон безопасен: второй раз возвращать уже нечего, и скрипт это
печатает, а не делает вид, что поработал.
"""

import json
import os
import sys

# ─── ПРЕДОХРАНИТЕЛЬ ───────────────────────────────────────────────────────
# Откат удаляет 752 карточки и переписывает чужие записи. На живой базе он не
# запускается: имя базы задаётся ключом -d, а odoo.conf держит db_name = odoo,
# так что ошибиться ключом легко. Умереть надо ДО первой записи.
# Список тот же, что у prepare_environment.py, и живой базы в нём нет.
PROBE_DBS = ("odoo_probe", "odoo_rehearsal", "odoo_rollback", "odoo_rollback_adopt")
if env.cr.dbname not in PROBE_DBS:  # noqa: F821 — env приходит из odoo shell
    sys.exit("ОТКАЗ: откат пишет в базу, а подключились к %r вместо одной из %s"
             % (env.cr.dbname, ", ".join(PROBE_DBS)))  # noqa: F821

MODULE = "pmk_bridge"
SNAPSHOT_PARAM = "pmk_bridge.rollback_snapshot"
# Имя файла несёт имя базы: копий несколько, а /tmp у контейнера один.
# Общее имя уже приводило к тому, что снимок одной копии ложился поверх
# снимка другой (см. тот же комментарий в prepare_environment.py).
SNAPSHOT_FILE = (os.environ.get("PMK_BRIDGE_SNAPSHOT")
                 or "/tmp/pmk_bridge_snapshot_%s.json" % env.cr.dbname)  # noqa: F821
SEP = "─" * 78

# Модели, под которые мост заводит СВОИ записи, в порядке удаления.
# Порядок не косметика: товар держит и категорию, и значение характеристики,
# поэтому товары уходят первыми, значения — после них, характеристика —
# после значений, категории — последними.
OWNED_ORDER = (
    "product.template",
    "product.attribute.value",
    "product.attribute",
    "product.category",
)

# Разделы снимка, в которых лежат чужие записи, и модель Odoo для каждого —
# нужна, чтобы отличить «эта запись была до заливки» от «эту завели мы».
SECTION_MODEL = {
    "единицы": "uom.uom",
    "точность": "decimal.precision",
    "категории": "product.category",
    "товары": "product.template",
    "варианты": "product.product",
    "характеристики": "product.attribute",
    "значения_характеристик": "product.attribute.value",
    "строки_характеристик": "product.template.attribute.line",
    "лист_справочника": "pmk.metal.sheet",
}

# Типы, которые снимок хранит текстом (prepare_environment приводит их к
# тексту при снятии). Здесь тот же список, и он обязан совпадать: по нему
# строится и выражение чтения, и приведение при записи. jsonb — чтобы не
# потерять ключи переводов, numeric — чтобы не потерять знаки после запятой,
# timestamp — чтобы не зависеть от часового пояса сессии.
TEXTUAL_TYPES = ("jsonb", "numeric", "timestamp")

ОШИБКИ = []


def head(n, title):
    print("\n" + SEP)
    print("ШАГ %s. %s" % (n, title))
    print(SEP)


def отказ(text):
    """Остановиться ДО первой записи. Полуоткат хуже, чем отсутствие отката."""
    sys.exit("\nОТКАЗ: %s" % text)


def column_types(table):
    """Типы колонок таблицы — из базы, а не из памяти.

    Нужны в двух местах: чтобы прочитать текущее значение ровно тем же
    выражением, каким его снимали, и чтобы вернуть текст обратно в jsonb или
    numeric, а не положить строку в числовое поле.
    """
    env.cr.execute(  # noqa: F821
        "SELECT column_name, udt_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s", (table,))
    return dict(env.cr.fetchall())  # noqa: F821


def read_expr(col, udt):
    """Выражение чтения колонки — такое же, каким снимали снимок."""
    return "%s::text" % col if udt in TEXTUAL_TYPES else col


# ═══ ШАГ 1 ════════════════════════════════════════════════════════════════
def load_snapshot():
    """Достать снимок: сначала из параметра базы, потом из файла.

    Параметр — источник правды: он лежит в той же базе, которую описывает, и
    разойтись с ней не может. Файл — второй экземпляр на случай, когда
    параметр уже удалён предыдущим прогоном отката, и место, куда загрузчик
    дописывает свои дополнения (договор — в prepare_environment.py).
    """
    head(1, "Снимок исходного состояния")
    Param = env["ir.config_parameter"].sudo()  # noqa: F821
    raw = Param.get_param(SNAPSHOT_PARAM)
    source = "параметр %s" % SNAPSHOT_PARAM
    if not raw and os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE, encoding="utf-8") as fp:
            raw = fp.read()
        source = "файл %s" % SNAPSHOT_FILE

    env.cr.execute("SELECT count(*) FROM ir_model_data WHERE module=%s", (MODULE,))  # noqa: F821
    traces = env.cr.fetchone()[0]  # noqa: F821

    if not raw:
        if traces == 0:
            print("  снимка нет, записей моста в базе тоже нет — откатывать нечего.")
            print("  Это нормальный конец: база уже чистая.")
            sys.exit(0)
        отказ(
            "снимка нет, а записей моста в базе %d.\n"
            "Вернуть чужие записи не по чему: какими были коды единиц, точность\n"
            "веса и имена существующих карточек ДО заливки, в базе больше не\n"
            "написано нигде. Снимок берёт prepare_environment.py (шаг 0) ДО\n"
            "первой правки. Единственный честный путь отсюда — поднять копию\n"
            "заново из дампа." % traces)

    snap = json.loads(raw)
    print("  источник: %s" % source)
    print("  снят %s на базе %r, версия %s"
          % (snap.get("снят"), snap.get("база"), snap.get("версия")))
    if snap.get("база") != env.cr.dbname:  # noqa: F821
        # Снимок от ЧУЖОЙ базы применять нельзя ни при каких обстоятельствах:
        # id в разных базах свои, и «восстановление» переписало бы строки,
        # которые никто не трогал. Но и падать не всегда правильно: если
        # следов моста нет, откатывать просто нечего.
        if traces == 0:
            print("  снимок от другой базы, а следов моста здесь нет — "
                  "откатывать нечего.")
            sys.exit(0)
        отказ("снимок снят на базе %r, а откатываем %r, и следов моста здесь %d.\n"
              "Это разные базы: их id не совпадают, и «восстановление» переписало\n"
              "бы строки, которых заливка не касалась. Нужен снимок ЭТОЙ базы —\n"
              "он лежит в её параметре %s."
              % (snap.get("база"), env.cr.dbname, traces, SNAPSHOT_PARAM))  # noqa: F821

    # Дополнения загрузчика: он мог дописать в файл разделы про таблицы,
    # которых в снимке подготовки нет (договор в prepare_environment.py).
    if os.path.exists(SNAPSHOT_FILE) and source.startswith("параметр"):
        try:
            with open(SNAPSHOT_FILE, encoding="utf-8") as fp:
                extra = json.load(fp).get("дополнения_загрузчика") or {}
        except (OSError, ValueError) as exc:
            extra = {}
            print("  файл снимка не прочитан (%s) — работаем по параметру" % exc)
        if extra:
            snap["разделы"].update(extra)
            print("  подмешаны дополнения загрузчика: %s" % ", ".join(sorted(extra)))

    print("  записей моста в базе сейчас: %d" % traces)
    for key, sec in sorted(snap["разделы"].items()):
        print("      %-24s %-34s строк %d"
              % (key, sec["таблица"], len(sec["строки"])))
    return snap


# ═══ ШАГ 2 ════════════════════════════════════════════════════════════════
def build_plan(snap):
    """Посчитать, что будет снято и что возвращено. ДО первой записи.

    Все проверки, способные привести к отказу, стоят здесь. Откат, который
    падает на середине, оставляет базу в состоянии, которого не было ни до,
    ни после заливки, — и разбирать это состояние будет некому.
    """
    head(2, "План отката (пока ничего не пишем)")

    # Чужие id по моделям: всё, чего в этих множествах нет, завели мы.
    foreign = {}
    for key, sec in snap["разделы"].items():
        model = SECTION_MODEL.get(key)
        if not model:
            continue
        idx = sec["колонки"].index("id")
        foreign.setdefault(model, set()).update(r[idx] for r in sec["строки"])

    env.cr.execute(  # noqa: F821
        "SELECT model, array_agg(res_id ORDER BY res_id) FROM ir_model_data "
        "WHERE module=%s GROUP BY model", (MODULE,))
    ours = {model: list(ids) for model, ids in env.cr.fetchall()}  # noqa: F821

    unknown = sorted(set(ours) - set(OWNED_ORDER))
    # Модель из ir_model_data может не существовать в реестре — например, её
    # дал модуль, который с тех пор сняли. Тогда env[model] упал бы посреди
    # удаления, то есть ровно там, где падать нельзя. Ловим здесь.
    нет_в_реестре = [m for m in unknown if m not in env]  # noqa: F821
    if нет_в_реестре:
        отказ("в ir_model_data есть записи моста для моделей, которых нет в\n"
              "реестре Odoo: %s.\nУдалять их нечем, а оставить — значит оставить "
              "следы моста. Разбираться руками." % ", ".join(нет_в_реестре))
    if unknown:
        print("  ВНИМАНИЕ: мост завёл записи в моделях, которых нет в списке")
        print("  порядка удаления: %s." % ", ".join(unknown))
        print("  Их удалят ПЕРВЫМИ — как листья дерева ссылок. Если это не так,")
        print("  порядок в OWNED_ORDER надо дописать осознанно, а не на удачу.")
        print("  Ещё важнее: если эти записи попутно ПЕРЕПИСАЛИ чужое, снимок")
        print("  об этом не знает и откат этого не вернёт.")

    plan = {"foreign": foreign, "ours": {}, "unknown": unknown}
    for model in unknown + list(OWNED_ORDER):
        ids = [i for i in ours.get(model, []) if i not in foreign.get(model, set())]
        adopted = [i for i in ours.get(model, []) if i in foreign.get(model, set())]
        plan["ours"][model] = ids
        if ours.get(model):
            print("  %-26s наших %-4d усыновлённых (НЕ удалять) %d"
                  % (model, len(ids), len(adopted)))

    # Предохранитель: наш товар с движениями или остатком — это не наш товар.
    # Значит опознание разъехалось, и удалять нельзя ничего.
    tmpl_ids = plan["ours"].get("product.template") or []
    if tmpl_ids:
        env.cr.execute(  # noqa: F821
            "SELECT count(DISTINCT m.id), count(DISTINCT q.id) "
            "FROM product_product p "
            "LEFT JOIN stock_move m ON m.product_id=p.id "
            "LEFT JOIN stock_quant q ON q.product_id=p.id "
            "WHERE p.product_tmpl_id = ANY(%s)", (tmpl_ids,))
        moves, quants = env.cr.fetchone()  # noqa: F821
        print("  по нашим товарам движений %d, квантов %d" % (moves, quants))
        if moves or quants:
            отказ("на товарах, которые откат считает своими, есть %d движений и\n"
                  "%d квантов склада. Свои товары мост завёл пустыми — значит\n"
                  "опознание разъехалось, и удаление снесло бы историю склада.\n"
                  "Разбираться руками." % (moves, quants))

    # Чужие товары, на которых висят добавленные нами строки характеристик.
    old_lines = foreign.get("product.template.attribute.line", set())
    tmpl_foreign = sorted(foreign.get("product.template", set()))
    if tmpl_foreign:
        env.cr.execute(  # noqa: F821
            "SELECT product_tmpl_id, count(*) FROM product_template_attribute_line "
            "WHERE product_tmpl_id = ANY(%s) AND NOT (id = ANY(%s)) "
            "GROUP BY product_tmpl_id ORDER BY product_tmpl_id",
            (tmpl_foreign, sorted(old_lines) or [0]))
        rows = env.cr.fetchall()  # noqa: F821
        print("  чужих карточек всего %d, из них с нашими характеристиками %d"
              % (len(tmpl_foreign), len(rows)))
        for tid, cnt in rows:
            print("      карточка %-5s строк характеристик к снятию %d" % (tid, cnt))
    return plan


# ═══ ШАГ 3 ════════════════════════════════════════════════════════════════
def detach_attributes(snap, plan):
    """Снять наши характеристики с ЧУЖИХ карточек, не потеряв остаток.

    Правило одного значения наоборот (замер — в шапке файла): сузить строку
    до значения, которое носит живой вариант, и только потом её удалить.
    Тогда Odoo не считает вариант «невозможной комбинацией» и не отправляет
    его в архив вместе с остатком.
    """
    head(3, "Характеристики снимаются с чужих карточек")
    old_lines = plan["foreign"].get("product.template.attribute.line", set())
    tmpl_ids = sorted(plan["foreign"].get("product.template", set()))
    if not tmpl_ids:
        print("  чужих карточек в снимке нет — снимать не с чего.")
        return
    Tmpl = env["product.template"]  # noqa: F821

    def остатки(tmpl):
        """Что сейчас у карточки: вариант, метки, склад. Цифрами."""
        env.invalidate_all()  # noqa: F821
        out = []
        for v in tmpl.with_context(active_test=False).product_variant_ids:
            # Поля записи читаем ДО запроса, а не внутри сборки кортежа.
            # Обращение к полю может само сходить в базу (дочитать запись),
            # и тогда курсор отдаёт уже ДРУГОЙ результат: fetchone() вернёт
            # None, а строка упадёт на «NoneType is not subscriptable».
            # Проверено на этом самом месте.
            vid, active, code = v.id, v.active, v.default_code
            marks = ", ".join(v.product_template_attribute_value_ids.mapped("name")) or "нет"
            env.cr.execute(  # noqa: F821
                "SELECT COALESCE(SUM(quantity),0) FROM stock_quant WHERE product_id=%s "
                "AND location_id IN (SELECT id FROM stock_location WHERE usage='internal')",
                (vid,))
            out.append((vid, active, code, marks, float(env.cr.fetchone()[0])))  # noqa: F821
        return out

    def печать(prefix, rows):
        for vid, active, code, marks, qty in rows:
            print("      %s вариант %-5s active=%-5s код=%-16s метки=[%s] склад=%.3f"
                  % (prefix, vid, active, code or "нет", marks, qty))

    снято = 0
    for tmpl in Tmpl.browse(tmpl_ids).exists():
        ours = tmpl.attribute_line_ids.filtered(lambda l: l.id not in old_lines)
        if not ours:
            continue
        print("  карточка %s «%s»" % (tmpl.id, tmpl.name))
        было = остатки(tmpl)
        печать("до: ", было)

        # Шаг А. Сузить каждую строку до значений, которые реально носит
        # живой вариант. Активные варианты, а не все: архивный вариант метку
        # тоже носит, но защищать надо тот, что виден в остатках.
        живые = tmpl.product_variant_ids.product_template_attribute_value_ids
        for line in ours:
            keep = line.product_template_value_ids.filtered(lambda v: v.id in живые.ids)
            vals = keep.mapped("product_attribute_value_id")
            if not vals:
                print("      «%s»: живой вариант не носит ни одного значения этой "
                      "строки — сужать не к чему" % line.attribute_id.name)
                ОШИБКИ.append(
                    "карточка %s: строка «%s» снимается без сужения — проверьте "
                    "вариант вручную" % (tmpl.id, line.attribute_id.name))
                continue
            было_значений = len(line.value_ids)
            if set(vals.ids) != set(line.value_ids.ids):
                line.write({"value_ids": [(6, 0, vals.ids)]})
                print("      «%s»: %d значений -> %d (оставили то, что носит вариант)"
                      % (line.attribute_id.name, было_значений, len(vals)))

        # Шаг Б. Теперь строки можно снимать: комбинация варианта пустеет
        # ровно в тот момент, когда пустеет набор характеристик карточки.
        имена = ours.attribute_id.mapped("name")
        ours.unlink()
        снято += 1
        стало = остатки(tmpl)
        печать("после:", стало)

        # Сверка тут же, а не в конце: если вариант ушёл в архив, дальше идти
        # нельзя — следующая карточка потеряет остаток так же молча.
        было_по_id = {r[0]: r for r in было}
        for vid, active, code, marks, qty in стало:
            prev = было_по_id.get(vid)
            if prev is None:
                отказ("у карточки %s появился новый вариант %s — значит старый "
                      "признан невозможной комбинацией. Правило одного значения "
                      "наоборот не сработало." % (tmpl.id, vid))
            if prev[1] and not active:
                отказ("вариант %s карточки %s ушёл в архив вместе с остатком "
                      "%.3f. Это ровно та потеря, ради которой сужали строку."
                      % (vid, tmpl.id, qty))
            if abs(prev[4] - qty) > 1e-6:
                отказ("у варианта %s склад изменился с %.3f на %.3f — откат "
                      "характеристик не имеет права трогать остатки."
                      % (vid, prev[4], qty))
            if marks != "нет":
                ОШИБКИ.append("вариант %s: метки остались [%s]" % (vid, marks))
        print("      снято характеристик: %s" % ", ".join(имена))
    if not снято:
        print("  наших характеристик на чужих карточках нет — снимать нечего.")
    env.flush_all()  # noqa: F821


# ═══ ШАГ 4 ════════════════════════════════════════════════════════════════
def restore_foreign(snap):
    """Вернуть чужим записям их прежние значения — по снимку.

    ПОЧЕМУ ЭТОТ ШАГ РАНЬШЕ УДАЛЕНИЯ, а не после, как просится. Усыновлённые
    карточки после заливки лежат в НАШИХ категориях: карточка 9 переехала из
    категории 6 в 40, карточка 11 — в 44. Ожидание было, что Odoo не даст
    удалить категорию с товарами. ЗАМЕР ПОКАЗАЛ ОБРАТНОЕ, и это хуже отказа:

        внешний ключ product_template.categ_id -> product_category стоит
        confdeltype='n' (NO ACTION), но unlink() проходит БЕЗ ЕДИНОЙ ОШИБКИ,
        а categ_id обнуляется:

            до:    карточка 9 -> 40, 10 -> 34, 11 -> 44, 12 -> 44
            после: карточка 9 -> None, 10 -> None, 11 -> None, 12 -> None
            карточек с пустой категорией в базе: 753 из 753

    Поле categ_id обязательное, и товар без категории — это товар без способа
    учёта затрат и без счетов. То есть «удалить сначала своё» не падает, а
    молча ломает чужие карточки — ровно тот класс поломки, который замечают
    через неделю.

    Тот же замер с обратным порядком: вернули карточки в категорию 6, потом
    удалили наши 24 категории — у всех четырёх categ_id остался 6, пустых
    категорий 749 (это наши 748 карточек, которые тут же удаляются, плюс
    карточка «ауе», у которой категории не было и до заливки).

    Пишем SQL, а не ORM, и это осознанно:
      * поле name у товара — jsonb переводов. ORM пишет ключ ТЕКУЩЕГО языка и
        чужие ключи не убирает, то есть «вернуть» им нельзя, можно только
        дописать. SQL кладёт колонку целиком — ровно то, что сняли.
      * вес: пока точность «Stock Weight» стоит 5 знаков, ORM округляет при
        записи, и восстановленный вес зависел бы от того, в каком порядке
        вернули точность и массы. SQL от точности не зависит вовсе.
      * kod и okei: вернуть надо NULL, а не пустую строку — в снимке лежит
        именно NULL, и сверка сравнивает их как разные значения.
    Значения кладутся ровно те, что сняты, поэтому проверки ORM здесь ничего
    бы не проверили: база уже была в этом состоянии и была согласованной.
    """
    head(4, "Возврат чужих записей")
    всего = 0
    for key in sorted(snap["разделы"]):
        sec = snap["разделы"][key]
        table, cols, rows = sec["таблица"], sec["колонки"], sec["строки"]
        if not rows:
            continue
        types = column_types(table)
        if not types:
            ОШИБКИ.append("таблицы %s больше нет — раздел %s не возвращён" % (table, key))
            continue
        id_i = cols.index("id")
        data_cols = [c for c in cols if c != "id"]

        # Текущее состояние читаем ТЕМ ЖЕ выражением, каким снимали, — иначе
        # сравнивали бы число с текстом и «нашли» бы расхождение на ровном месте.
        # Раздел из одной колонки id (характеристики, значения, строки
        # характеристик) возвращать нечего: он говорит только о том, какие
        # записи БЫЛИ, и работает как список «это чужое, не удалять».
        сейчас = {}
        if data_cols:
            select = ", ".join(read_expr(c, types.get(c, "")) for c in data_cols)
            env.cr.execute(  # noqa: F821,S608
                "SELECT id, %s FROM %s WHERE id = ANY(%%s)" % (select, table),
                ([r[id_i] for r in rows],))
            сейчас = {r[0]: list(r[1:]) for r in env.cr.fetchall()}  # noqa: F821
        else:
            env.cr.execute("SELECT id FROM %s WHERE id = ANY(%%s)" % table,  # noqa: F821,S608
                           ([r[id_i] for r in rows],))
            сейчас = {r[0]: [] for r in env.cr.fetchall()}  # noqa: F821

        правок, пропало = 0, []
        for row in rows:
            rid = row[id_i]
            было = [row[cols.index(c)] for c in data_cols]
            есть = сейчас.get(rid)
            if есть is None:
                пропало.append(rid)
                continue
            if есть == было:
                continue
            sets = ", ".join(
                "%s = %%s::%s" % (c, types.get(c, "text")) for c in data_cols)
            env.cr.execute(  # noqa: F821,S608
                "UPDATE %s SET %s WHERE id = %%s" % (table, sets), было + [rid])
            правок += 1
            изменилось = [(c, e, b) for c, e, b in zip(data_cols, есть, было) if e != b]
            print("  %-22s id %-5s вернули: %s"
                  % (table, rid, "; ".join(
                      "%s %r -> %r" % (c, e, b) for c, e, b in изменилось[:4])))

        # Строка, которой в базе не стало. Вернуть её можно, только если
        # снимок хранит её целиком, — иначе у неё нет ни имени, ни ссылок.
        if пропало:
            if sec.get("строка_целиком"):
                place = ", ".join("%s" for _ in cols)
                for row in rows:
                    if row[id_i] not in пропало:
                        continue
                    env.cr.execute(  # noqa: F821,S608
                        "INSERT INTO %s (%s) VALUES (%s)"
                        % (table, ", ".join(cols),
                           ", ".join("%%s::%s" % types.get(c, "text") for c in cols)),
                        list(row))
                    правок += 1
                    print("  %-22s id %-5s строка ВОССТАНОВЛЕНА целиком "
                          "(её удалила подготовка среды)" % (table, row[id_i]))
                # Последовательность id двигать не надо: id уже существовал
                # до заливки, значит счётчик его давно прошёл.
            else:
                ОШИБКИ.append(
                    "%s: строк %s в базе больше нет, а снимок хранит у них только "
                    "правимые поля — восстановить нечем" % (table, пропало))
                print("  %-22s ПРОПАЛИ строки %s — снимок хранит не всю строку, "
                      "вернуть невозможно" % (table, пропало))

        # Лишние строки (те, что завёл мост) здесь НЕ считаем: на этом шаге
        # они ещё на месте — удаление идёт следующим. Их считает сверка, шаг 7.
        всего += правок
        print("  %-22s строк в снимке %-4d возвращено %d" % (table, len(rows), правок))

    # Точность читается через ormcache: без сброса поле веса до конца процесса
    # продолжит округлять по-старому, и сверка увидит не то, что в базе.
    env.registry.clear_cache()  # noqa: F821
    env.invalidate_all()  # noqa: F821
    print("  правок всего: %d (кэш реестра сброшен — точность веса читается заново)"
          % всего)


# ═══ ШАГ 5 ════════════════════════════════════════════════════════════════
def delete_owned(plan):
    """Удалить то, что мост ЗАВЁЛ. Усыновлённое не трогаем.

    Удаляем через ORM, а не SQL: ORM снимает заодно строки ir_model_data,
    комбинации вариантов и значения характеристик карточек, и — главное —
    честно отказывает, если запись где-то используется. SQL DELETE прошёл бы
    молча и оставил висящие ссылки.
    """
    head(5, "Удаление того, что завёл мост")
    for model in plan["unknown"] + list(OWNED_ORDER):
        ids = plan["ours"].get(model) or []
        if not ids:
            continue
        recs = env[model].with_context(active_test=False).browse(ids).exists()  # noqa: F821
        if not recs:
            print("  %-26s уже удалено" % model)
            continue
        удалено = 0
        # Пачками: на 748 карточках падение в середине иначе не локализовать.
        for start in range(0, len(recs), 100):
            chunk = recs[start:start + 100]
            try:
                chunk.unlink()
            except Exception as exc:  # noqa: BLE001 — сообщение Odoo важнее типа
                отказ("%s: удаление пачки %d-%d не прошло.\n%s"
                      % (model, start, start + len(chunk),
                         str(exc).replace("\n", " ")[:500]))
            удалено += len(chunk)
        print("  %-26s удалено %d" % (model, удалено))
    env.flush_all()  # noqa: F821
    env.invalidate_all()  # noqa: F821


# ═══ ШАГ 6 ════════════════════════════════════════════════════════════════
def drop_traces():
    """Убрать внешние идентификаторы моста и сам снимок.

    Внешние идентификаторы удалённых записей ORM снял вместе с записями.
    Остаются идентификаторы УСЫНОВЛЁННЫХ — их записали поверх чужих карточек
    и категории, самих записей это не касается. Их надо снять руками: до
    заливки их не было, а при будущей установке модуля они сделают чужую
    карточку записью модуля со всеми вытекающими.

    Снимок удаляется последним и только после того, как его переписали в
    файл: до заливки параметра в базе не было, и сверка обязана сойтись в
    том числе по числу параметров.
    """
    head(6, "Следы моста")
    Param = env["ir.config_parameter"].sudo()  # noqa: F821
    raw = Param.get_param(SNAPSHOT_PARAM)
    if raw:
        try:
            with open(SNAPSHOT_FILE, "w", encoding="utf-8") as fp:
                fp.write(raw)
            print("  снимок переписан в %s — повторный откат возможен без параметра"
                  % SNAPSHOT_FILE)
        except OSError as exc:
            print("  снимок в файл не записан (%s). Параметр удаляю всё равно: "
                  "возвращать уже нечего." % exc)

    env.cr.execute("SELECT model, count(*) FROM ir_model_data WHERE module=%s "  # noqa: F821
                   "GROUP BY model ORDER BY model", (MODULE,))
    остатки = env.cr.fetchall()  # noqa: F821
    for model, cnt in остатки:
        print("  осталось внешних идентификаторов %s: %d (усыновлённые)" % (model, cnt))
    env.cr.execute("DELETE FROM ir_model_data WHERE module=%s", (MODULE,))  # noqa: F821
    print("  удалено строк ir_model_data модуля %s: %d" % (MODULE, env.cr.rowcount))  # noqa: F821

    if raw:
        env.cr.execute("DELETE FROM ir_config_parameter WHERE key=%s", (SNAPSHOT_PARAM,))  # noqa: F821
        print("  параметр %s удалён (до заливки его не было)" % SNAPSHOT_PARAM)
    env.invalidate_all()  # noqa: F821


# ═══ ШАГ 7 ════════════════════════════════════════════════════════════════
def verify(snap):
    """Сверить получившееся со снимком поимённо. Без цифр вывод не принимается."""
    head(7, "Сверка с состоянием до заливки")
    сошлось, разошлось = 0, 0
    for key in sorted(snap["разделы"]):
        sec = snap["разделы"][key]
        table, cols, rows = sec["таблица"], sec["колонки"], sec["строки"]
        types = column_types(table)
        if not types:
            continue
        id_i = cols.index("id")
        data_cols = [c for c in cols if c != "id"]
        if data_cols:
            select = ", ".join(read_expr(c, types.get(c, "")) for c in data_cols)
            env.cr.execute("SELECT id, %s FROM %s ORDER BY id" % (select, table))  # noqa: F821,S608
            сейчас = {r[0]: list(r[1:]) for r in env.cr.fetchall()}  # noqa: F821
        else:
            # Раздел-список: сверяем только состав записей, полей в нём нет.
            env.cr.execute("SELECT id FROM %s ORDER BY id" % table)  # noqa: F821,S608
            сейчас = {r[0]: [] for r in env.cr.fetchall()}  # noqa: F821
        ожидалось = {r[id_i]: [r[cols.index(c)] for c in data_cols] for r in rows}

        лишние = sorted(set(сейчас) - set(ожидалось))
        пропавшие = sorted(set(ожидалось) - set(сейчас))
        различия = [i for i in set(сейчас) & set(ожидалось) if сейчас[i] != ожидалось[i]]
        ok = not (лишние or пропавшие or различия)
        print("  %-24s %-34s строк было %-4d стало %-4d  %s"
              % (key, table, len(ожидалось), len(сейчас), "СОВПАЛО" if ok else "РАСХОЖДЕНИЕ"))
        if ok:
            сошлось += 1
            continue
        разошлось += 1
        if лишние:
            print("      лишних строк %d: %s" % (len(лишние), лишние[:10]))
        if пропавшие:
            print("      пропало строк %d: %s" % (len(пропавшие), пропавшие[:10]))
        for i in sorted(различия)[:10]:
            расх = [(c, a, b) for c, a, b in zip(data_cols, сейчас[i], ожидалось[i]) if a != b]
            print("      id %-5s %s" % (i, "; ".join(
                "%s сейчас %r, ожидалось %r" % (c, a, b) for c, a, b in расх)))
        ОШИБКИ.append("%s: расхождений %d, лишних %d, пропавших %d"
                      % (table, len(различия), len(лишние), len(пропавшие)))

    env.cr.execute("SELECT count(*) FROM ir_model_data WHERE module=%s", (MODULE,))  # noqa: F821
    traces = env.cr.fetchone()[0]  # noqa: F821
    print("  записей ir_model_data модуля %s: %d (ожидалось %d)"
          % (MODULE, traces, snap.get("было_записей_моста", 0)))
    if traces != snap.get("было_записей_моста", 0):
        ОШИБКИ.append("остались внешние идентификаторы моста: %d" % traces)

    # Остатки склада — отдельной строкой: ради них всё и затевалось.
    env.cr.execute(  # noqa: F821
        "SELECT count(*), COALESCE(round(SUM(quantity)::numeric,3),0) FROM stock_quant")
    кв, кол = env.cr.fetchone()  # noqa: F821
    print("  квантов склада %d, суммарное количество %s" % (кв, кол))
    env.cr.execute("SELECT count(*) FROM stock_move")  # noqa: F821
    print("  движений склада %d" % env.cr.fetchone()[0])  # noqa: F821

    print("\n  разделов сошлось %d, разошлось %d" % (сошлось, разошлось))
    return разошлось == 0


snap = load_snapshot()
plan = build_plan(snap)
detach_attributes(snap, plan)
restore_foreign(snap)
delete_owned(plan)
drop_traces()
ok = verify(snap)

print("\n" + SEP)
if ОШИБКИ:
    print("ЗАМЕЧАНИЯ ОТКАТА (%d):" % len(ОШИБКИ))
    for text in ОШИБКИ:
        print("  * %s" % text)
if ok and not ОШИБКИ:
    print("ОТКАТ ПОЛНЫЙ: база совпала со снимком по всем разделам.")
else:
    print("ОТКАТ НЕПОЛНЫЙ: см. расхождения и замечания выше. Фиксируем всё равно —")
    print("незафиксированный полуоткат хуже зафиксированного: его не увидит ни")
    print("следующий прогон, ни сверка.")
print(SEP)
env.cr.commit()  # noqa: F821
print("зафиксировано в базе %s" % env.cr.dbname)  # noqa: F821
print("=== КОНЕЦ ===")
