#!/bin/sh
set -euo pipefail

python manage.py check --deploy
python manage.py migrate --noinput

exec "$@"
