import os, calendar, datetime as dt
from flask import Flask, request, redirect, url_for, render_template_string, flash
from db import query, execute, DBError

app = Flask(__name__)
app.secret_key = "worktime-demo"
TODAY = os.environ.get("DEMO_DATE", "2026-11-22")  # дата текущей смены в тестовых данных
POS = {"barista": "Б", "waiter": "О", "manager": "У"}
VIOL = {"late": "опоздание", "early_leave": "ранний уход", "absent": "прогул"}

def short(name, pos):
    f, i = name.split()[:2]
    return f"{i} {f[0]}. ({POS[pos]})"

BASE_CSS = """
*{box-sizing:border-box} body{margin:0;font-family:'Segoe UI',system-ui,sans-serif}
.msg{max-width:1000px;margin:12px auto;padding:10px 16px;border-radius:10px;background:#fdecea;color:#b3261e}
.ok{background:#e8f5e9;color:#1b5e20}
nav{max-width:1000px;margin:12px auto 0;display:flex;gap:14px;font-size:14px}
nav a{color:#6f4e37;text-decoration:none;padding:4px 10px;border-radius:8px}
nav a.on{background:#f0e6dc;font-weight:600}
"""

BARISTA = """<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>WorkTime — рабочее место бариста</title><style>""" + BASE_CSS + """
body{background:#faf7f4;color:#2d2118}
.card{max-width:640px;margin:20px auto;background:#fff;border-radius:28px;padding:36px 44px;box-shadow:0 8px 30px rgba(111,78,55,.08)}
h1{text-align:center;color:#6f4e37;margin:6px 0 10px;font-size:32px}
.sub{text-align:center;color:#8a7b70;font-size:14px;margin-bottom:6px}
.badge{display:block;width:max-content;margin:0 auto;padding:6px 18px;border-radius:20px;background:#e0f2ec;color:#00796b;font-weight:600;font-size:15px}
.badge.act{background:#fff3d6;color:#9a6700}.badge.done{background:#ece7e2;color:#6f4e37}
.btnrow{text-align:center;margin:30px 0 28px}
button.main{background:#6f4e37;color:#fff;border:0;border-radius:16px;padding:20px 52px;font-size:22px;font-weight:700;cursor:pointer;box-shadow:0 6px 16px rgba(111,78,55,.35)}
button.main.stop{background:#a1432f}
button.main:disabled{background:#cbbfb5;box-shadow:none;cursor:default}
hr{border:0;border-top:1px solid #eee;margin:0 0 24px}
h2{font-size:20px;margin:0 0 14px}
.task{display:flex;align-items:center;gap:14px;background:#f9f7f5;border-left:4px solid #a9805e;border-radius:12px;padding:16px 18px;margin-bottom:12px}
.task form{margin:0}.task.done{opacity:.55;border-left-color:#d8c3b3}.task.done span{text-decoration:line-through}
.cb{width:32px;height:32px;border:2px solid #a9805e;border-radius:8px;background:#fff;cursor:pointer;font-size:18px;color:#fff;padding:0}
.done .cb{background:#7fc4bb;border-color:#7fc4bb}
.who{display:block;text-align:center;margin-top:6px;font-size:13px;color:#8a7b70}
select{font:inherit;padding:2px 6px;border-radius:6px;border:1px solid #d8c3b3}
</style>
<nav><a class=on href="/barista?emp={{emp.employee_id}}">Рабочее место</a><a href="/manager">Панель управляющего</a><a href="/employees">Сотрудники</a></nav>
{% for c,m in msgs %}<div class="msg {{c}}">{{m}}</div>{% endfor %}
<div class=card>
<h1>Рабочее место бариста</h1>
<div class=sub>Сотрудник:
<form style="display:inline" method=get><select name=emp onchange="this.form.submit()">
{% for e in emps %}<option value={{e.employee_id}} {{'selected' if e.employee_id==emp.employee_id}}>{{e.full_name}}</option>{% endfor %}</select></form>
· смена {{date_ru}} {% if plan %}· план {{plan.planned_start[:5]}}–{{plan.planned_end[:5]}}{% endif %}</div>
<span class="badge {{ 'act' if state=='active' else ('done' if state=='done' else '') }}">{{label}}</span>
<div class=btnrow>
{% if state=='idle' %}<form method=post action="/shift/start"><input type=hidden name=emp value={{emp.employee_id}}><input type=hidden name=at value="{{at}}"><button class=main {{'disabled' if not plan}}>Начать смену</button></form>
{% elif state=='active' %}<form method=post action="/shift/end"><input type=hidden name=emp value={{emp.employee_id}}><input type=hidden name=at value="{{at}}"><button class="main stop">Завершить смену</button></form>
{% else %}<button class=main disabled>Смена завершена</button>{% endif %}
</div><hr>
<h2>📋 Задачи на сегодня</h2>
{% for t in tasks %}<div class="task {{'done' if t.status=='done'}}"><form method=post action="/task/{{t.task_id}}/toggle"><input type=hidden name=emp value={{emp.employee_id}}><button class=cb title="Отметить">{{'✓' if t.status=='done'}}</button></form><span>{{t.title}}</span></div>
{% else %}<div class=sub>На сегодня задач нет</div>{% endfor %}
</div></html>"""

