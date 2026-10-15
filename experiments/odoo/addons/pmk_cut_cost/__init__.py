from . import models


def post_init_hook(env):
    """Расчёты, разложенные раньше: доля по раскрою посчитана при установке,
    а «Купить» и закупка строк по ней — нет (ядро не пересчитывает зависимые
    поля от нового поля при установке). Пересчитываем сами; изделия и итоги
    расчёта подтянутся по цепочке."""
    lines = env["pmk.metal.spec.line"].search([("pmk_cut_share", ">", 0)])
    if not lines:
        return
    names = ["cost_fact_one", "cost_fact_total", "weight_fact_one", "weight_fact_total"]
    for name in names:
        env.add_to_compute(lines._fields[name], lines)
    env.flush_all()
    # Пересчёт из хука сам зависимых не будит — будим явно: изделия, итоги
    # расчёта, маржа.
    lines.modified(names)
    env.flush_all()
