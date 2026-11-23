"""Слой доступа к БД WorkTime: параметризованные запросы к PostgreSQL через клиент psql.
Параметры подключения: переменные PGHOST, PGPORT, PGUSER, PGDATABASE, PGPASSWORD.
Значения передаются в psql как переменные (\\set), а затем подставляются как :'name',
то есть не склеиваются со строкой запроса. Они идут через стандартный ввод в UTF-8,
поэтому русский текст одинаково работает в Windows и Linux."""
import json, subprocess, re, os

PSQL = ["psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1",
        "-h", os.environ.get("PGHOST", "localhost"), "-p", os.environ.get("PGPORT", "5432"),
        "-U", os.environ.get("PGUSER", "worktime"), "-d", os.environ.get("PGDATABASE", "worktime")]
ENV = dict(os.environ, PGCLIENTENCODING="UTF8")   # клиент psql всегда работает в UTF-8
ERR = re.compile(r"(?:ERROR|ОШИБКА):\s+(.*)")

class DBError(Exception):
    pass

def _lit(v):
    """Значение параметра как строка в одинарных кавычках для команды \\set."""
    s = "" if v is None else str(v)
    s = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    return f"'{s}'"

def _run(sql, params):
    for k in params:  # :name -> :'name' (psql сам экранирует значение как строковый литерал)
        sql = re.sub(rf"(?<!:):{k}\b", f":'{k}'", sql)
    head = "".join(f"\\set {k} {_lit(v)}\n" for k, v in params.items())
    r = subprocess.run(PSQL, input=head + sql, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=ENV)
    if r.returncode != 0:
        m = ERR.search(r.stderr)
        raise DBError(m.group(1).strip() if m else r.stderr.strip())
    return r.stdout

def query(sql, **params):
    """Выполняет SELECT (или вызов функции) и возвращает список словарей."""
    out = _run(f"SELECT COALESCE(json_agg(t), '[]'::json) FROM ({sql}) t;", params)
    return json.loads(out.strip() or "[]")

def execute(sql, **params):
    """Выполняет INSERT/UPDATE/DELETE без возврата строк."""
    _run(sql, params)