MANAGER = """<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>WorkTime — панель управляющего</title><style>""" + BASE_CSS + """
body{background:#f3f6f9;color:#1f2d3a}
.wrap{max-width:1000px;margin:0 auto;padding:0 16px 40px}
h1{font-size:30px;margin:18px 0 18px;color:#1f3340}
.card{background:#fff;border-radius:18px;padding:26px 30px;margin-bottom:26px;box-shadow:0 2px 12px rgba(31,45,58,.05)}
h2{font-size:20px;margin:0 0 18px;padding-bottom:12px;border-bottom:1px solid #e6ebf0;color:#4a4036;display:flex;justify-content:space-between;align-items:center}
h2 small{font-size:14px;font-weight:400}
table{width:100%;border-collapse:collapse}
.cal td,.cal th{border:1px solid #dfe6ec;width:14.28%;vertical-align:top;font-size:13px}
.cal th{background:#f6f8fa;padding:10px}.cal td{height:92px;padding:8px}
.cal .dn{font-size:13px;margin-bottom:6px;color:#333}
.chip{display:block;background:#e8f0fb;color:#1f5f9e;border-radius:6px;padding:4px 8px;margin-bottom:4px;font-size:12px}
.chip.bad{background:#fde7e4;color:#b3261e}
.cal td.off{background:#fafbfc;color:#aaa}.cal td.today{background:#fff8f6}
.fin th{background:#f7f9fb;text-align:left;padding:14px 12px;border-bottom:2px solid #dfe6ec;font-size:15px}
.fin td{padding:14px 12px;border-bottom:1px solid #eef1f4}
.pos{color:#2e7d32}.neg{color:#d32f2f}.tot{font-family:Consolas,monospace;font-weight:700;color:#0a8f3c}
button.calc{background:#6f4e37;color:#fff;border:0;border-radius:10px;padding:10px 20px;font-size:15px;font-weight:600;cursor:pointer}
.vl td{padding:10px 12px;border-bottom:1px solid #eef1f4;font-size:14px}
.tag{padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600}
.tag.late{background:#fff3d6;color:#9a6700}.tag.early_leave{background:#e8f0fb;color:#1f5f9e}.tag.absent{background:#fde7e4;color:#b3261e}
form.inl{display:inline}select,input{font:inherit;padding:6px 10px;border-radius:8px;border:1px solid #cfd8e0}
.frm{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;margin-top:6px}
.frm label{display:flex;flex-direction:column;font-size:12px;color:#667;gap:4px}
.frm input[type=text]{min-width:260px}
button.btn{background:#1f5f9e;color:#fff;border:0;border-radius:10px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer}
button.btn.sec{background:#eef3f8;color:#1f3340}button.btn.red{background:#fde7e4;color:#b3261e}
.scroll{max-height:340px;overflow:auto}.st{font-size:12px;padding:2px 10px;border-radius:12px;background:#eef1f4}
.st.open,.st.active{background:#e0f2ec;color:#00796b}.hint{font-size:12px;color:#778;margin-top:8px}
.tl td{padding:9px 12px;border-bottom:1px solid #eef1f4;font-size:14px}
</style>
<div class=wrap>
<nav style="margin:12px 0 0"><a href="/barista">Рабочее место</a><a class=on href="/manager">Панель управляющего</a><a href="/employees">Сотрудники</a></nav>
{% for c,m in msgs %}<div class="msg {{c}}" style="margin:12px 0">{{m}}</div>{% endfor %}
<h1>Панель Управляющего</h1>
<div class=card><h2><span>📅 График смен ({{title}})</span>
<small><form class=inl method=get><select name=month onchange="this.form.submit()">{% for m,n in months %}<option value={{m}} {{'selected' if m==month}}>{{n}}</option>{% endfor %}</select></form></small></h2>
<table class=cal><tr>{% for d in ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'] %}<th>{{d}}</th>{% endfor %}</tr>
{% for week in weeks %}<tr>{% for day in week %}<td class="{{'off' if not day.in_month}} {{'today' if day.iso==today}}"><div class=dn>{{day.label}}</div>
{% for c in day.chips %}<span class="chip {{'bad' if c.viol}}" title="{{c.viol or ''}}">{{c.text}}</span>{% endfor %}</td>{% endfor %}</tr>{% endfor %}</table>
<div style="font-size:12px;color:#777;margin-top:10px">Б — бариста, О — официант. Красным отмечены смены с нарушением дисциплины.</div></div>

<div class=card><h2><span>✏️ Редактирование графика</span></h2>
<form class=frm method=post action="/schedule/set"><input type=hidden name=month value={{month}}>
<label>Сотрудник<select name=emp>{% for e in emps %}<option value={{e.employee_id}}>{{e.full_name}}</option>{% endfor %}</select></label>
<label>Дата<input type=date name=date value="{{today}}" required></label>
<label>Начало<input type=time name=start value="08:00" required></label>
<label>Конец<input type=time name=end value="16:00" required></label>
<button class=btn>Назначить / изменить</button>
<button class="btn red" formaction="/schedule/remove">Убрать из графика</button></form>
<div class=hint>Если на выбранную дату смены ещё нет, она создаётся автоматически. Закрытые смены менять нельзя.</div></div>

<div class=card><h2><span>🗓 Смены месяца</span>
<form class=inl method=post action="/absences/mark"><input type=hidden name=month value={{month}}><button class="btn sec" style="padding:8px 14px;border:0;border-radius:10px;cursor:pointer">Отметить прогулы на сегодня</button></form></h2>
<div class=scroll><table class=tl><tr><th align=left>Дата</th><th align=left>Статус</th><th align=left>В графике</th><th align=left>Выручка</th><th></th></tr>
{% for sh in shifts %}<tr><td>{{sh.d_ru}}</td><td><span class="st {{sh.status}}">{{sname[sh.status]}}</span></td><td>{{sh.cnt}} чел.</td>
<td>{% if sh.revenue is not none %}{{'{:,.2f}'.format(sh.revenue).replace(',',' ')}} ₽{% else %}—{% endif %}</td>
<td>{% if sh.status in ('open','active') %}<form class=inl method=post action="/shift/close"><input type=hidden name=month value={{month}}><input type=hidden name=date value={{sh.shift_date}}>
<input type=text name=revenue placeholder="Выручка, ₽" size=11 required> <button class="btn sec" style="padding:7px 12px;border:0;border-radius:10px;cursor:pointer">Закрыть смену</button></form>{% endif %}</td></tr>
{% else %}<tr><td colspan=5 style="color:#777">В этом месяце смен нет</td></tr>{% endfor %}</table></div>
<div class=hint>При закрытии смены не пришедшие сотрудники автоматически получают отметку «прогул», после чего отметки времени блокируются.</div></div>

<div class=card><h2><span>📋 Задачи на смену</span>
<small><form class=inl method=get><input type=hidden name=month value={{month}}><input type=date name=tdate value="{{tdate}}" onchange="this.form.submit()"></form></small></h2>
<table class=tl>{% for t in tasks %}<tr><td>{{t.title}}</td><td>{{t.full_name}}</td><td>{{'✓ выполнена' if t.status=='done' else 'в работе'}}</td></tr>
{% else %}<tr><td style="color:#777">На выбранную дату задач нет</td></tr>{% endfor %}</table>
<form class=frm method=post action="/task/assign" style="margin-top:14px"><input type=hidden name=month value={{month}}>
<label>Дата смены<input type=date name=date value="{{tdate}}" required></label>
<label>Исполнитель<select name=emp>{% for e in emps %}<option value={{e.employee_id}}>{{e.full_name}}</option>{% endfor %}</select></label>
<label>Задача<input type=text name=title maxlength=150 placeholder="Например: инвентаризация сиропов" required></label>
<button class=btn>Назначить задачу</button></form></div>

<div class=card><h2><span>⚠️ Нарушения дисциплины</span></h2>
<table class=vl>{% for v in viol %}<tr><td>{{v.shift_date}}</td><td>{{v.full_name}}</td><td><span class="tag {{v.violation}}">{{vname[v.violation]}}</span></td><td>{% if v.violation=='early_leave' %}уход: план {{v.planned_end[:5]}}, факт {{v.actual_end[:5]}}{% elif v.violation=='late' %}приход: план {{v.planned_start[:5]}}, факт {{v.actual_start[:5]}}{% else %}приход по плану в {{v.planned_start[:5]}} не зафиксирован{% endif %}</td></tr>
{% else %}<tr><td>Нарушений за месяц нет</td></tr>{% endfor %}</table></div>

<div class=card><h2><span>💰 Финансы: Итоговые выплаты</span>
<form class=inl method=post action="/payouts/calc"><input type=hidden name=month value={{month}}><button class=calc>Рассчитать ЗП</button></form></h2>
<table class=fin><tr><th>Сотрудник</th><th>Часы</th><th>Премии</th><th>Штрафы</th><th>Итого к выплате</th></tr>
{% for p in pays %}<tr><td>{{p.full_name}}</td><td>{{'%.2f'|format(p.hours_worked)|replace('.',',')}} ч.</td><td class=pos>+{{'{:,.0f}'.format(p.bonus).replace(',',' ')}} ₽</td>
<td class="{{'neg' if p.penalty>0}}">{{'−' if p.penalty>0}}{{'{:,.0f}'.format(p.penalty).replace(',',' ')}} ₽</td>
<td class=tot>{{'{:,.0f}'.format(p.total_amount).replace(',',' ')}} ₽{% if p.total_amount==0 and p.penalty>0 %}<br><small style="font-weight:400;color:#777;font-family:inherit">штраф больше начисленного</small>{% endif %}</td></tr>
{% else %}<tr><td colspan=5 style="color:#777">За выбранный месяц выплаты не рассчитаны — нажмите «Рассчитать ЗП».</td></tr>{% endfor %}</table>
<form class=frm method=post action="/payouts/bonus" style="margin-top:16px"><input type=hidden name=month value={{month}}>
<label>Добавить премию сотруднику<select name=emp>{% for e in emps %}<option value={{e.employee_id}}>{{e.full_name}}</option>{% endfor %}</select></label>
<label>Сумма, ₽<input type=text name=bonus size=10 placeholder="например, 2500" required></label>
<button class=btn>Добавить премию</button></form>
<div class=hint>Суммы накапливаются: 10 000 и затем 2 500 дадут 12 500 ₽. Чтобы исправить ошибку, введите отрицательное число (например, −2500). Итог пересчитывается сразу.</div></div></div></html>"""

