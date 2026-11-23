-- Патч для уже созданной БД: понятные сообщения при повторной отметке прихода и ухода
CREATE OR REPLACE FUNCTION start_shift(p_employee integer, p_shift integer,
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

CREATE OR REPLACE FUNCTION end_shift(p_employee integer, p_shift integer,
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
