# Flask To-Do

A multi-user to-do app built with Flask and SQLite. The only dependency is Flask.

## Features

- Sign up, log in (by username or email), log out
- Add, edit, delete and complete/un-complete tasks
- Title, description, priority (low / medium / high) and due date
- Overdue highlighting and summary stats (total / active / done / overdue)
- Search, filter by status and priority, sort by newest / oldest / due date / priority
- Clear all completed tasks
- Account page: change password, delete account (and all your tasks)
- Every user only ever sees and touches their own tasks
- Light and dark mode (follows your OS setting)

## Run it

```bash
cd flasktodo
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python app.py                    # or: flask --app app run --debug
```

Open http://127.0.0.1:5000. The SQLite database is created automatically at
`instance/todo.sqlite`, and a random secret key is generated at
`instance/secret_key` on first run.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

## Configuration

| Variable      | Purpose                                                              |
|---------------|----------------------------------------------------------------------|
| `SECRET_KEY`  | Session signing key. If unset, one is generated in `instance/`.      |
| `FLASK_DEBUG` | `python app.py` runs in debug mode by default; set to `0` to disable.|

## Project layout

```
flasktodo/
├── app.py              # app factory, database, auth and task routes
├── requirements.txt
├── static/style.css
├── templates/          # base, login, signup, index, edit, account, error
└── tests/test_app.py
```

## Security notes

- Passwords are hashed with Werkzeug (`generate_password_hash`).
- All POST requests are CSRF-protected with a per-session token.
- SQL uses parameterised queries; templates auto-escape user content.
- The `next` redirect after login only accepts local paths.

For production, run behind a real WSGI server (e.g. `gunicorn "app:create_app()"`)
over HTTPS, set `SECRET_KEY` explicitly, set `SESSION_COOKIE_SECURE=True`, turn off debug
mode, and add login rate limiting (for example with Flask-Limiter).
