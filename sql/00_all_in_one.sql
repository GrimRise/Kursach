-- WorkTime: полный скрипт создания БД (PostgreSQL 16). Порядок: схема → логика → тестовые данные

-- WorkTime: физическая схема БД (PostgreSQL 16)
-- Типы-перечисления
CREATE TYPE position_type  AS ENUM ('barista', 'waiter', 'manager');
CREATE TYPE shift_status   AS ENUM ('planned', 'open', 'active', 'closed', 'calculated');
CREATE TYPE violation_type AS ENUM ('none', 'late', 'early_leave', 'absent');
CREATE TYPE task_status    AS ENUM ('new', 'done');

-- Сотрудник
CREATE TABLE employee (
    employee_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name    varchar(100)  NOT NULL,
    position     position_type NOT NULL,
    hourly_rate  numeric(8,2)  NOT NULL CHECK (hourly_rate > 0)
);

-- Рабочая смена (один рабочий день заведения)
CREATE TABLE shift (
    shift_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_date  date          NOT NULL UNIQUE,
    status      shift_status  NOT NULL DEFAULT 'planned',
    revenue     numeric(10,2) CHECK (revenue >= 0)
);

-- График (плановая смена сотрудника)
CREATE TABLE schedule (
    schedule_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id    integer NOT NULL REFERENCES employee(employee_id),
    shift_date     date    NOT NULL,
    planned_start  time    NOT NULL,
    planned_end    time    NOT NULL,
    CONSTRAINT chk_schedule_time CHECK (planned_end > planned_start),
    CONSTRAINT uq_schedule UNIQUE (employee_id, shift_date)
);

-- Отметка времени (факт прихода и ухода)
CREATE TABLE time_record (
    record_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id   integer NOT NULL REFERENCES employee(employee_id),
    shift_id      integer NOT NULL REFERENCES shift(shift_id),
    actual_start  timestamp,
    actual_end    timestamp,
    violation     violation_type NOT NULL DEFAULT 'none',
    CONSTRAINT chk_actual_time CHECK (actual_end IS NULL OR actual_end > actual_start),
    CONSTRAINT chk_absent CHECK (
        (violation = 'absent' AND actual_start IS NULL AND actual_end IS NULL)
        OR (violation <> 'absent' AND actual_start IS NOT NULL)),
    CONSTRAINT uq_time_record UNIQUE (employee_id, shift_id)
);

-- Задача
CREATE TABLE task (
    task_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_id     integer NOT NULL REFERENCES shift(shift_id),
    executor_id  integer NOT NULL REFERENCES employee(employee_id),
    title        varchar(150) NOT NULL,
    status       task_status  NOT NULL DEFAULT 'new'
);

-- Выплата
CREATE TABLE payout (
    payout_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id   integer NOT NULL REFERENCES employee(employee_id),
    period        date    NOT NULL CHECK (period = date_trunc('month', period)::date),
    hours_worked  numeric(6,2)  NOT NULL DEFAULT 0 CHECK (hours_worked >= 0),
    bonus         numeric(10,2) NOT NULL DEFAULT 0 CHECK (bonus >= 0),
    penalty       numeric(10,2) NOT NULL DEFAULT 0 CHECK (penalty >= 0),
    total_amount  numeric(10,2) NOT NULL CHECK (total_amount >= 0),
    CONSTRAINT uq_payout UNIQUE (employee_id, period)
);

-- Индексы (внешние ключи и частые фильтры)
CREATE INDEX idx_schedule_date     ON schedule(shift_date);
CREATE INDEX idx_time_record_shift ON time_record(shift_id);
CREATE INDEX idx_time_record_viol  ON time_record(violation) WHERE violation <> 'none';
CREATE INDEX idx_task_shift        ON task(shift_id);
CREATE INDEX idx_task_executor     ON task(executor_id);

-- Триггер: в закрытой смене отметки времени менять нельзя
CREATE FUNCTION fn_block_closed_shift() RETURNS trigger AS $$
DECLARE st shift_status;
BEGIN
    SELECT status INTO st FROM shift WHERE shift_id = NEW.shift_id;
    IF st IN ('closed', 'calculated') THEN
        RAISE EXCEPTION 'Смена % закрыта: отметки времени изменять нельзя', NEW.shift_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_block_closed_shift
