"""Автотесты WorkTime: логика БД (триггер, функции, ограничения) и веб-приложение.
Запуск (из папки tests):  python test_worktime.py
Нужна пустая БД worktime_test, владелец — роль worktime (см. README). Перед каждым тестом
объекты БД пересоздаются из sql/00_all_in_one.sql, поэтому тесты независимы."""
import os, sys, subprocess, unittest, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("PGDATABASE", "worktime_test")
os.environ.setdefault("DEMO_DATE", "2026-11-22")
sys.path.insert(0, str(ROOT / "app"))
import db                                    # слой доступа к БД приложения
from db import query, execute, DBError

D1, D2, D3, D4 = "2027-01-11", "2027-01-12", "2027-01-13", "2027-01-14"   # даты для сценариев


def reset_db():
    """Пересоздать схему, логику и тестовые данные."""
    base = list(db.PSQL)
    for args in (["-c", "DROP OWNED BY worktime CASCADE"], ["-f", str(ROOT / "sql" / "00_all_in_one.sql")]):
        r = subprocess.run(base + args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=db.ENV)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)


def val(sql, **p):
    """Первое значение первой строки результата."""
    r = query(sql, **p)
    return next(iter(r[0].values())) if r else None


class Base(unittest.TestCase):
    def setUp(self):
        reset_db()

    def sched(self, emp, date, s="08:00", e="16:00"):
        return val("SELECT set_schedule(:e, :d::date, :s::time, :t::time)", e=emp, d=date, s=s, t=e)

    def shift_id(self, date):
        return val("SELECT shift_id FROM shift WHERE shift_date=:d::date", d=date)

    def start(self, emp, date, at):
        return val("SELECT start_shift(:e, :s, :a::timestamp)", e=emp, s=self.shift_id(date), a=f"{date} {at}")

    def end(self, emp, date, at):
        return val("SELECT end_shift(:e, :s, :a::timestamp)", e=emp, s=self.shift_id(date), a=f"{date} {at}")

    def viol(self, emp, date):
        return val("SELECT violation FROM time_record WHERE employee_id=:e AND shift_id=(SELECT shift_id FROM shift WHERE shift_date=:d::date)", e=emp, d=date)

    def assertErr(self, text, sql, **p):
        with self.assertRaises(DBError) as c:
            query(sql, **p)
        self.assertIn(text, str(c.exception))


class TestAttendance(Base):
    """Отметка времени и контроль дисциплины"""
    def test_01_start_on_time(self):
        "TC-01 Приход по плану не является нарушением"
        self.sched(1, D1); self.start(1, D1, "08:00:00"); self.assertEqual(self.viol(1, D1), "none")

    def test_02_late_boundary(self):
        "TC-02 Опоздание ровно на 10 минут допустимо, на 10 минут 1 секунду — нарушение"
        self.sched(1, D1); self.sched(2, D1)
        self.start(1, D1, "08:10:00"); self.start(2, D1, "08:10:01")
        self.assertEqual(self.viol(1, D1), "none"); self.assertEqual(self.viol(2, D1), "late")

    def test_03_early_leave_boundary(self):
        "TC-03 Уход раньше плана ровно на 10 минут допустим, на 10 минут 1 секунду раньше — нарушение"
        self.sched(1, D1); self.sched(2, D1); self.start(1, D1, "08:00:00"); self.start(2, D1, "08:00:00")
        self.end(1, D1, "15:50:00"); self.end(2, D1, "15:49:59")
        self.assertEqual(self.viol(1, D1), "none"); self.assertEqual(self.viol(2, D1), "early_leave")

    def test_04_late_not_overwritten(self):
        "TC-04 Опоздание не заменяется ранним уходом (штраф за одну смену не удваивается)"
        self.sched(1, D1); self.start(1, D1, "08:30:00"); self.end(1, D1, "14:00:00")
        self.assertEqual(self.viol(1, D1), "late")

    def test_05_not_scheduled(self):
        "TC-05 Сотрудник вне графика не может начать смену"
        self.sched(1, D1)
        self.assertErr("не назначен", "SELECT start_shift(:e,:s,:a::timestamp)", e=2, s=self.shift_id(D1), a=f"{D1} 08:00")

    def test_06_double_start(self):
        "TC-06 Повторное начало смены отклоняется понятным сообщением"
        self.sched(1, D1); self.start(1, D1, "08:00:00")
        self.assertErr("уже начата", "SELECT start_shift(:e,:s,:a::timestamp)", e=1, s=self.shift_id(D1), a=f"{D1} 08:05")

    def test_07_end_without_start(self):
        "TC-07 Завершить смену без прихода нельзя"
        self.sched(1, D1)
        self.assertErr("Нет начатой смены", "SELECT end_shift(:e,:s,:a::timestamp)", e=1, s=self.shift_id(D1), a=f"{D1} 16:00")

    def test_08_double_end(self):
        "TC-08 Повторное завершение смены отклоняется понятным сообщением"
        self.sched(1, D1); self.start(1, D1, "08:00:00"); self.end(1, D1, "16:00:00")
        self.assertErr("уже завершена", "SELECT end_shift(:e,:s,:a::timestamp)", e=1, s=self.shift_id(D1), a=f"{D1} 16:05")

    def test_09_end_before_start(self):
        "TC-09 Время ухода раньше времени прихода отклоняется ограничением БД"
        self.sched(1, D1); self.start(1, D1, "09:00:00")
        with self.assertRaises(DBError):
            self.end(1, D1, "08:00:00")

    def test_10_end_for_absent(self):
        "TC-10 Для сотрудника с отметкой «прогул» нельзя зафиксировать уход"
        self.sched(1, D1); val("SELECT mark_absences(:d::date, :n::timestamp)", d=D1, n=f"{D1} 17:00")
        self.assertErr("отмечен как прогульщик", "SELECT end_shift(:e,:s,:a::timestamp)", e=1, s=self.shift_id(D1), a=f"{D1} 16:00")

    def test_11_start_for_absent(self):
        "TC-11 Сотруднику с отметкой «прогул» нельзя зафиксировать приход"
        self.sched(1, D1); val("SELECT mark_absences(:d::date, :n::timestamp)", d=D1, n=f"{D1} 17:00")
        self.assertErr("уже", "SELECT start_shift(:e,:s,:a::timestamp)", e=1, s=self.shift_id(D1), a=f"{D1} 16:30")

    def test_12_status_active(self):
        "TC-12 После первого прихода смена получает статус «идёт»"
        self.sched(1, D1); self.start(1, D1, "08:00:00")
        self.assertEqual(val("SELECT status FROM shift WHERE shift_date=:d::date", d=D1), "active")


