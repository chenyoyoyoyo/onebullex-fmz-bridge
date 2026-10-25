#!/usr/bin/env bash
# OneBullEx x FMZ 主機安裝腳本（Ubuntu 22.04 / 24.04，例如 AWS Lightsail）
#
#   sudo bash install_server.sh adapter                       安裝轉接程式並設為開機自動啟動
#   sudo bash install_server.sh docker <FMZ託管者壓縮檔路徑>    安裝 FMZ 託管者並設為開機自動啟動
#   sudo bash install_server.sh status                        檢查兩個服務、連線與本機對外 IP
#
# 轉接程式只監聽 127.0.0.1，主機不需要開放任何對外連接埠（SSH 除外）。
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR=/opt/onebullex_fmz
APP_USER=obxfmz
APP_ENV=/etc/onebullex-fmz.env
APP_SVC=onebullex-fmz
ROBOT_DIR=/opt/robot
ROBOT_SVC=fmz-robot
STRAT_USER=fmzstrat

say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[注意] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[錯誤] %s\033[0m\n' "$*" >&2; exit 1; }

need_root() { [ "$(id -u)" -eq 0 ] || die "請用 sudo 執行：sudo bash $0 $*"; }

ensure_user() {
  id "$1" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$1"
}

health_check() {
  local port
  port="$(grep -E '^OBX_PORT=' "$APP_ENV" 2>/dev/null | cut -d= -f2)"
  port="${port:-6666}"
  curl -s -m 15 -X POST "http://127.0.0.1:${port}/OneBullEx" \
    -H 'Content-Type: application/json' \
    -d '{"method":"ticker","params":{"symbol":"BTC_USDT"}}' || true
}

install_adapter() {
  need_root adapter
  [ -f "$SRC_DIR/onebullex_fmz_plugin.py" ] || die "找不到 onebullex_fmz_plugin.py，請在程式資料夾內執行本腳本"

  say "安裝 Python 與憑證套件"
  if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import certifi' 2>/dev/null; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-certifi curl
  fi
  python3 -c 'import sys; assert sys.version_info >= (3, 8)' || die "需要 Python 3.8 以上"

  say "複製程式到 $APP_DIR"
  ensure_user "$APP_USER"
  install -d -m 755 "$APP_DIR"
  install -m 644 "$SRC_DIR/onebullex_fmz_plugin.py" "$APP_DIR/"
  for f in obx_tool.py check_testnet.py smoke_trade.py README.md; do
    [ -f "$SRC_DIR/$f" ] && install -m 644 "$SRC_DIR/$f" "$APP_DIR/"
  done

  if [ ! -f "$APP_ENV" ]; then
    say "建立設定檔 $APP_ENV（預設測試網）"
    cat > "$APP_ENV" <<'EOF'
# OneBullEx 轉接程式設定。修改後執行：sudo systemctl restart onebullex-fmz
# 連線環境：test（測試網）或 prod（正式環境）
OBX_ENV=test
OBX_PORT=6666
# 以下都是選用的自我保護，預設不限制交易對、張數與槓桿。
# 只允許某些合約時填清單（逗號分隔），例如 btcspartans_usdt,ethspartans_usdt；all 表示不限制
OBX_ALLOWED=all
# 單筆最大張數、最大槓桿（0 表示不限制）；想防止策略寫錯下出過大的單，可自行設定
OBX_MAX_QTY=0
OBX_MAX_LEV=0
# 每秒最多下單筆數，防止策略迴圈失控連續送單（0 表示不限制）
OBX_MAX_RATE=5
# 開倉預設槓桿（會套用到合約設定）；0 表示沿用帳戶目前設定
OBX_DEFAULT_LEV=0
EOF
    chmod 644 "$APP_ENV"
  else
    warn "保留既有設定檔 $APP_ENV"
    grep -q '^OBX_DEFAULT_LEV=' "$APP_ENV" || printf '# 開倉預設槓桿；0 表示沿用帳戶目前設定\nOBX_DEFAULT_LEV=0\n' >> "$APP_ENV"
  fi

  say "設定開機自動啟動（systemd：$APP_SVC）"
  cat > "/etc/systemd/system/${APP_SVC}.service" <<EOF
[Unit]
Description=OneBullEx x FMZ adapter
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
EnvironmentFile=$APP_ENV
ExecStart=/usr/bin/python3 $APP_DIR/onebullex_fmz_plugin.py --host 127.0.0.1 --env \${OBX_ENV} --port \${OBX_PORT} --allowed-symbols \${OBX_ALLOWED} --max-order-qty \${OBX_MAX_QTY} --max-leverage \${OBX_MAX_LEV} --max-orders-per-sec \${OBX_MAX_RATE} --default-leverage \${OBX_DEFAULT_LEV} -v
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now "$APP_SVC" >/dev/null
  systemctl restart "$APP_SVC"
  sleep 2

  say "連線測試（讀取 BTC 報價）"
  local out; out="$(health_check)"
  echo "$out"
  if echo "$out" | grep -q '"last"'; then
    say "轉接程式安裝完成，服務地址：http://127.0.0.1:$(grep -E '^OBX_PORT=' "$APP_ENV" | cut -d= -f2)/OneBullEx"
  else
    warn "連線測試沒有拿到報價，請執行：sudo journalctl -u $APP_SVC -n 50"
  fi
}

install_docker() {
  need_root docker
  local pkg="${1:-}"
  [ -n "$pkg" ] && [ -f "$pkg" ] || die "請提供 FMZ 託管者壓縮檔：sudo bash $0 docker robot_linux_amd64.tar.gz
（到 FMZ「託管者 → 添加託管者 → 手動部署」下載 Linux 版）"

  say "解壓縮託管者"
  local tmp; tmp="$(mktemp -d)"
  case "$pkg" in
    *.tar.gz|*.tgz) tar -xzf "$pkg" -C "$tmp" ;;
    *.zip) command -v unzip >/dev/null || apt-get install -y -qq unzip; unzip -q "$pkg" -d "$tmp" ;;
    *) cp "$pkg" "$tmp/robot" ;;
  esac
  local bin; bin="$(find "$tmp" -type f -name robot | head -n1)"
  [ -n "$bin" ] || die "壓縮檔裡找不到 robot 執行檔"

  if systemctl is-active --quiet "$ROBOT_SVC"; then
    say "停止舊版託管者（保留 logs 與身分）"
    systemctl stop "$ROBOT_SVC"
  fi
  install -d -m 700 "$ROBOT_DIR"
  install -m 755 "$bin" "$ROBOT_DIR/robot"
  rm -rf "$tmp"
  ensure_user "$STRAT_USER"

  if [ ! -f "$ROBOT_DIR/robot.conf" ]; then
    say "設定託管者帳號（密碼不會顯示在畫面上）"
    local addr pass name
    read -rp "通訊地址（FMZ 手動部署頁面上的 node.fmz.com/數字）：" addr
    [ -n "$addr" ] || die "通訊地址不可為空"
    read -rsp "FMZ 帳號密碼：" pass; echo
    [ -n "$pass" ] || die "密碼不可為空"
    read -rp "託管者名稱（英數字，顯示在 FMZ 上，可留空）：" name
    name="$(printf '%s' "$name" | tr -cd 'A-Za-z0-9_.-')"
    umask 077
    printf 's=%s\np=%s\n' "$addr" "$pass" > "$ROBOT_DIR/robot.conf"
    chmod 600 "$ROBOT_DIR/robot.conf"
    printf '%s' "$name" > "$ROBOT_DIR/robot.name"
    unset pass
  else
    warn "保留既有設定 $ROBOT_DIR/robot.conf（要重設帳號請先刪除此檔）"
  fi
  local name_opt=""
  if [ -s "$ROBOT_DIR/robot.name" ]; then
    name_opt=" -n $(cat "$ROBOT_DIR/robot.name")"
  fi

  say "設定開機自動啟動（systemd：$ROBOT_SVC，策略以受限帳號 $STRAT_USER 執行）"
  cat > "/etc/systemd/system/${ROBOT_SVC}.service" <<EOF