def msgs():
    out = []
    for x in request.args.getlist("f"):
        k, _, m = x.partition("|")
        out.append(("ok" if k == "ok" else "", m))
    return out

def back(url, kind, text, **kw):
    return redirect(url_for(url, f=f"{kind}|{text}", **kw))

@app.get("/")
def index():
    return redirect(url_for("barista"))

@app.get("/barista")
def barista():
    emps = query("SELECT employee_id, full_name FROM employee WHERE position <> 'manager' ORDER BY 1")
    eid = int(request.args.get("emp", emps[0]["employee_id"]))
    emp = next(e for e in emps if e["employee_id"] == eid)
    sh = query("SELECT shift_id, status FROM shift WHERE shift_date = :d", d=TODAY)
    plan = tr = None; tasks = []
    state, label = "idle", "Смена не начата"
    if sh:
        plan = (query("SELECT planned_start, planned_end FROM schedule WHERE employee_id=:e AND shift_date=:d", e=eid, d=TODAY) or [None])[0]
        tr = (query("SELECT actual_start, actual_end, violation FROM time_record WHERE employee_id=:e AND shift_id=:s", e=eid, s=sh[0]["shift_id"]) or [None])[0]
        tasks = query("SELECT task_id, title, status FROM task WHERE shift_id=:s AND executor_id=:e ORDER BY task_id", s=sh[0]["shift_id"], e=eid)
    if tr and tr["violation"] == "absent":
        state, label = "done", "Смена пропущена (прогул)"
    elif tr and tr["actual_end"]:
        state, label = "done", f"Смена завершена в {tr['actual_end'][11:16]}"
    elif tr:
        state, label = "active", f"Смена идёт с {tr['actual_start'][11:16]}"
    elif not plan:
        label = "Сегодня вы не в графике"
    return render_template_string(BARISTA, emps=emps, emp=emp, plan=plan, tasks=tasks, state=state, label=label,
                                  date_ru=dt.date.fromisoformat(TODAY).strftime('%d.%m.%Y'), at=request.args.get("at", ""), msgs=msgs())

