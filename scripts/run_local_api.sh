#!/usr/bin/env bash
set -euo pipefail

DB_LOCAL_PORT="${DB_LOCAL_PORT:-5433}"
BASTION_HOST="${BASTION_HOST:-98.91.194.219}"
BASTION_USER="${BASTION_USER:-ec2-user}"
BASTION_KEY="${BASTION_KEY:-$HOME/.ssh/rds-bastion-key.pem}"
RDS_ENDPOINT="${RDS_ENDPOINT:-promab-database.cuxmicmquovc.us-east-1.rds.amazonaws.com}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"

ensure_db_tunnel() {
  if nc -z localhost "$DB_LOCAL_PORT" >/dev/null 2>&1; then
    echo "DB tunnel already up on localhost:${DB_LOCAL_PORT}"
    return
  fi

  echo "Starting DB tunnel on localhost:${DB_LOCAL_PORT}..."
  ssh -f -N \
    -i "$BASTION_KEY" \
    -L "${DB_LOCAL_PORT}:${RDS_ENDPOINT}:5432" \
    "${BASTION_USER}@${BASTION_HOST}"

  if ! nc -z localhost "$DB_LOCAL_PORT" >/dev/null 2>&1; then
    echo "Failed to start DB tunnel on localhost:${DB_LOCAL_PORT}" >&2
    exit 1
  fi
}

ensure_db_tunnel

echo "Starting app on http://${APP_HOST}:${APP_PORT}"
exec uvicorn src.main:app --reload --host "$APP_HOST" --port "$APP_PORT"
