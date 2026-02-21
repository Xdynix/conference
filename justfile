set dotenv-load := true
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

export PYTHONUTF8 := "1"
export LOGURU_COLORIZE := "1"

default: ruff

# set up development environment
dev-setup:
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
