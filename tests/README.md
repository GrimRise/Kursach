# Автотесты WorkTime

Тесты используют только стандартный `unittest` и Flask, дополнительных пакетов не нужно.

1. Создайте пустую тестовую базу (один раз, команды те же, что для основной базы):
```
psql -U postgres -p 5432 -c "CREATE DATABASE worktime_test OWNER worktime ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'"
```
2. Задайте подключение и запустите (Windows, cmd):
```
set PGPORT=5432
set PGPASSWORD=worktime
cd tests
python test_worktime.py
```
Перед каждым тестом объекты тестовой БД пересоздаются из `sql/00_all_in_one.sql`. Основная база `worktime` не затрагивается.