class TestAbsencesAndClose(Base):
    """Прогулы и закрытие смены"""
    def mark(self, date, now):
        return val("SELECT mark_absences(:d::date, :n::timestamp)", d=date, n=f"{date} {now}")

    def test_20_absence_after_end(self):
        "TC-20 Прогул отмечается только после планового окончания смены"
        self.sched(1, D1); self.assertEqual(self.mark(D1, "12:00"), 0); self.assertEqual(self.mark(D1, "16:01"), 1)
        self.assertEqual(self.viol(1, D1), "absent")

    def test_21_absence_idempotent(self):
        "TC-21 Повторная отметка прогулов не создаёт дубликатов"
        self.sched(1, D1); self.mark(D1, "17:00"); self.assertEqual(self.mark(D1, "18:00"), 0)

    def test_22_present_not_marked(self):
        "TC-22 Пришедший сотрудник не получает отметку «прогул»"
        self.sched(1, D1); self.sched(2, D1); self.start(1, D1, "08:00:00")
        self.assertEqual(self.mark(D1, "17:00"), 1); self.assertEqual(self.viol(1, D1), "none"); self.assertEqual(self.viol(2, D1), "absent")

    def test_23_close_requires_finish(self):
        "TC-23 Смену нельзя закрыть, пока кто-то не завершил работу"
        self.sched(1, D1); self.start(1, D1, "08:00:00")
        self.assertErr("не завершили смену", "SELECT close_shift(:d::date, 1000)", d=D1)

    def test_24_close_marks_absent_and_saves_revenue(self):
        "TC-24 Закрытие смены сохраняет выручку и отмечает не пришедших прогульщиками"
        self.sched(1, D1); self.sched(2, D1); self.start(1, D1, "08:00:00"); self.end(1, D1, "16:00:00")
        self.assertEqual(val("SELECT close_shift(:d::date, 41250.5)", d=D1), 1)
        self.assertEqual(self.viol(2, D1), "absent")
        self.assertEqual(float(val("SELECT revenue FROM shift WHERE shift_date=:d::date", d=D1)), 41250.5)
        self.assertEqual(val("SELECT status FROM shift WHERE shift_date=:d::date", d=D1), "closed")

    def test_25_close_negative_revenue(self):
        "TC-25 Отрицательная выручка отклоняется"
        self.sched(1, D1); self.assertErr("неотрицательным", "SELECT close_shift(:d::date, -1)", d=D1)

    def test_26_close_twice(self):
        "TC-26 Закрытую смену нельзя закрыть повторно"
        self.sched(1, D1); query("SELECT close_shift(:d::date, 100)", d=D1)
        self.assertErr("Открытой смены", "SELECT close_shift(:d::date, 100)", d=D1)

    def test_27_trigger_blocks_closed(self):
        "TC-27 Триггер запрещает менять отметки времени закрытой смены"
        self.sched(1, D1); self.start(1, D1, "08:00:00"); self.end(1, D1, "16:00:00"); query("SELECT close_shift(:d::date, 100)", d=D1)
        with self.assertRaises(DBError) as c:
            execute("UPDATE time_record SET actual_end = actual_end + interval '1 hour'")
        self.assertIn("закрыта", str(c.exception))

    def test_28_schedule_locked_after_close(self):
        "TC-28 В закрытой смене нельзя менять график и назначать задачи"
        self.sched(1, D1); query("SELECT close_shift(:d::date, 100)", d=D1)
        self.assertErr("закрыта", "SELECT set_schedule(1,:d::date,'09:00','17:00')", d=D1)
        self.assertErr("закрыта", "SELECT remove_schedule(1,:d::date)", d=D1)
        self.assertErr("закрыта", "SELECT assign_task(:d::date,1,'Задача')", d=D1)