BEFORE INSERT OR UPDATE ON time_record
FOR EACH ROW EXECUTE FUNCTION fn_block_closed_shift();

-- Начать смену: фиксирует приход, определяет опоздание (допуск 10 минут)
CREATE FUNCTION start_shift(p_employee integer, p_shift integer,
                            p_at timestamp DEFAULT localtimestamp) RETURNS integer AS $$
DECLARE v_date date; v_plan time; v_viol violation_type := 'none'; v_id integer;
BEGIN
    SELECT s.shift_date, sc.planned_start INTO v_date, v_plan
    FROM shift s JOIN schedule sc ON sc.shift_date = s.shift_date
    WHERE s.shift_id = p_shift AND sc.employee_id = p_employee AND s.status IN ('open','active');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Сотрудник % не назначен на открытую смену %', p_employee, p_shift;
    END IF;
    IF EXISTS (SELECT 1 FROM time_record WHERE employee_id = p_employee AND shift_id = p_shift AND violation = 'absent') THEN
        RAISE EXCEPTION 'Сотрудник уже отмечен как прогульщик в этой смене: приход зафиксировать нельзя';
    END IF;
    IF EXISTS (SELECT 1 FROM time_record WHERE employee_id = p_employee AND shift_id = p_shift) THEN
        RAISE EXCEPTION 'Смена уже начата: приход зафиксирован';
    END IF;
    IF p_at > v_date + v_plan + interval '10 minutes' THEN v_viol := 'late'; END IF;
    INSERT INTO time_record(employee_id, shift_id, actual_start, violation)
    VALUES (p_employee, p_shift, p_at, v_viol) RETURNING record_id INTO v_id;
    UPDATE shift SET status = 'active' WHERE shift_id = p_shift AND status = 'open';
    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- Завершить смену: фиксирует уход, определяет ранний уход
CREATE FUNCTION end_shift(p_employee integer, p_shift integer,
                          p_at timestamp DEFAULT localtimestamp) RETURNS void AS $$
DECLARE v_date date; v_plan_end time;
BEGIN
    SELECT s.shift_date, sc.planned_end INTO v_date, v_plan_end
    FROM shift s JOIN schedule sc ON sc.shift_date = s.shift_date
    WHERE s.shift_id = p_shift AND sc.employee_id = p_employee;
    IF EXISTS (SELECT 1 FROM time_record WHERE employee_id = p_employee AND shift_id = p_shift AND violation = 'absent') THEN
        RAISE EXCEPTION 'Сотрудник отмечен как прогульщик в этой смене: уход зафиксировать нельзя';
    END IF;
    IF EXISTS (SELECT 1 FROM time_record WHERE employee_id = p_employee AND shift_id = p_shift AND actual_end IS NOT NULL) THEN
        RAISE EXCEPTION 'Смена уже завершена: уход зафиксирован';
    END IF;
    UPDATE time_record
       SET actual_end = p_at,
           violation = CASE WHEN violation = 'none' AND p_at < v_date + v_plan_end - interval '10 minutes'
                            THEN 'early_leave' ELSE violation END
     WHERE employee_id = p_employee AND shift_id = p_shift AND actual_end IS NULL;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Нет начатой смены для сотрудника % (смена %)', p_employee, p_shift;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Рассчитать ЗП за месяц.
