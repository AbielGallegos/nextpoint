#!/bin/bash
# Reinicia la base PostgreSQL de auditoría y levanta el servidor real en :8000
cd /home/claude/nextpoint
pkill -f "runserver 127.0.0.1:8000" 2>/dev/null; sleep 1
set -a; . ./.env; set +a
export DATABASE_URL=${AUDIT_DATABASE_URL:?Define AUDIT_DATABASE_URL (base de ENSAYO PostgreSQL)}
export NEXTPOINT_DEBUG=0; python3 manage.py collectstatic --noinput -v0; python3 manage.py migrate -v0 && python3 manage.py reset_demo --yes >/dev/null
nohup python3 manage.py runserver 127.0.0.1:8000 --noreload > /home/claude/audit/server.log 2>&1 &
sleep 3; curl -s localhost:8000/health; echo
