#!/bin/sh
set -e

echo "=== Chapuu Backend Starting ==="

# Wait for database to be ready (only when DB_HOST is set = PostgreSQL mode)
if [ -n "$DB_HOST" ]; then
  echo "Waiting for PostgreSQL at $DB_HOST:${DB_PORT:-5432}..."
  until python -c "
import psycopg2, os, sys
try:
  psycopg2.connect(dbname=os.environ.get('DB_NAME'), user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASSWORD'), host=os.environ.get('DB_HOST'), port=os.environ.get('DB_PORT','5432'))
  print('Database ready.')
except Exception as e:
  sys.exit(1)
"; do
    echo "Database not ready — retrying in 2s..."
    sleep 2
  done
fi

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Starting application..."
exec "$@"