[Unit]
Description=FMZ robot (docker)
After=network-online.target $APP_SVC.service
Wants=network-online.target

[Service]
WorkingDirectory=$ROBOT_DIR
ExecStart=$ROBOT_DIR/robot -c $ROBOT_DIR/robot.conf -u $STRAT_USER$name_opt
Restart=on-failure
RestartSec=5
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now "$ROBOT_SVC" >/dev/null
  sleep 5
  if systemctl is-active --quiet "$ROBOT_SVC"; then
    say "託管者已啟動，請到 FMZ「託管者」頁面確認顯示為在線"
  else
    warn "託管者沒有啟動，請執行：sudo journalctl -u $ROBOT_SVC -n 50"
  fi
}

show_status() {
  say "轉接程式（$APP_SVC）"
  systemctl is-active "$APP_SVC" 2>/dev/null || true
  say "FMZ 託管者（$ROBOT_SVC）"
  systemctl is-active "$ROBOT_SVC" 2>/dev/null || true
  [ -f "$ROBOT_DIR/logs/docker.log" ] && tail -n 5 "$ROBOT_DIR/logs/docker.log" 2>/dev/null || true
  say "轉接程式連線測試"
  health_check; echo
  say "本機對外 IP（請提供給 OneBullEx 綁定 API key 白名單）"
  curl -s -m 10 https://checkip.amazonaws.com || echo "查詢失敗"
  [ -f "$APP_ENV" ] && { say "目前設定"; grep -E '^OBX_' "$APP_ENV"; }
}

case "${1:-}" in
  adapter) install_adapter ;;
  docker)  install_docker "${2:-}" ;;
  status)  show_status ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