class TestSchedule(Base):
    """График работы, задачи, сотрудники"""
    def test_30_schedule_creates_and_updates(self):
        "TC-30 Назначение создаёт смену и запись графика, повторное назначение меняет время без дубликата"
        a = self.sched(1, D1, "08:00", "16:00"); b = self.sched(1, D1, "10:00", "18:00")
        self.assertEqual(a, b)
        self.assertEqual(val("SELECT planned_start::text FROM schedule WHERE schedule_id=:i", i=a), "10:00:00")
        self.assertEqual(val("SELECT count(*) FROM shift WHERE shift_date=:d::date", d=D1), 1)

    def test_31_schedule_validation(self):
        "TC-31 Конец смены не может быть раньше начала; менеджера в график поставить нельзя"
        self.assertErr("позже", "SELECT set_schedule(1,:d::date,'16:00','08:00')", d=D1)
        mid = val("SELECT add_employee('Петров Пётр','manager',500)")
        self.assertErr("не найден", "SELECT set_schedule(:e,:d::date,'08:00','16:00')", e=mid, d=D1)

    def test_32_remove_schedule(self):
        "TC-32 Убрать из графика можно только того, кто ещё не отмечался"
        self.sched(1, D1); self.start(1, D1, "08:00:00")
        self.assertErr("уже отмечался", "SELECT remove_schedule(1,:d::date)", d=D1)
        self.sched(2, D1); query("SELECT remove_schedule(2,:d::date)", d=D1)
        self.assertErr("такого сотрудника нет", "SELECT remove_schedule(2,:d::date)", d=D1)

    def test_33_assign_task(self):
        "TC-33 Задача назначается только назначенному на смену исполнителю и с непустым названием"
        self.sched(1, D1)
        self.assertIsNotNone(val("SELECT assign_task(:d::date,1,'  Проверить кассу  ')", d=D1))
        self.assertEqual(val("SELECT title FROM task ORDER BY task_id DESC LIMIT 1"), "Проверить кассу")
        self.assertErr("не назначен", "SELECT assign_task(:d::date,2,'x')", d=D1)
        self.assertErr("не может быть пустым", "SELECT assign_task(:d::date,1,'   ')", d=D1)
        self.assertErr("смены нет", "SELECT assign_task(:d::date,1,'x')", d=D2)

    def test_34_add_employee_and_rate(self):
        "TC-34 Добавление сотрудника и смена ставки проверяют вводимые значения"
        self.assertIsNotNone(val("SELECT add_employee('Орлова Мария','waiter',310.5)"))
        self.assertErr("фамилию и имя", "SELECT add_employee('Орлова','waiter',300)")
        self.assertErr("положительным", "SELECT add_employee('Орлова Мария','waiter',0)")
        self.assertEqual(float(val("SELECT update_rate(1, 410)")), 410.0)
        self.assertErr("положительным", "SELECT update_rate(1, -5)")
        self.assertErr("не найден", "SELECT update_rate(999, 300)")

    def test_35_text_stored_as_data(self):
        "TC-35 Кавычки, обратный слэш и SQL-команды в тексте сохраняются как обычный текст (нет SQL-инъекции)"
        self.sched(1, D1); t = "О'Брайен \\ \"q\" ; DROP TABLE task; --"
        i = val("SELECT assign_task(:d::date,1,:t)", d=D1, t=t)
        self.assertEqual(val("SELECT title FROM task WHERE task_id=:i", i=i), t)
        self.assertGreater(val("SELECT count(*) FROM task"), 0)

    def test_36_table_constraints(self):
        "TC-36 Ограничения БД: период выплаты — первое число месяца, ставка > 0, уникальность графика"
        with self.assertRaises(DBError):
            execute("INSERT INTO payout(employee_id,period,total_amount) VALUES (1,'2027-01-15',0)")
        with self.assertRaises(DBError):
            execute("UPDATE employee SET hourly_rate = 0 WHERE employee_id = 1")
        self.sched(1, D1)
        with self.assertRaises(DBError):
            execute("INSERT INTO schedule(employee_id,shift_date,planned_start,planned_end) VALUES (1,'2027-01-11','09:00','10:00')")


