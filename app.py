import os
import sqlite3
import tempfile
from datetime import date

from flask import Flask, g, redirect, render_template, request, url_for, flash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DATABASE_URL 이 있으면 Supabase(PostgreSQL), 없으면 로컬 SQLite 사용
DATABASE_URL = os.environ.get("DATABASE_URL")

# Vercel 서버리스 환경은 /tmp 만 쓰기 가능 (인스턴스가 재시작되면 데이터 초기화)
if os.environ.get("VERCEL"):
    DB_PATH = os.path.join(tempfile.gettempdir(), "todo.db")
else:
    DB_PATH = os.path.join(BASE_DIR, "todo.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

PRIORITIES = {"high": "높음", "medium": "보통", "low": "낮음"}


class PostgresDB:
    """sqlite3 와 같은 방식(?, execute, commit)으로 쓸 수 있게 감싼 PostgreSQL 연결"""

    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row

        # Supabase 트랜잭션 풀러(6543)는 prepared statement 를 지원하지 않음
        self.conn = psycopg.connect(url, row_factory=dict_row, prepare_threshold=None)

    def execute(self, sql, params=()):
        return self.conn.execute(sql.replace("?", "%s"), params)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def connect():
    if DATABASE_URL:
        return PostgresDB(DATABASE_URL)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    if DATABASE_URL:
        sql = """
            CREATE TABLE IF NOT EXISTS todos (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """
    else:
        sql = """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """
    db = connect()
    try:
        db.execute(sql)
        db.commit()
    finally:
        db.close()


@app.route("/")
def index():
    status = request.args.get("status", "all")
    query = "SELECT * FROM todos"
    if status == "active":
        query += " WHERE done = 0"
    elif status == "done":
        query += " WHERE done = 1"
    query += """
        ORDER BY done,
                 CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                 due_date IS NULL, due_date, id DESC
    """
    db = get_db()
    todos = db.execute(query).fetchall()
    counts = db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(done), 0) AS done FROM todos"
    ).fetchone()
    return render_template(
        "index.html",
        todos=todos,
        status=status,
        counts=counts,
        priorities=PRIORITIES,
        today=date.today().isoformat(),
    )


@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    priority = request.form.get("priority", "medium")
    due_date = request.form.get("due_date") or None
    if not title:
        flash("할 일을 입력해 주세요.")
        return redirect(url_for("index"))
    if priority not in PRIORITIES:
        priority = "medium"
    db = get_db()
    db.execute(
        "INSERT INTO todos (title, priority, due_date) VALUES (?, ?, ?)",
        (title, priority, due_date),
    )
    db.commit()
    return redirect(url_for("index"))


@app.route("/toggle/<int:todo_id>", methods=["POST"])
def toggle(todo_id):
    db = get_db()
    db.execute("UPDATE todos SET done = 1 - done WHERE id = ?", (todo_id,))
    db.commit()
    return redirect(request.referrer or url_for("index"))


@app.route("/edit/<int:todo_id>", methods=["GET", "POST"])
def edit(todo_id):
    db = get_db()
    todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if todo is None:
        flash("해당 할 일을 찾을 수 없습니다.")
        return redirect(url_for("index"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        priority = request.form.get("priority", "medium")
        due_date = request.form.get("due_date") or None
        if not title:
            flash("할 일을 입력해 주세요.")
            return redirect(url_for("edit", todo_id=todo_id))
        if priority not in PRIORITIES:
            priority = "medium"
        db.execute(
            "UPDATE todos SET title = ?, priority = ?, due_date = ? WHERE id = ?",
            (title, priority, due_date, todo_id),
        )
        db.commit()
        flash("수정되었습니다.")
        return redirect(url_for("index"))

    return render_template("edit.html", todo=todo, priorities=PRIORITIES)


@app.route("/delete/<int:todo_id>", methods=["POST"])
def delete(todo_id):
    db = get_db()
    db.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    db.commit()
    return redirect(request.referrer or url_for("index"))


@app.route("/clear-done", methods=["POST"])
def clear_done():
    db = get_db()
    db.execute("DELETE FROM todos WHERE done = 1")
    db.commit()
    flash("완료된 할 일을 모두 삭제했습니다.")
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
