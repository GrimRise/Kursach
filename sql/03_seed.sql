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
