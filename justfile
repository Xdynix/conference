# [windows] on a `set` item is what requires 1.56.0.
set minimum-version := '1.56.0'
set dotenv-load

[windows]
set shell := ["powershell.exe", "-NoLogo", "-Command"]

export PYTHONUTF8 := "1"
export LOGURU_COLORIZE := "1"

default: ruff

# set up development environment
dev-setup:
    uv python upgrade 3.14
    uv sync
    uv run pre-commit install
    uv run scripts/dev-setup.py

# run ruff linter and formatter
ruff:
    uv run ruff check --fix .
    uv run ruff format .

# execute all linters
lint:
    uv run pre-commit run --all-files

# audit locked dependencies for known vulnerabilities
audit:
    uv audit --frozen

# execute tests
test *args:
    uv run pytest --cov app -n 8 {{ args }}

# shorthand for manage.py
manage *args:
    uv run manage.py {{ args }}

# start Python shell with Django configured
shell:
    uv run manage.py shell_plus

# populate the database with dummy data
seed-dummy:
    uv run manage.py runscript seed-dummy

# populate the database with realistic staging data (flushes DB first)
seed-staging:
    uv run --group test manage.py runscript seed-staging

# start development services
[parallel]
dev: dev-app dev-mailer dev-scheduler

# start Django server
dev-app:
    uv run manage.py runserver_plus localhost:8000 --cert-file=var/dev-server.crt --nostatic

# start mailer worker
dev-mailer:
    uv run hupper --shutdown-interval=5 -m manage runmailer

# start scheduler worker
dev-scheduler:
    uv run hupper --shutdown-interval=5 -m manage runscheduler