class TestPayouts(Base):
    """Расчёт выплат"""
    def month(self):
        # сотрудник 1 (350 ₽/ч): 8 ч; 7,5 ч с опозданием; 7 ч с ранним уходом; прогул
        for d in (D1, D2, D3, D4):
            self.sched(1, d)
        self.start(1, D1, "08:00:00"); self.end(1, D1, "16:00:00")
        self.start(1, D2, "08:30:00"); self.end(1, D2, "16:00:00")
        self.start(1, D3, "08:00:00"); self.end(1, D3, "15:00:00")
        query("SELECT close_shift(:d::date, 1)", d=D4)

    def row(self, emp=1):
        return query("SELECT hours_worked, bonus, penalty, total_amount FROM payout WHERE employee_id=:e AND period='2027-01-01'", e=emp)[0]

    def test_40_formula(self):
        "TC-40 Итого = часы × ставка + премия − штрафы (22,5 ч × 350 + 1000 − (200+200+500) = 7975)"
        self.month(); val("SELECT add_bonus(1,'2027-01-01',1000)")
        r = self.row(); self.assertEqual((float(r["hours_worked"]), float(r["bonus"]), float(r["penalty"]), float(r["total_amount"])), (22.5, 1000, 900, 7975))

    def test_41_clamp_zero(self):
        "TC-41 Итог не может быть отрицательным: штраф за прогул без часов даёт 0"
        self.month(); query("SELECT calculate_payouts('2027-01-01')")
        r = self.row(2) if query("SELECT 1 FROM payout WHERE employee_id=2 AND period='2027-01-01'") else None
        self.sched(2, D1); query("SELECT mark_absences(:d::date,:n::timestamp)", d=D1, n=f"{D1} 20:00"); query("SELECT calculate_payouts('2027-01-01')")
        r = self.row(2); self.assertEqual((float(r["penalty"]), float(r["total_amount"])), (500, 0))

    def test_42_bonus_accumulates(self):
        "TC-42 Премии накапливаются (10 000, затем 2 500 дают 12 500); отрицательное значение исправляет ошибку"
        self.month()
        self.assertEqual(float(val("SELECT add_bonus(1,'2027-01-01',10000)")), 10000)
        self.assertEqual(float(val("SELECT add_bonus(1,'2027-01-01',2500)")), 12500)
        self.assertEqual(float(val("SELECT add_bonus(1,'2027-01-01',-500)")), 12000)
        self.assertErr("Нельзя уменьшить", "SELECT add_bonus(1,'2027-01-01',-99999)")
        self.assertErr("отличную от нуля", "SELECT add_bonus(1,'2027-01-01',0)")

    def test_43_bonus_survives_recalc(self):
        "TC-43 Повторный расчёт сохраняет премию и обновляет итог"
        self.month(); val("SELECT add_bonus(1,'2027-01-01',3000)"); a = self.row()["total_amount"]
        query("SELECT calculate_payouts('2027-01-01')"); query("SELECT calculate_payouts('2027-01-01')")
        r = self.row(); self.assertEqual((float(r["bonus"]), r["total_amount"]), (3000, a))
        self.assertEqual(val("SELECT count(*) FROM payout WHERE employee_id=1 AND period='2027-01-01'"), 1)

    def test_44_rate_change(self):
        "TC-44 Новая ставка применяется при следующем расчёте"
        self.month(); query("SELECT calculate_payouts('2027-01-01')"); a = float(self.row()["total_amount"])
        query("SELECT update_rate(1, 400)"); query("SELECT calculate_payouts('2027-01-01')")
        self.assertEqual(float(self.row()["total_amount"]) - a, 22.5 * 50)

    def test_45_manager_excluded(self):
        "TC-45 Управляющие в расчёт выплат не попадают"
        val("SELECT add_employee('Петров Пётр','manager',500)")
        query("SELECT calculate_payouts('2027-01-01')")
        self.assertEqual(val("SELECT count(*) FROM payout WHERE period='2027-01-01'"), 3)

    def test_46_seed_figures(self):
        "TC-46 Контрольные цифры тестовых данных за май 2026"
        got = {r["employee_id"]: float(r["total_amount"]) for r in query("SELECT employee_id,total_amount FROM payout WHERE period='2026-05-01'")}
        self.assertEqual(got, {1: 61313.0, 2: 45375.0, 3: 58838.4})

    def test_47_violations_view(self):
        "TC-47 Представление v_violations содержит только смены с нарушением"
        self.sched(1, D1); self.sched(2, D1); self.start(1, D1, "08:30:00"); self.start(2, D1, "08:00:00")
        rows = query("SELECT violation FROM v_violations WHERE shift_date=:d::date", d=D1)
        self.assertEqual([r["violation"] for r in rows], ["late"])


