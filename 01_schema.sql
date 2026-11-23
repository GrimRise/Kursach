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
