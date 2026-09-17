#!/usr/bin/env bash
# 검수 웹 상시 실행 — 떠 있지 않으면 띄운다 (cron 헬스체크용).
#   ./serve_web.sh          안 떠 있으면 기동, 떠 있으면 아무것도 안 함
#   ./serve_web.sh stop     내리기
#
# serve_day1.sh와 같은 방식: setsid로 세션과 분리해 띄우고 0.0.0.0에 바인딩하므로
# 같은 망에서 http://143.89.46.192:8000 으로 바로 접속된다.
set -uo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

PY=/usr/bin/python3
PORT="${WEB_PORT:-8000}"
LOG="$DIR/data/web.log"
PIDFILE="$DIR/data/web.pid"

if [ "${1:-}" = "stop" ]; then
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null && echo "[web] 내렸습니다"
  # 포트로 한정한다 — 같은 골격의 KSAMentoring 웹(8100)까지 죽이면 안 된다 (2026-09-13 사고)
  pkill -f "gunicorn.*0.0.0.0:${PORT} .*web.app:app" 2>/dev/null
  rm -f "$PIDFILE"
  exit 0
fi

# 이미 정상 응답하면 아무것도 안 함 (cron이 1분마다 불러도 안전)
if curl -sf -o /dev/null -m 5 "http://127.0.0.1:${PORT}/login"; then
  exit 0
fi

# 응답은 없는데 pid 파일의 프로세스가 살아 있으면 '멈춘' 서버다. 그대로 두면 gunicorn이
# "Already running on PID"로 재기동을 거절해 영원히 안 뜬다 (2026-08~09 실제로 16일간 먹통).
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "[$(date '+%F %T')] 응답 없음 → 멈춘 서버(PID $(cat "$PIDFILE")) 강제 종료" >> "$LOG"
  kill -9 "$(cat "$PIDFILE")" 2>/dev/null
  pkill -9 -f "gunicorn.*0.0.0.0:${PORT} .*web.app:app" 2>/dev/null
  sleep 1
fi
rm -f "$PIDFILE"

mkdir -p "$DIR/data"

export WEB_USER="${WEB_USER:-taehee}"
export WEB_PASSWORD="${WEB_PASSWORD:-taehee_fighting_123}"
# 세션 키: 처음 한 번만 무작위로 만들어 파일에 두고 이후엔 읽어 쓴다.
# 재시작해도 로그인이 안 풀리면서 밖에서는 예측할 수 없다.
# (예전에는 sha256("competition-autoscraper") 같은 고정 상수를 썼는데, 그 값은
#  코드만 보면 누구나 계산할 수 있어서 비밀번호 없이 세션을 위조할 수 있었다.)
SECRET_FILE="$DIR/data/web.secret"
if [ ! -s "$SECRET_FILE" ]; then
  ( umask 077; "$PY" -c 'import secrets;print(secrets.token_hex(32))' > "$SECRET_FILE" )
fi
chmod 600 "$SECRET_FILE"
export WEB_SECRET="${WEB_SECRET:-$(cat "$SECRET_FILE")}"
export SCRAPER_PYTHON="${SCRAPER_PYTHON:-$PY}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"
export PYTHONUNBUFFERED=1

# 워커 1개 + 스레드 8개: 수집을 지켜보는 백그라운드 스레드가 한 프로세스 안에 있어야
# 실행 상태를 놓치지 않는다. 동시 접속은 스레드로 감당한다.
setsid "$PY" -m gunicorn \
  --workers 1 --threads 8 --timeout 120 \
  --bind "0.0.0.0:${PORT}" \
  --access-logfile - --error-logfile - \
  --pid "$PIDFILE" \
  web.app:app >> "$LOG" 2>&1 < /dev/null &

for _ in $(seq 1 20); do
  curl -sf -o /dev/null -m 2 "http://127.0.0.1:${PORT}/login" && break
  sleep 1
done

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "[$(date '+%F %T')] started on :${PORT}" >> "$LOG"
echo "[web] http://${IP}:${PORT}  (아이디 ${WEB_USER})"