def at_param():
    a = request.form.get("at", "").strip()
    return f"{TODAY} {a}" if a else f"{TODAY} {dt.datetime.now():%H:%M:%S}"

@app.post("/shift/start")
def shift_start():
    eid = request.form["emp"]
    try:
        s = query("SELECT shift_id FROM shift WHERE shift_date=:d", d=TODAY)[0]["shift_id"]
        query("SELECT start_shift(:e, :s, :a::timestamp)", e=eid, s=s, a=at_param())
    except (DBError, IndexError) as ex:
        return back("barista", "err", str(ex), emp=eid)
    return back("barista", "ok", "Приход зафиксирован", emp=eid)

@app.post("/shift/end")
def shift_end():
    eid = request.form["emp"]
    try:
        s = query("SELECT shift_id FROM shift WHERE shift_date=:d", d=TODAY)[0]["shift_id"]
        query("SELECT end_shift(:e, :s, :a::timestamp)", e=eid, s=s, a=at_param())
    except (DBError, IndexError) as ex:
        return back("barista", "err", str(ex), emp=eid)
    return back("barista", "ok", "Уход зафиксирован", emp=eid)

@app.post("/task/<int:tid>/toggle")
def task_toggle(tid):
    execute("UPDATE task SET status = CASE WHEN status='done' THEN 'new'::task_status ELSE 'done'::task_status END WHERE task_id=:t", t=tid)
    return redirect(url_for("barista", emp=request.form["emp"]))