-- Итого = часы × ставка + премия − штрафы (опоздание 200 ₽, ранний уход 200 ₽, прогул 500 ₽).
-- Ранее введённая премия сохраняется при пересчёте.
CREATE FUNCTION calculate_payouts(p_period date) RETURNS integer AS $$
DECLARE v_from date := date_trunc('month', p_period)::date; v_cnt integer;
BEGIN
    INSERT INTO payout(employee_id, period, hours_worked, bonus, penalty, total_amount)
    SELECT e.employee_id, v_from,
           COALESCE(h.hrs, 0),
           COALESCE(p.bonus, 0),
           COALESCE(h.pen, 0),
           GREATEST(ROUND(COALESCE(h.hrs,0) * e.hourly_rate, 2) + COALESCE(p.bonus,0) - COALESCE(h.pen,0), 0)
    FROM employee e
    LEFT JOIN (
        SELECT tr.employee_id,
               ROUND(SUM(EXTRACT(EPOCH FROM (tr.actual_end - tr.actual_start)) / 3600)::numeric, 2) AS hrs,
               SUM(CASE tr.violation WHEN 'late' THEN 200 WHEN 'early_leave' THEN 200
                                     WHEN 'absent' THEN 500 ELSE 0 END) AS pen
        FROM time_record tr JOIN shift s ON s.shift_id = tr.shift_id
        WHERE s.shift_date >= v_from AND s.shift_date < v_from + interval '1 month'
        GROUP BY tr.employee_id) h ON h.employee_id = e.employee_id
    LEFT JOIN payout p ON p.employee_id = e.employee_id AND p.period = v_from
    WHERE e.position <> 'manager'
    ON CONFLICT (employee_id, period) DO UPDATE
        SET hours_worked = EXCLUDED.hours_worked, penalty = EXCLUDED.penalty,
            total_amount = EXCLUDED.total_amount;
    GET DIAGNOSTICS v_cnt = ROW_COUNT;
    RETURN v_cnt;
END;
$$ LANGUAGE plpgsql;

-- Представление: отчёт о нарушениях дисциплины
CREATE VIEW v_violations AS
SELECT s.shift_date, e.full_name, tr.violation,
       sc.planned_start, sc.planned_end,
       tr.actual_start::time AS actual_start, tr.actual_end::time AS actual_end
FROM time_record tr
JOIN shift s     ON s.shift_id = tr.shift_id
JOIN employee e  ON e.employee_id = tr.employee_id
LEFT JOIN schedule sc ON sc.employee_id = tr.employee_id AND sc.shift_date = s.shift_date
WHERE tr.violation <> 'none';

-- ===== Функции управляющего =====

-- Поставить сотрудника в график на дату (или изменить время). Смена на дату создаётся при необходимости.
CREATE FUNCTION set_schedule(p_employee integer, p_date date, p_start time, p_end time) RETURNS integer AS $$
DECLARE v_status shift_status; v_id integer;
BEGIN
    IF p_end <= p_start THEN
        RAISE EXCEPTION 'Время окончания должно быть позже времени начала';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM employee WHERE employee_id = p_employee AND position <> 'manager') THEN
        RAISE EXCEPTION 'Сотрудник % не найден или не работает в смене', p_employee;
    END IF;
    SELECT status INTO v_status FROM shift WHERE shift_date = p_date;
    IF v_status IN ('closed', 'calculated') THEN
        RAISE EXCEPTION 'Смена % закрыта: график изменять нельзя', to_char(p_date, 'DD.MM.YYYY');
    END IF;
    IF NOT FOUND THEN
        INSERT INTO shift(shift_date, status) VALUES (p_date, 'open');
    END IF;
    INSERT INTO schedule(employee_id, shift_date, planned_start, planned_end)
    VALUES (p_employee, p_date, p_start, p_end)
    ON CONFLICT (employee_id, shift_date)
    DO UPDATE SET planned_start = EXCLUDED.planned_start, planned_end = EXCLUDED.planned_end
    RETURNING schedule_id INTO v_id;
    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- Убрать сотрудника из графика (если он ещё не отмечался в этой смене)
