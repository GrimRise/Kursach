-- Патч для уже созданной БД: премии теперь накапливаются
DROP FUNCTION IF EXISTS set_bonus(integer, date, numeric);
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
