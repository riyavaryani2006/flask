"""Flask To-Do app: signup, login and per-user task management (SQLite).

Only Flask (and its Werkzeug dependency) is required.

Run:
    python app.py
or
    flask --app app run --debug
"""
import hmac
import os
import re
import secrets
import sqlite3
from datetime import date
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

PRIORITIES = ("low", "medium", "high")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8

SORTS = {
    "newest": "completed ASC, created_at DESC, id DESC",
    "oldest": "completed ASC, created_at ASC, id ASC",
    "due": "completed ASC, due_date IS NULL, due_date ASC, id DESC",
    "priority": (
        "completed ASC, "
        "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        "id DESC"
    ),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    priority     TEXT NOT NULL DEFAULT 'medium'
                 CHECK (priority IN ('low', 'medium', 'high')),
    due_date     TEXT,
    completed    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
"""

# Used to spend roughly the same time on unknown usernames as on real ones.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _load_or_create_secret(instance_path):
    """Return a persistent random secret key (stored in the instance folder)."""
    os.makedirs(instance_path, exist_ok=True)
    path = os.path.join(instance_path, "secret_key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            value = fh.read().strip()
            if value:
                return value
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return value


def init_db(database_path):
    conn = sqlite3.connect(database_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_db():
    from flask import current_app

    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def safe_next(target):
    """Only allow same-site relative redirects (prevents open redirects)."""
    if not target or "\\" in target:
        return None
    parts = urlparse(target)
    if parts.scheme or parts.netloc:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    return target


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            flash("Please log in to continue.", "info")
            nxt = request.full_path if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))
        return view(*args, **kwargs)

    return wrapped


def like_pattern(text):
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def read_task_form(form):
    """Validate task fields from a submitted form. Returns (data, errors)."""
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    priority = form.get("priority", "medium")
    due_raw = form.get("due_date", "").strip()
    errors = []

    if not title:
        errors.append("Title is required.")
    elif len(title) > 200:
        errors.append("Title must be 200 characters or fewer.")
    if len(description) > 2000:
        errors.append("Description must be 2000 characters or fewer.")
    if priority not in PRIORITIES:
        errors.append("Priority must be low, medium or high.")
        priority = "medium"

    due_date = None
    if due_raw:
        try:
            due_date = date.fromisoformat(due_raw).isoformat()
        except ValueError:
            errors.append("Due date must be a valid date.")

    data = {
        "title": title,
        "description": description,
        "priority": priority,
        "due_date": due_date,
    }
    return data, errors


def validate_new_password(password, confirm):
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password != confirm:
        return "Passwords do not match."
    return None


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------
def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DATABASE=os.path.join(app.instance_path, "todo.sqlite"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_or_create_secret(app.instance_path)

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
    init_db(app.config["DATABASE"])

    # ---- request lifecycle ------------------------------------------------
    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.before_request
    def load_user_and_check_csrf():
        if request.endpoint == "static":
            return
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            g.user = (
                get_db()
                .execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,))
                .fetchone()
            )
            if g.user is None:
                session.clear()

        if request.method == "POST":
            expected = session.get("_csrf", "")
            sent = request.form.get("_csrf", "")
            if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
                abort(400, "Invalid or missing CSRF token. Reload the page and try again.")

    @app.context_processor
    def inject_globals():
        return {"csrf_token": csrf_token, "today": date.today().isoformat()}

    @app.errorhandler(400)
    @app.errorhandler(404)
    def http_error(error):
        return (
            render_template("error.html", code=error.code, message=error.description),
            error.code,
        )

    # ---- auth -------------------------------------------------------------
    @app.route("/signup", methods=("GET", "POST"))
    def signup():
        if g.user:
            return redirect(url_for("index"))
        form = {"username": "", "email": ""}
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            form = {"username": username, "email": email}

            error = None
            if not USERNAME_RE.match(username):
                error = "Username must be 3-30 characters: letters, numbers or underscore."
            elif not EMAIL_RE.match(email) or len(email) > 254:
                error = "Enter a valid email address."
            else:
                error = validate_new_password(password, confirm)

            if error is None:
                db = get_db()
                try:
                    cur = db.execute(
                        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                        (username, email, generate_password_hash(password)),
                    )
                    db.commit()
                except sqlite3.IntegrityError:
                    error = "That username or email is already registered."
                else:
                    session.clear()
                    session["user_id"] = cur.lastrowid
                    flash("Welcome! Your account is ready.", "success")
                    return redirect(url_for("index"))
            flash(error, "error")
        return render_template("signup.html", form=form)

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if g.user:
            return redirect(url_for("index"))
        next_url = request.values.get("next", "")
        identifier = ""
        if request.method == "POST":
            identifier = request.form.get("identifier", "").strip()
            password = request.form.get("password", "")
            user = (
                get_db()
                .execute(
                    "SELECT * FROM users WHERE username = ? OR email = ?",
                    (identifier, identifier),
                )
                .fetchone()
            )
            if user is None:
                check_password_hash(_DUMMY_HASH, password)
                ok = False
            else:
                ok = check_password_hash(user["password_hash"], password)

            if ok:
                session.clear()  # new session on login (prevents fixation)
                session["user_id"] = user["id"]
                return redirect(safe_next(next_url) or url_for("index"))
            flash("Invalid username/email or password.", "error")
        return render_template("login.html", identifier=identifier, next_url=next_url)

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("login"))

    # ---- tasks ------------------------------------------------------------
    def get_task_or_404(task_id):
        task = (
            get_db()
            .execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, g.user["id"]),
            )
            .fetchone()
        )
        if task is None:
            abort(404, "Task not found.")
        return task

    @app.route("/")
    @login_required
    def index():
        db = get_db()
        uid = g.user["id"]

        status = request.args.get("status", "all")
        priority = request.args.get("priority", "")
        q = request.args.get("q", "").strip()
        sort = request.args.get("sort", "newest")
        if sort not in SORTS:
            sort = "newest"

        where = ["user_id = ?"]
        params = [uid]
        if status == "active":
            where.append("completed = 0")
        elif status == "completed":
            where.append("completed = 1")
        else:
            status = "all"
        if priority in PRIORITIES:
            where.append("priority = ?")
            params.append(priority)
        else:
            priority = ""
        if q:
            where.append("(title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')")
            pattern = like_pattern(q)
            params.extend([pattern, pattern])

        tasks = db.execute(
            f"SELECT * FROM tasks WHERE {' AND '.join(where)} ORDER BY {SORTS[sort]}",
            params,
        ).fetchall()

        stats = db.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(completed = 0), 0) AS active,
                   COALESCE(SUM(completed = 1), 0) AS done,
                   COALESCE(SUM(completed = 0 AND due_date IS NOT NULL
                                AND due_date < ?), 0) AS overdue
            FROM tasks WHERE user_id = ?
            """,
            (date.today().isoformat(), uid),
        ).fetchone()

        return render_template(
            "index.html",
            tasks=tasks,
            stats=stats,
            status=status,
            priority=priority,
            q=q,
            sort=sort,
            priorities=PRIORITIES,
        )

    @app.post("/tasks/add")
    @login_required
    def add_task():
        data, errors = read_task_form(request.form)
        if errors:
            for message in errors:
                flash(message, "error")
        else:
            db = get_db()
            db.execute(
                "INSERT INTO tasks (user_id, title, description, priority, due_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    g.user["id"],
                    data["title"],
                    data["description"],
                    data["priority"],
                    data["due_date"],
                ),
            )
            db.commit()
            flash("Task added.", "success")
        return redirect(safe_next(request.form.get("next")) or url_for("index"))

    @app.route("/tasks/<int:task_id>/edit", methods=("GET", "POST"))
    @login_required
    def edit_task(task_id):
        task = get_task_or_404(task_id)
        form = dict(task)
        if request.method == "POST":
            data, errors = read_task_form(request.form)
            completed = 1 if request.form.get("completed") else 0
            form = {**data, "id": task_id, "completed": completed}
            if errors:
                for message in errors:
                    flash(message, "error")
            else:
                db = get_db()
                db.execute(
                    """
                    UPDATE tasks
                    SET title = ?, description = ?, priority = ?, due_date = ?,
                        completed = ?,
                        completed_at = CASE WHEN ? = 1
                                            THEN COALESCE(completed_at, CURRENT_TIMESTAMP)
                                            ELSE NULL END
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        data["title"],
                        data["description"],
                        data["priority"],
                        data["due_date"],
                        completed,
                        completed,
                        task_id,
                        g.user["id"],
                    ),
                )
                db.commit()
                flash("Task updated.", "success")
                return redirect(url_for("index"))
        return render_template("edit.html", task=form, priorities=PRIORITIES)

    @app.post("/tasks/<int:task_id>/toggle")
    @login_required
    def toggle_task(task_id):
        get_task_or_404(task_id)
        db = get_db()
        db.execute(
            """
            UPDATE tasks
            SET completed = 1 - completed,
                completed_at = CASE WHEN completed = 0 THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id = ? AND user_id = ?
            """,
            (task_id, g.user["id"]),
        )
        db.commit()
        return redirect(safe_next(request.form.get("next")) or url_for("index"))

    @app.post("/tasks/<int:task_id>/delete")
    @login_required
    def delete_task(task_id):
        get_task_or_404(task_id)
        db = get_db()
        db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, g.user["id"]))
        db.commit()
        flash("Task deleted.", "success")
        return redirect(safe_next(request.form.get("next")) or url_for("index"))

    @app.post("/tasks/clear-completed")
    @login_required
    def clear_completed():
        db = get_db()
        cur = db.execute(
            "DELETE FROM tasks WHERE user_id = ? AND completed = 1", (g.user["id"],)
        )
        db.commit()
        count = cur.rowcount
        if count:
            flash(f"Removed {count} completed task{'s' if count != 1 else ''}.", "success")
        else:
            flash("No completed tasks to remove.", "info")
        return redirect(url_for("index"))

    # ---- account ----------------------------------------------------------
    @app.route("/account")
    @login_required
    def account():
        return render_template("account.html")

    @app.post("/account/password")
    @login_required
    def change_password():
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm", "")
        db = get_db()
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()

        error = None
        if not check_password_hash(row["password_hash"], current):
            error = "Current password is incorrect."
        else:
            error = validate_new_password(new, confirm)

        if error:
            flash(error, "error")
        else:
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new), g.user["id"]),
            )
            db.commit()
            flash("Password updated.", "success")
        return redirect(url_for("account"))

    @app.post("/account/delete")
    @login_required
    def delete_account():
        password = request.form.get("password", "")
        db = get_db()
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()
        if not check_password_hash(row["password_hash"], password):
            flash("Incorrect password. Your account was not deleted.", "error")
            return redirect(url_for("account"))
        db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))  # tasks cascade
        db.commit()
        session.clear()
        flash("Your account and all its tasks have been deleted.", "info")
        return redirect(url_for("signup"))

    return app


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG", "1") == "1")