CREATE FUNCTION remove_schedule(p_employee integer, p_date date) RETURNS void AS $$
DECLARE v_status shift_status;
BEGIN
    SELECT status INTO v_status FROM shift WHERE shift_date = p_date;
    IF v_status IN ('closed', 'calculated') THEN
        RAISE EXCEPTION 'Смена % закрыта: график изменять нельзя', to_char(p_date, 'DD.MM.YYYY');
    END IF;
    IF EXISTS (SELECT 1 FROM time_record tr JOIN shift s USING (shift_id)
               WHERE tr.employee_id = p_employee AND s.shift_date = p_date) THEN
        RAISE EXCEPTION 'Сотрудник уже отмечался в этой смене: убрать его из графика нельзя';
    END IF;
    DELETE FROM schedule WHERE employee_id = p_employee AND shift_date = p_date;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'В графике на % такого сотрудника нет', to_char(p_date, 'DD.MM.YYYY');
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Автоматически отметить прогулы: назначен в график, плановое окончание уже прошло, прихода нет
CREATE FUNCTION mark_absences(p_date date, p_now timestamp DEFAULT localtimestamp) RETURNS integer AS $$
DECLARE v_shift integer; v_cnt integer;
BEGIN
    SELECT shift_id INTO v_shift FROM shift WHERE shift_date = p_date AND status IN ('open', 'active');
    IF NOT FOUND THEN
        RETURN 0;
    END IF;
    INSERT INTO time_record(employee_id, shift_id, violation)
    SELECT sc.employee_id, v_shift, 'absent'
    FROM schedule sc
    WHERE sc.shift_date = p_date
      AND p_date + sc.planned_end < p_now
      AND NOT EXISTS (SELECT 1 FROM time_record tr
                      WHERE tr.shift_id = v_shift AND tr.employee_id = sc.employee_id);
    GET DIAGNOSTICS v_cnt = ROW_COUNT;
    RETURN v_cnt;
END;
$$ LANGUAGE plpgsql;

-- Закрыть смену: фиксирует выручку, не пришедшие помечаются прогульщиками, отметки блокируются
CREATE FUNCTION close_shift(p_date date, p_revenue numeric) RETURNS integer AS $$
DECLARE v_shift integer; v_abs integer;
BEGIN
    IF p_revenue IS NULL OR p_revenue < 0 THEN
        RAISE EXCEPTION 'Выручка должна быть неотрицательным числом';
    END IF;
    SELECT shift_id INTO v_shift FROM shift WHERE shift_date = p_date AND status IN ('open', 'active');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Открытой смены на % нет', to_char(p_date, 'DD.MM.YYYY');
    END IF;
    IF EXISTS (SELECT 1 FROM time_record WHERE shift_id = v_shift AND actual_start IS NOT NULL AND actual_end IS NULL) THEN
        RAISE EXCEPTION 'Есть сотрудники, которые не завершили смену: закрыть смену нельзя';
    END IF;
    v_abs := mark_absences(p_date, 'infinity'::timestamp);
    UPDATE shift SET status = 'closed', revenue = p_revenue WHERE shift_id = v_shift;
    RETURN v_abs;
END;
$$ LANGUAGE plpgsql;

-- Назначить задачу исполнителю на смену
CREATE FUNCTION assign_task(p_date date, p_executor integer, p_title text) RETURNS integer AS $$
DECLARE v_shift integer; v_status shift_status; v_id integer;
BEGIN
    IF btrim(coalesce(p_title, '')) = '' THEN
        RAISE EXCEPTION 'Название задачи не может быть пустым';
    END IF;
    SELECT shift_id, status INTO v_shift, v_status FROM shift WHERE shift_date = p_date;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'На % смены нет: сначала поставьте сотрудников в график', to_char(p_date, 'DD.MM.YYYY');
    END IF;
    IF v_status IN ('closed', 'calculated') THEN
        RAISE EXCEPTION 'Смена закрыта: задачи добавлять нельзя';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM schedule WHERE employee_id = p_executor AND shift_date = p_date) THEN
        RAISE EXCEPTION 'Исполнитель не назначен на смену %', to_char(p_date, 'DD.MM.YYYY');
    END IF;
    INSERT INTO task(shift_id, executor_id, title) VALUES (v_shift, p_executor, btrim(p_title))
    RETURNING task_id INTO v_id;
    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- Добавить премию сотруднику за месяц: сумма прибавляется к уже назначенной, итог пересчитывается.
