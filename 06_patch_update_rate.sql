-- Патч для уже созданной БД: изменение ставки сотрудника
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
