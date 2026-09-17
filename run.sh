#!/usr/bin/env bash
# 로컬 실행 런처: Ollama 서버 자동 기동 + 모델 확인 + 올바른 파이썬으로 스크래퍼 실행.
#   사용: ./run.sh            (기본 수집)
#         PAGES=5 MAX_DETAILS=100 ./run.sh   (더 넓게)
set -uo pipefail
cd "$(dirname "$0")"

OLLAMA=/home/schoaq/.local/bin/ollama
PY=/usr/bin/python3                 # bs4/openpyxl/requests 가 설치된 인터프리터
export OLLAMA_HOST=http://127.0.0.1:11434   # 반드시 http:// 포함 (classify.py가 그대로 URL로 사용)
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"

# 1) Ollama 서버가 없으면 백그라운드 기동
if ! curl -s -m 3 "${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
  echo "[run] Ollama 서버 기동..."
  mkdir -p "$HOME/.ollama"
  nohup "$OLLAMA" serve > "$HOME/.ollama/serve.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -s -m 2 "${OLLAMA_HOST}/api/version" >/dev/null 2>&1 && break
    sleep 1
  done
fi

# 2) 모델 없으면 pull
"$OLLAMA" list 2>/dev/null | grep -q "${OLLAMA_MODEL}" || "$OLLAMA" pull "$OLLAMA_MODEL"

# 3) 스크래퍼 실행
exec "$PY" main.py "$@"