-- Отрицательное значение уменьшает премию (исправление ошибки), но итоговая премия не может стать меньше нуля.
-- Возвращает общую сумму премий сотрудника за месяц.
CREATE FUNCTION add_bonus(p_employee integer, p_period date, p_amount numeric) RETURNS numeric AS $$
DECLARE v_from date := date_trunc('month', p_period)::date; v_total numeric;
BEGIN
    IF p_amount IS NULL OR p_amount = 0 THEN
        RAISE EXCEPTION 'Введите сумму премии, отличную от нуля';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM employee WHERE employee_id = p_employee AND position <> 'manager') THEN
        RAISE EXCEPTION 'Сотрудник % не найден', p_employee;
    END IF;
    IF p_amount < 0 AND COALESCE((SELECT bonus FROM payout WHERE employee_id = p_employee AND period = v_from), 0) + p_amount < 0 THEN
        RAISE EXCEPTION 'Нельзя уменьшить премию больше, чем назначено';
    END IF;
    INSERT INTO payout(employee_id, period, bonus, total_amount)
    VALUES (p_employee, v_from, GREATEST(p_amount, 0), 0)
    ON CONFLICT (employee_id, period) DO UPDATE SET bonus = payout.bonus + p_amount;
    PERFORM calculate_payouts(v_from);
    SELECT bonus INTO v_total FROM payout WHERE employee_id = p_employee AND period = v_from;
    RETURN v_total;
END;
$$ LANGUAGE plpgsql;

-- Добавить сотрудника
CREATE FUNCTION add_employee(p_name text, p_position position_type, p_rate numeric) RETURNS integer AS $$
DECLARE v_id integer;
BEGIN
    IF array_length(regexp_split_to_array(btrim(p_name), '\s+'), 1) < 2 THEN
        RAISE EXCEPTION 'Укажите фамилию и имя сотрудника';
    END IF;
    IF p_rate IS NULL OR p_rate <= 0 THEN
        RAISE EXCEPTION 'Ставка должна быть положительным числом';
    END IF;
    INSERT INTO employee(full_name, position, hourly_rate) VALUES (btrim(p_name), p_position, p_rate)
    RETURNING employee_id INTO v_id;
    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- Изменить почасовую ставку сотрудника. Действует для следующих расчётов выплат
-- (при пересчёте месяца ставка применяется ко всем часам месяца).
CREATE FUNCTION update_rate(p_employee integer, p_rate numeric) RETURNS numeric AS $$
BEGIN
    IF p_rate IS NULL OR p_rate <= 0 THEN
        RAISE EXCEPTION 'Ставка должна быть положительным числом';
    END IF;
    UPDATE employee SET hourly_rate = p_rate WHERE employee_id = p_employee;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Сотрудник % не найден', p_employee;
    END IF;
    RETURN p_rate;
END;
$$ LANGUAGE plpgsql;

INSERT INTO employee(full_name, position, hourly_rate) VALUES
 ('Антясов Сергей', 'barista', 350),
 ('Иванов Петр',    'waiter',  300),
 ('Макарова Анна',  'barista', 320);

-- Май 2026: смены, график
INSERT INTO shift(shift_date, status, revenue)
SELECT d::date, 'open', 38000 + (EXTRACT(day FROM d)::int * 731) % 9000
FROM generate_series('2026-05-01'::date, '2026-05-31'::date, '1 day') d;

INSERT INTO schedule(employee_id, shift_date, planned_start, planned_end)
SELECT e.employee_id, d::date, '08:00', '16:00'
FROM generate_series('2026-05-01'::date, '2026-05-31'::date, '1 day') d
CROSS JOIN employee e
WHERE (EXTRACT(day FROM d)::int + e.employee_id) % 3 <> 0 OR EXTRACT(day FROM d)::int = 12;