SNAME = {"planned": "запланирована", "open": "открыта", "active": "идёт", "closed": "закрыта", "calculated": "рассчитана"}
RU_MONTHS = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]

@app.get("/manager")
def manager():
    month = request.args.get("month") or TODAY[:7]
    y, m = map(int, month.split("-"))
    first = dt.date(y, m, 1)
    rows = query("""SELECT sc.shift_date, e.full_name, e.position, COALESCE(tr.violation::text,'none') AS viol
        FROM schedule sc JOIN employee e USING (employee_id)
        LEFT JOIN shift s ON s.shift_date = sc.shift_date
        LEFT JOIN time_record tr ON tr.shift_id = s.shift_id AND tr.employee_id = sc.employee_id
        WHERE sc.shift_date >= :f AND sc.shift_date < (:f::date + interval '1 month') ORDER BY sc.shift_date, e.employee_id""", f=first.isoformat())
    by = {}
    for r in rows:
        by.setdefault(r["shift_date"], []).append({"text": short(r["full_name"], r["position"]), "viol": VIOL.get(r["viol"])})
    weeks = []
    for w in calendar.Calendar(0).monthdatescalendar(y, m):
        weeks.append([{"iso": d.isoformat(), "in_month": d.month == m,
                       "label": str(d.day) if d.day != 1 or d.month == m and d.day != 1 else f"1 ({RU_MONTHS[d.month-1][:3].lower()}.)",
                       "chips": by.get(d.isoformat(), []) if d.month == m else []} for d in w])
    viol = query("SELECT to_char(shift_date,'DD.MM.YYYY') AS shift_date, full_name, violation, planned_start, planned_end, actual_start, actual_end FROM v_violations WHERE shift_date >= :f AND shift_date < (:f::date + interval '1 month') ORDER BY 1, 2", f=first.isoformat())
    pays = query("SELECT e.full_name, p.hours_worked, p.bonus, p.penalty, p.total_amount FROM payout p JOIN employee e USING (employee_id) WHERE p.period = :f ORDER BY e.employee_id", f=first.isoformat())
    emps = query("SELECT employee_id, full_name FROM employee WHERE position <> 'manager' ORDER BY 1")
    shifts = query("""SELECT s.shift_date, to_char(s.shift_date,'DD.MM.YYYY') AS d_ru, s.status, s.revenue,
        (SELECT count(*) FROM schedule sc WHERE sc.shift_date = s.shift_date) AS cnt FROM shift s
        WHERE s.shift_date >= :f AND s.shift_date < (:f::date + interval '1 month') ORDER BY s.shift_date""", f=first.isoformat())
    tdate = request.args.get("tdate") or TODAY
    tasks = query("""SELECT t.task_id, t.title, t.status, e.full_name FROM task t JOIN shift s USING (shift_id)
        JOIN employee e ON e.employee_id = t.executor_id WHERE s.shift_date = :d ORDER BY t.task_id""", d=tdate)
    months = [(f"2026-{i:02d}", f"{RU_MONTHS[i-1]} 2026") for i in (4, 5, 6)] + [("2026-11", "Ноябрь 2026")]
    if month not in [m for m, _ in months]:
        months.append((month, f"{RU_MONTHS[m-1]} {y}"))
    return render_template_string(MANAGER, title=f"{RU_MONTHS[m-1]} {y}", weeks=weeks, viol=viol, pays=pays, month=month,
                                  months=months, today=TODAY, emps=emps, shifts=shifts, tasks=tasks, tdate=tdate,
                                  sname=SNAME, vname={"late": "Опоздание", "early_leave": "Ранний уход", "absent": "Прогул"}, msgs=msgs())

