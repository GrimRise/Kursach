-- Сброс демо-смены 22.11.2026 к начальному состоянию
DELETE FROM time_record WHERE shift_id = (SELECT shift_id FROM shift WHERE shift_date = '2026-11-22');
UPDATE shift SET status = 'open', revenue = NULL WHERE shift_date = '2026-11-22';
DELETE FROM schedule WHERE shift_date = '2026-11-22' AND employee_id NOT IN (1, 2);
DELETE FROM task WHERE shift_id = (SELECT shift_id FROM shift WHERE shift_date = '2026-11-22')
   AND title NOT IN ('Включить кофемашину и прогреть группы', 'Проверить наличие зерна и молока',
                     'Протереть гостевые столики', 'Снять показания счётчиков');
UPDATE task SET status = CASE WHEN title = 'Снять показания счётчиков' THEN 'done'::task_status ELSE 'new'::task_status END
 WHERE shift_id = (SELECT shift_id FROM shift WHERE shift_date = '2026-11-22');
