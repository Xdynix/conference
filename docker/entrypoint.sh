#!/bin/sh
set -euo pipefail

python manage.py migrate --noinput

exec "$@"