@app.post("/payouts/calc")
def payouts_calc():
    month = request.form["month"]
    try:
        n = query("SELECT calculate_payouts(:d::date) AS n", d=month + "-01")[0]["n"]
    except DBError as ex:
        return back("manager", "err", str(ex), month=month)
    return back("manager", "ok", f"Расчёт выполнен для сотрудников: {n}", month=month)


def num(name):
    """Читает число из формы (допускает запятую), иначе возвращает None."""
    try:
        return float(request.form.get(name, "").strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None

def mgr_action(ok_text, sql, **params):
    """Выполняет функцию БД из панели менеджера и возвращается на панель с сообщением."""
    month = request.form.get("month", "2026-05")
    try:
        r = query(sql, **params)
    except DBError as ex:
        return back("manager", "err", str(ex), month=month)
    n = next(iter(r[0].values())) if r else None
    return back("manager", "ok", ok_text(n) if callable(ok_text) else ok_text, month=month)

@app.post("/schedule/set")
def schedule_set():
    f = request.form
    return mgr_action("График обновлён", "SELECT set_schedule(:e, :d::date, :s::time, :t::time)",
                      e=f["emp"], d=f["date"], s=f["start"], t=f["end"])

@app.post("/schedule/remove")
def schedule_remove():
    f = request.form
    return mgr_action("Сотрудник убран из графика", "SELECT remove_schedule(:e, :d::date)", e=f["emp"], d=f["date"])

@app.post("/absences/mark")
def absences_mark():
    now = f"{TODAY} {dt.datetime.now().strftime('%H:%M:%S')}"
    return mgr_action(lambda n: f"Отмечено прогулов: {n}", "SELECT mark_absences(:d::date, :n::timestamp)", d=TODAY, n=now)

@app.post("/shift/close")
def shift_close():
    rev = num("revenue")
    if rev is None:
        return back("manager", "err", "Введите выручку числом", month=request.form.get("month", "2026-05"))
    return mgr_action(lambda n: "Смена закрыта" + (f", отмечено прогулов: {n}" if n else ""),
                      "SELECT close_shift(:d::date, :r::numeric)", d=request.form["date"], r=rev)

@app.post("/task/assign")
def task_assign():
    f = request.form
    return mgr_action("Задача назначена", "SELECT assign_task(:d::date, :e, :t)", d=f["date"], e=f["emp"], t=f["title"])

@app.post("/payouts/bonus")
def payouts_bonus():
    b = num("bonus")
    month = request.form.get("month", "2026-05")
    if b is None:
        return back("manager", "err", "Введите премию числом", month=month)
    return mgr_action(lambda n: f"Премия добавлена. Всего премий за месяц: {float(n):,.2f} ₽".replace(",", " "),
                      "SELECT add_bonus(:e, :p::date, :b::numeric)", e=request.form["emp"], p=month + "-01", b=b)

PNAME = {"barista": "Бариста", "waiter": "Официант", "manager": "Управляющий"}
EMPLOYEES = """<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>WorkTime — сотрудники</title><style>""" + BASE_CSS + """
body{background:#f3f6f9;color:#1f2d3a}.wrap{max-width:1000px;margin:0 auto;padding:0 16px 40px}
h1{font-size:30px;margin:18px 0;color:#1f3340}.card{background:#fff;border-radius:18px;padding:26px 30px;margin-bottom:26px;box-shadow:0 2px 12px rgba(31,45,58,.05)}
h2{font-size:20px;margin:0 0 18px;padding-bottom:12px;border-bottom:1px solid #e6ebf0;color:#4a4036}
table{width:100%;border-collapse:collapse}th{text-align:left;padding:12px;border-bottom:2px solid #dfe6ec;background:#f7f9fb}td{padding:12px;border-bottom:1px solid #eef1f4}
select,input{font:inherit;padding:6px 10px;border-radius:8px;border:1px solid #cfd8e0}
.frm{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}.frm label{display:flex;flex-direction:column;font-size:12px;color:#667;gap:4px}
.frm input[type=text]{min-width:280px}button.btn{background:#1f5f9e;color:#fff;border:0;border-radius:10px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer}
</style><div class=wrap>
<nav style="margin:12px 0 0"><a href="/barista">Рабочее место</a><a href="/manager">Панель управляющего</a><a class=on href="/employees">Сотрудники</a></nav>
{% for c,m in msgs %}<div class="msg {{c}}" style="margin:12px 0">{{m}}</div>{% endfor %}
<h1>Сотрудники</h1>
<div class=card><h2>Список сотрудников</h2>
<table><tr><th>ФИО</th><th>Должность</th><th>Ставка, ₽/ч</th><th>Изменить ставку</th></tr>
{% for e in emps %}<tr><td>{{e.full_name}}</td><td>{{pname[e.position]}}</td><td>{{'{:,.2f}'.format(e.hourly_rate).replace(',',' ')}}</td>
<td><form class=frm method=post action="/employees/rate" style="gap:8px"><input type=hidden name=emp value={{e.employee_id}}><input type=text name=rate size=8 placeholder="новая ставка" required><button class=btn style="padding:7px 12px">Сохранить</button></form></td></tr>{% endfor %}</table>
<div style="font-size:12px;color:#778;margin-top:10px">Новая ставка применяется при следующем расчёте выплат: при пересчёте месяца она относится ко всем часам этого месяца.</div></div>
<div class=card><h2>Добавить сотрудника</h2>
<form class=frm method=post action="/employees/add">
<label>ФИО<input type=text name=name maxlength=100 placeholder="Фамилия Имя Отчество" required></label>
<label>Должность<select name=position><option value=barista>Бариста</option><option value=waiter>Официант</option></select></label>
<label>Ставка, ₽/ч<input type=text name=rate size=8 value="300" required></label>
<button class=btn>Добавить</button></form></div></div></html>"""

@app.get("/employees")
def employees():
    emps = query("SELECT employee_id, full_name, position, hourly_rate FROM employee ORDER BY employee_id")
    return render_template_string(EMPLOYEES, emps=emps, pname=PNAME, msgs=msgs())

@app.post("/employees/rate")
def employees_rate():
    rate = num("rate")
    if rate is None:
        return back("employees", "err", "Введите ставку числом")
    try:
        query("SELECT update_rate(:e, :r::numeric)", e=request.form["emp"], r=rate)
    except DBError as ex:
        return back("employees", "err", str(ex))
    return back("employees", "ok", "Ставка изменена")

@app.post("/employees/add")
def employees_add():
    rate = num("rate")
    if rate is None:
        return back("employees", "err", "Введите ставку числом")
    try:
        query("SELECT add_employee(:n, :p::position_type, :r::numeric)", n=request.form["name"], p=request.form["position"], r=rate)
    except DBError as ex:
        return back("employees", "err", str(ex))
    return back("employees", "ok", "Сотрудник добавлен")

if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5050)))
