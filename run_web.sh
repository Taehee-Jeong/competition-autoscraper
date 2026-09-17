#!/usr/bin/env bash
# 검수 웹 실행 (내부용).
#   ./run_web.sh                 → http://127.0.0.1:8000  (이 서버 안에서만)
#   WEB_HOST=0.0.0.0 ./run_web.sh → 같은 망의 다른 PC에서도 접속 (공유 서버 주의)
#
# 다른 PC에서 안전하게 보려면 포트를 여는 대신 SSH 터널을 쓰세요:
#   ssh -L 8000:localhost:8000 schoaq@eez192   →  브라우저에서 localhost:8000
set -uo pipefail
cd "$(dirname "$0")"

PY=/usr/bin/python3

export WEB_USER="${WEB_USER:-taehee}"
export WEB_PASSWORD="${WEB_PASSWORD:-taehee_fighting_123}"
export WEB_HOST="${WEB_HOST:-127.0.0.1}"
export WEB_PORT="${WEB_PORT:-8000}"
# 세션 키를 고정해두면 서버를 재시작해도 로그인이 풀리지 않는다
mkdir -p data
if [ ! -s data/web.secret ]; then
  ( umask 077; "$PY" -c 'import secrets;print(secrets.token_hex(32))' > data/web.secret )
fi
export WEB_SECRET="${WEB_SECRET:-$(cat data/web.secret)}"
# 웹에서 [지금 수집하기]를 누르면 이 인터프리터로 main.py를 돌린다
export SCRAPER_PYTHON="${SCRAPER_PYTHON:-$PY}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"

echo "[web] http://${WEB_HOST}:${WEB_PORT}  (아이디 ${WEB_USER})"
exec "$PY" -m web.app
