#!/bin/bash
set -e

cd /pretix/src

echo "Esperando a PostgreSQL en ${PRETIX_DATABASE_HOST:-db}:${PRETIX_DATABASE_PORT:-5432}..."
until python3 - <<'PYEOF'
import os
import socket
import sys

host = os.environ.get("PRETIX_DATABASE_HOST", "db")
port = int(os.environ.get("PRETIX_DATABASE_PORT", "5432"))
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PYEOF
do
  sleep 1
done

if [ "$1" == "runserver" ]; then
    # Compila las traducciones (.po -> .mo). Los .mo no están en git; Django
    # saltea los que ya están al día, así que solo tarda la primera vez.
    python3 manage.py compilemessages
    python3 manage.py migrate --noinput
    python3 manage.py collectstatic --noinput
    exec python3 manage.py runserver 0.0.0.0:8000
fi

if [ "$1" == "celery" ]; then
    exec celery -A pretix.celery_app worker -l info
fi

if [ "$1" == "manage" ]; then
    shift
    exec python3 manage.py "$@"
fi

exec "$@"