-- Отметки времени
INSERT INTO time_record(employee_id, shift_id, actual_start, actual_end, violation)
SELECT sc.employee_id, s.shift_id,
  CASE v WHEN 'absent' THEN NULL
         WHEN 'late' THEN sc.shift_date + sc.planned_start + ((12 + dd % 9) || ' minutes')::interval
         ELSE sc.shift_date + sc.planned_start - ((dd % 6) || ' minutes')::interval END,
  CASE v WHEN 'absent' THEN NULL
         WHEN 'early_leave' THEN sc.shift_date + sc.planned_end - interval '40 minutes'
         ELSE sc.shift_date + sc.planned_end + ((dd % 4 * 3) || ' minutes')::interval END,
  v::violation_type
FROM (
  SELECT sc.*, EXTRACT(day FROM sc.shift_date)::int AS dd,
    CASE
      WHEN EXTRACT(day FROM sc.shift_date)::int = 12 THEN CASE WHEN sc.employee_id = 3 THEN 'late' ELSE 'none' END
      WHEN (EXTRACT(day FROM sc.shift_date)::int*13 + sc.employee_id*5) % 31 = 0 THEN 'absent'
      WHEN (EXTRACT(day FROM sc.shift_date)::int*7  + sc.employee_id*3) % 13 = 0 THEN 'late'
      WHEN (EXTRACT(day FROM sc.shift_date)::int*5  + sc.employee_id)   % 19 = 0 THEN 'early_leave'
      ELSE 'none' END AS v
  FROM schedule sc) sc
JOIN shift s ON s.shift_date = sc.shift_date;

-- Задачи: три регулярные на каждую смену, исполнители по очереди
INSERT INTO task(shift_id, executor_id, title, status)
SELECT s.shift_id, w.employee_id, t.title, 'done'
FROM shift s
JOIN LATERAL (SELECT array_agg(employee_id ORDER BY employee_id) AS ids
              FROM schedule WHERE shift_date = s.shift_date) a ON true
CROSS JOIN (VALUES (0,'Включить кофемашину и прогреть группы'),
                   (1,'Проверить наличие зерна и молока'),
                   (2,'Протереть гостевые столики')) t(n, title)
JOIN LATERAL (SELECT a.ids[1 + t.n % array_length(a.ids,1)] AS employee_id) w ON true
WHERE s.shift_date BETWEEN '2026-05-01' AND '2026-05-31';

INSERT INTO task(shift_id, executor_id, title, status)
SELECT shift_id, 1, 'Настройка помола', 'done' FROM shift WHERE shift_date = '2026-05-12';
INSERT INTO task(shift_id, executor_id, title, status)
SELECT shift_id, 3, 'Инвентаризация витрины', 'done' FROM shift WHERE shift_date = '2026-05-12';

-- прогул сотрудника 20.05.2026
UPDATE time_record SET violation='absent', actual_start=NULL, actual_end=NULL
 WHERE employee_id=2 AND shift_id=(SELECT shift_id FROM shift WHERE shift_date='2026-05-20');

UPDATE shift SET status = 'closed' WHERE shift_date BETWEEN '2026-05-01' AND '2026-05-31';

-- Расчёт за май с премиями за разовые поручения
SELECT calculate_payouts('2026-05-01');
UPDATE payout SET bonus = CASE employee_id WHEN 1 THEN 2500 WHEN 2 THEN 1000 ELSE 3200 END
 WHERE period = '2026-05-01';
SELECT calculate_payouts('2026-05-01');
UPDATE shift SET status = 'calculated' WHERE shift_date BETWEEN '2026-05-01' AND '2026-05-31';

-- Текущая смена для демонстрации работы кнопок
INSERT INTO shift(shift_date, status) VALUES ('2026-11-22', 'open');
INSERT INTO schedule(employee_id, shift_date, planned_start, planned_end) VALUES
 (1, '2026-11-22', '08:00', '16:00'), (2, '2026-11-22', '08:00', '16:00');
INSERT INTO task(shift_id, executor_id, title) SELECT shift_id, 1, t FROM shift,
 (VALUES ('Включить кофемашину и прогреть группы'), ('Проверить наличие зерна и молока'),
         ('Протереть гостевые столики'), ('Снять показания счётчиков')) v(t)
 WHERE shift_date = '2026-11-22';
UPDATE task SET status = 'done' WHERE title = 'Снять показания счётчиков';
