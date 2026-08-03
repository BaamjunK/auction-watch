#!/usr/bin/env bash
#
# 파이프라인 실행 → 대시보드 갱신 → 커밋 → GitHub Pages 배포(푸시)까지.
#
#   ./deploy.sh                전체 실행 후 배포
#   ./deploy.sh --no-analyze   수집·필터만 하고 배포 (빠른 갱신)
#   ./deploy.sh --no-push      커밋까지만 (배포 안 함)
#
# launchd 자동 실행에서도 이 스크립트를 쓴다. 자동 실행 환경에서는
# 대화형 입력이 불가능하므로, 푸시 인증이 안 되면 조용히 실패하지 않고
# 로그에 원인을 남기고 종료 코드를 남긴다.
set -uo pipefail
cd "$(dirname "$0")"

PUSH=1
PIPE_ARGS=()
for a in "$@"; do
  case "$a" in
    --no-push) PUSH=0 ;;
    *) PIPE_ARGS+=("$a") ;;
  esac
done

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*"; }

# 인터프리터 고정 — launchd 의 PATH 에서는 requests 가 없는 다른 python3 가
# 먼저 잡힐 수 있다(Homebrew python 등). 환경변수 PYTHON 으로 덮어쓸 수 있다.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for cand in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import requests' >/dev/null 2>&1; then
      PYTHON="$cand"; break
    fi
  done
fi
if [ -z "$PYTHON" ]; then
  log "✗ requests 가 설치된 python3 을 찾지 못했습니다. 'python3 -m pip install -r requirements.txt' 후 재시도하세요."
  exit 1
fi
log "python: $PYTHON ($("$PYTHON" -V 2>&1))"

# 네트워크(DNS) 준비 대기 — 절전 복귀 직후 실행되면 이름 해석이 아직 안 되어
# 'nodename nor servname provided' 로 즉시 실패한다. 최대 5분까지 기다린다.
NET_WAIT=0
until "$PYTHON" -c "import socket; socket.getaddrinfo('www.courtauction.go.kr', 443)" >/dev/null 2>&1; do
  if [ "$NET_WAIT" -ge 300 ]; then
    log "✗ 네트워크(DNS) 준비 안 됨 — 5분 대기 후 중단. 다음 예정 시각에 재시도됩니다."
    exit 1
  fi
  [ "$NET_WAIT" -eq 0 ] && log "네트워크 준비 대기 중..."
  sleep 15
  NET_WAIT=$((NET_WAIT + 15))
done
[ "$NET_WAIT" -gt 0 ] && log "네트워크 준비 완료 (${NET_WAIT}s 대기)"

log "=== 파이프라인 시작 ==="
if ! "$PYTHON" -m auctionwatch.pipeline "${PIPE_ARGS[@]+"${PIPE_ARGS[@]}"}"; then
  log "✗ 파이프라인 실패 — 배포 중단"
  exit 1
fi

if git diff --quiet -- docs/ && git diff --cached --quiet -- docs/; then
  log "변경 없음 — 커밋·배포 생략"
  exit 0
fi

COUNT=$("$PYTHON" - <<'PY'
import json, re
html = open('docs/index.html', encoding='utf-8').read()
m = re.search(r'<script id="data"[^>]*>(.*?)</script>', html, re.S)
items = json.loads(m.group(1))['items']
analyzed = sum(1 for i in items if i.get('status') == 'analyzed')
print(f"{len(items)}건(분석 {analyzed})")
PY
)

git add docs/
if ! git commit -q -m "대시보드 갱신: $COUNT $(date '+%Y-%m-%d %H:%M')"; then
  log "✗ 커밋 실패 — 배포 중단"
  exit 1
fi
log "✓ 커밋 완료: $COUNT"

if [ "$PUSH" -eq 0 ]; then
  log "--no-push 지정 — 배포 생략 (수동: git push)"
  exit 0
fi

log "GitHub Pages 배포(푸시) 시작"
if git push -q origin HEAD; then
  log "✓ 배포 완료 — https://baamjunk.github.io/auction-watch/ (반영까지 1~2분)"
else
  rc=$?
  log "✗ 푸시 실패(rc=$rc). 커밋은 로컬에 남아 있으니 다음 실행 또는 수동 'git push' 로 반영됩니다."
  log "   인증 문제라면 확인: gh auth status --hostname github.com"
  log "   git credential helper: $(git config --get credential.https://github.com.helper || echo '(미설정)')"
  exit "$rc"
fi
