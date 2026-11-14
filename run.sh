#!/usr/bin/env bash
# One command to run the studio: ./run.sh        (mock mode, hub at http://127.0.0.1:8000)
#                                ./run.sh live   (real Claude agents, real spending)
#                                ./run.sh test   (backend tests)
#                                ./run.sh dev    (hot-reloading hub at http://127.0.0.1:5173)
#                                ./run.sh clip … (the GTA clipper's command line: ./run.sh clip --help)
set -euo pipefail
CALLER_DIR="$PWD"
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Creating Python environment…"
  python3 -m venv .venv
fi
if [ backend/requirements.txt -nt .venv/.installed ]; then
  .venv/bin/pip install -q -r backend/requirements.txt
  touch .venv/.installed
fi

case "${1:-run}" in
  test)
    cd backend && exec ../.venv/bin/python -m pytest -q
    ;;
  clip)
    # From where it was called, so file paths on the command line work as typed.
    PROJECT="$PWD" && cd "$CALLER_DIR" && PYTHONPATH="$PROJECT/backend" exec "$PROJECT/.venv/bin/python" -m clipper "${@:2}"
    ;;
  dev)
    (cd hub && [ -d node_modules ] || npm install --no-audit --no-fund)
    (cd hub && npm run dev) &
    trap 'kill 0' EXIT
    cd backend && ../.venv/bin/uvicorn studio.api:create_app --factory --host 127.0.0.1 --port 8000 --reload --timeout-graceful-shutdown 3
    ;;
  run|live)
    [ "${1:-run}" = live ] && export STUDIO_MODE=live
    (cd hub && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build >/dev/null)
    echo "Agent Hub (${STUDIO_MODE:-mock} mode): The Athletics Archive at http://127.0.0.1:8000, Game Day Brain at http://127.0.0.1:8001, GTA 6 Clip Central at http://127.0.0.1:8002"
    cd backend
    # Two studios, each with its own channel, data and agents, and the GTA clipper's wing. The others run beside the Archive and stop with it.
    STUDIO_WORKSPACE=slop ../.venv/bin/uvicorn studio.api:create_app --factory --host 127.0.0.1 --port 8001 --timeout-graceful-shutdown 3 &
    SLOP_PID=$!
    ../.venv/bin/uvicorn clipper.api:create_app --factory --host 127.0.0.1 --port 8002 --timeout-graceful-shutdown 3 &
    CLIPS_PID=$!
    trap 'kill $SLOP_PID $CLIPS_PID 2>/dev/null' EXIT INT TERM
    ../.venv/bin/uvicorn studio.api:create_app --factory --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 3
    ;;
  *)
    echo "usage: ./run.sh [run|live|dev|test]" && exit 1
    ;;
esac