class TestWeb(Base):
    """Веб-приложение (маршруты и сообщения пользователю)"""
    @classmethod
    def setUpClass(cls):
        import app as webapp
        webapp.app.config["TESTING"] = True
        cls.c = webapp.app.test_client()

    def post(self, url, **data):
        r = self.c.post(url, data=data, follow_redirects=True); return r.status_code, r.get_data(as_text=True)

    def test_60_pages_open(self):
        "TC-60 Страницы открываются без ошибок"
        for u in ("/", "/barista", "/barista?emp=2", "/manager", "/manager?month=2026-05", "/employees"):
            self.assertEqual(self.c.get(u, follow_redirects=True).status_code, 200, u)

    def test_61_default_month(self):
        "TC-61 Панель управляющего открывается на месяце текущей смены"
        self.assertIn("Ноябрь 2026", self.c.get("/manager").get_data(as_text=True))

    def test_62_checkin_flow(self):
        "TC-62 Приход и уход через интерфейс, сообщения пользователю"
        s, t = self.post("/shift/start", emp=1, at="08:03"); self.assertIn("Приход зафиксирован", t)
        s, t = self.post("/shift/start", emp=1, at="08:04"); self.assertIn("уже начата", t)
        s, t = self.post("/shift/end", emp=1, at="16:05"); self.assertIn("Уход зафиксирован", t)

    def test_63_absent_page_regression(self):
        "TC-63 Страница бариста не падает, если у сотрудника отметка «прогул» (регрессия дефекта №3)"
        query("SELECT mark_absences('2026-11-22', '2026-11-22 23:00')")
        r = self.c.get("/barista?emp=1"); self.assertEqual(r.status_code, 200)
        self.assertIn("прогул", r.get_data(as_text=True))

    def test_64_cyrillic_form(self):
        "TC-64 Русский текст в формах сохраняется без искажений (регрессия дефекта №4)"
        s, t = self.post("/task/assign", date="2026-11-22", emp=1, title="Инвентаризация сиропов", month="2026-11")
        self.assertIn("Задача назначена", t); self.assertIn("Инвентаризация сиропов", t)
        s, t = self.post("/employees/add", name="Орлова Мария Ивановна", position="waiter", rate="310,5")
        self.assertIn("Сотрудник добавлен", t); self.assertIn("Орлова Мария Ивановна", t)

    def test_65_bad_numbers(self):
        "TC-65 Нечисловые значения в формах дают сообщение об ошибке, а не сбой"
        for url, data, text in (("/shift/close", dict(date="2026-11-22", revenue="abc", month="2026-11"), "числом"),
                                ("/payouts/bonus", dict(emp=1, bonus="abc", month="2026-11"), "числом"),
                                ("/employees/rate", dict(emp=1, rate="abc"), "числом")):
            s, t = self.post(url, **data); self.assertEqual(s, 200); self.assertIn(text, t)

    def test_66_bonus_via_ui(self):
        "TC-66 Премия через интерфейс накапливается"
        self.post("/payouts/bonus", emp=1, bonus="10 000", month="2026-06")
        s, t = self.post("/payouts/bonus", emp=1, bonus="2500", month="2026-06"); self.assertIn("12 500.00", t)

    def test_67_close_via_ui(self):
        "TC-67 Закрытие смены через интерфейс и защита закрытой смены"
        s, t = self.post("/shift/close", date="2026-11-22", revenue="41 250,5", month="2026-11"); self.assertIn("Смена закрыта", t)
        s, t = self.post("/schedule/set", emp=3, date="2026-11-22", start="09:00", end="17:00", month="2026-11")
        self.assertIn("закрыта: график изменять нельзя", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
