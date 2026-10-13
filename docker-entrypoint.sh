#!/bin/sh
set -e

# Apply migrations before serving. With several replicas, set RUN_MIGRATIONS=false here and
# run `alembic upgrade head` once as a release step instead.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  alembic upgrade head
fi

exec "$@"
