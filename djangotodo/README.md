# Django To-Do

A multi-user to-do app built with Django (SQLite by default). The only dependency is Django.

## Features

- Sign up (username, email, password with Django's password validators), log in, log out
- Add, edit, delete and complete/un-complete tasks
- Title, description, priority (low / medium / high) and due date
- Overdue highlighting and summary stats (total / active / done / overdue)
- Search, filter by status and priority, sort by newest / oldest / due date / priority
- Clear all completed tasks
- Account page: change password, delete account (and all your tasks)
- Every user only ever sees and touches their own tasks (other users' tasks return 404)
- Django admin at `/admin/` for superusers
- Light and dark mode (follows your OS setting)

## Run it

```bash
cd djangotodo
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser   # optional - only needed for /admin/
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign up.

## Run the tests

```bash
python manage.py test
```

## Configuration

Settings are read from environment variables, with development-friendly defaults.

| Variable                | Default                   | Purpose                                       |
|-------------------------|---------------------------|-----------------------------------------------|
| `DJANGO_DEBUG`          | `1`                       | Set to `0` for production                     |
| `DJANGO_SECRET_KEY`     | insecure dev key          | **Required** when `DJANGO_DEBUG` is not `1`   |
| `DJANGO_ALLOWED_HOSTS`  | `localhost,127.0.0.1`     | Comma-separated host names                    |
| `DJANGO_TIME_ZONE`      | `UTC`                     | e.g. `Asia/Kolkata` - affects "overdue" dates |

## Project layout

```
djangotodo/
├── manage.py
├── requirements.txt
├── config/            # settings, root urls, wsgi/asgi
├── accounts/          # sign-up, account page, delete account (login/logout/password
│                      #   change use Django's built-in auth views)
├── tasks/             # Task model, forms, views, urls, admin, migrations, tests
├── templates/         # base, registration/*, accounts/*, tasks/*
└── static/css/style.css
```

## Notes

- Log in is by username (Django's default user model). Sign-up also collects a unique email.
- Logout is a POST request (required by Django 5+), so the nav "Log out" is a small form.
- Hand-written initial migration: `tasks/migrations/0001_initial.py`. If you change the
  model, run `python manage.py makemigrations`.

## Going to production

Set `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`, run
`python manage.py collectstatic`, serve static files (e.g. WhiteNoise or your web server),
use a production WSGI server such as gunicorn behind HTTPS, and consider a
production database such as PostgreSQL.
