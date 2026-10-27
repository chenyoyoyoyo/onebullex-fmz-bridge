#!/usr/bin/env python3
"""
TradingView 訊號接收程式：TradingView 警報（webhook）→ 本程式 → OneBullEx 斯巴達 bot

訊號採「目標持倉」：每則訊息說明「這個交易對現在應該持有多少張（多為正、空為負、0 為空手）」，
程式查實際持倉後補差額。重送或漏送一則訊號，下一則到達時都會自動對齊，不會越下越多。

設定全部來自環境變數（由 install_server.sh tv 寫入 /etc/onebullex-tv.env）：
    OBX_ENV          test 或 prod（預設 test）
    OBX_API_KEY      OneBullEx 機器人 API key
    OBX_SECRET       OneBullEx 機器人 API secret
    TV_PASSPHRASE    TradingView 訊息裡必須帶的密碼
    TV_PORT          監聽埠（只聽 127.0.0.1，由 Caddy 提供 HTTPS 對外），預設 8780
    TV_DRY_RUN       1 = 只記錄要下的單、不送出（預設 1）；確認訊號正確後改 0
    TV_ALLOWED_IPS   允許的來源 IP，逗號分隔；預設為 TradingView 官方 4 個 IP；all 表示不限制
    TV_SYMBOLS       選用：只允許這些交易對，逗號分隔；預設 all
    TV_MAX_QTY       選用：單一交易對持倉上限（張），超過就不執行；預設 0 = 不限
    TV_LEVERAGE      選用：開倉前把該合約槓桿設成此值；預設 0 = 沿用帳戶設定

訊息格式（JSON，見 references/10-tradingview.md）：
    {"passphrase": "...", "symbol": "BTCSPARTANS_USDT",
     "market_position": "{{strategy.market_position}}",
     "size": "{{strategy.market_position_size}}", "unit": "coin"}
或
    {"passphrase": "...", "symbol": "BTCSPARTANS_USDT", "target": 2}
或（指標警報）
    {"passphrase": "...", "symbol": "BTCSPARTANS_USDT", "action": "long", "qty": 2}

只用 Python 標準函式庫。
"""

import hmac
import json
import os
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from onebullex_fmz_plugin import (BASE_URLS, KNOWN_SYMBOLS, OneBullExClient, PluginError,
                                  to_fmz_symbol, to_ob_symbol)

# TradingView 官方公布的 webhook 來源 IP
TRADINGVIEW_IPS = ("52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7")
MAX_BODY = 8192
FILL_TIMEOUT = 15.0
POLL_INTERVAL = 0.5


def log(*parts):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *parts, flush=True)


class SignalError(Exception):
    """訊息內容錯誤（回 400）。"""


def _dec(v, name):
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        raise SignalError(f"{name} 不是數字：{v!r}")
    if not d.is_finite():
        raise SignalError(f"{name} 不是有效數字：{v!r}")
    return d


def to_contracts(amount, unit, contract_size):
    """把數量換成整數張。coin = 幣數（例如 0.0003 BTC），contracts = 張數。
    幣數換算若不是整數張，無條件捨去（不會多下）。"""
    if unit == "contracts":
        n = amount
    elif unit == "coin":
        if contract_size <= 0:
            raise SignalError("查不到合約面值，無法把幣數換成張數")
        n = amount / contract_size
    else:
        raise SignalError(f"unit 只能是 contracts 或 coin，收到 {unit!r}")
    sign = -1 if n < 0 else 1
    n = abs(n)
    nearest = n.to_integral_value()
    whole = nearest if abs(n - nearest) < Decimal("0.000001") else n.to_integral_value(rounding=ROUND_FLOOR)
    return sign * int(whole)


def parse_signal(msg):
    """回傳 (symbol 原字串, 目標的「數量」Decimal（帶正負號）, unit, 說明)。"""
    if not isinstance(msg, dict):
        raise SignalError("訊息必須是 JSON 物件")
    symbol = str(msg.get("symbol") or "").strip()
    if not symbol:
        raise SignalError("缺少 symbol，例如 \"BTCSPARTANS_USDT\"")
    unit = str(msg.get("unit") or "contracts").strip().lower()
    mult = _dec(msg.get("multiplier", 1), "multiplier")
    if mult <= 0:
        raise SignalError("multiplier 必須大於 0")

    if "market_position" in msg:
        side = str(msg.get("market_position") or "").strip().lower()
        size = abs(_dec(msg.get("size", 0), "size"))
        if side == "long":
            target = size
        elif side == "short":
            target = -size
        elif side == "flat":
            target = Decimal(0)
        else:
            raise SignalError(f"market_position 只能是 long、short、flat，收到 {side!r}")
        how = f"market_position={side} size={size}"
    elif "target" in msg:
        target = _dec(msg.get("target"), "target")
        how = f"target={target}"
    elif "action" in msg:
        action = str(msg.get("action") or "").strip().lower()
        if action in ("close", "flat", "exit"):
            target = Decimal(0)
        else:
            qty = abs(_dec(msg.get("qty", 0), "qty"))
            if qty == 0:
                raise SignalError("action 為 long／short 時必須有 qty")
            if action in ("long", "buy"):
                target = qty
            elif action in ("short", "sell"):
                target = -qty
            else:
                raise SignalError(f"action 只能是 long、short、close，收到 {action!r}")
        how = f"action={action}"
    else:
        raise SignalError("訊息要有 market_position+size、target 或 action 其中一種")
    return symbol, target * mult, unit, how


class Executor:
    """把持倉調整到目標張數。先平倉、確認成交，再開倉、確認成交，最後核對持倉。"""

    def __init__(self, client, dry_run=True, max_qty=0, leverage=0):
        self.client = client
        self.dry_run = dry_run
        self.max_qty = max_qty
        self.leverage = leverage
        self._spec = {}
        self._lev_set = set()

    def contract_size(self, sym):
        if sym not in self._spec:
            d = self.client.request("GET", "/v2/public/symbol/detail", {"symbol": sym}) or {}
            self._spec[sym] = Decimal(str(d.get("contractSize") or "0"))
        return self._spec[sym]

    def positions(self, sym):
        rows = self.client.request("GET", "/v2/position/list", {"symbol": sym}, private=True) or []
        out = {"LONG": [], "SHORT": []}
        for p in rows:
            size = Decimal(str(p.get("positionSize") or "0"))
            if size > 0 and p.get("positionSide") in out:
                out[p["positionSide"]].append(p)
        for side in out:   # 先進先出：持倉 ID 隨開倉時間遞增
            out[side].sort(key=lambda p: int(p.get("positionId") or 0))
        return out

    @staticmethod
    def total(rows):
        return int(sum(Decimal(str(p.get("positionSize") or "0")) for p in rows))

    def net(self, sym):
        pos = self.positions(sym)
        return self.total(pos["LONG"]) - self.total(pos["SHORT"]), pos

    def _leverage(self, sym, side):
        if self.leverage:
            if sym not in self._lev_set:
                self.client.request("POST", "/v2/position/adjust-leverage",
                                    {"symbol": sym, "leverage": self.leverage}, private=True)
                self._lev_set.add(sym)
            return self.leverage
        confs = self.client.request("GET", "/v2/position/confs", {"symbol": sym}, private=True) or []
        lev = None
        for c in confs:
            if c.get("positionSide") in (side, "BOTH") and c.get("leverage"):
                lev = int(c["leverage"])
                if c.get("positionSide") == side:
                    break
        return lev

    def _wait_fill(self, order_id, qty):
        deadline = time.time() + FILL_TIMEOUT
        last = None
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            try:
                o = self.client.request("GET", "/v2/order/detail", {"orderId": int(order_id)}, private=True)
            except PluginError as e:
                if "invalid_order" in str(e):
                    continue     # 非同步下單，剛下的單稍後才查得到
                raise
            if not o:
                continue
            last = o
            state = o.get("state")
            if state == "FILLED" and Decimal(str(o.get("executedQty") or "0")) == qty:
                return o
            if state in ("CANCELED", "PARTIALLY_CANCELED", "REJECTED", "EXPIRED"):
                raise PluginError(f"訂單 {order_id} 未完整成交（{state}，成交 {o.get('executedQty')} 張）")
        raise PluginError(f"訂單 {order_id} 在 {FILL_TIMEOUT:g} 秒內未確認成交，最後狀態：{last and last.get('state')}")

    def _send(self, sym, order_side, position_side, qty, position_id=None):
        body = {"symbol": sym, "orderSide": order_side, "positionSide": position_side,
                "origQty": str(qty), "orderType": "MARKET",
                "clientOrderId": "tv" + uuid.uuid4().hex[:20]}
        if position_id is not None:
            body["positionId"] = int(position_id)
        else:
            lev = self._leverage(sym, position_side)
            if lev:
                body["leverage"] = lev
        order_id = self.client.request("POST", "/v2/order/create", body, private=True)
        o = self._wait_fill(order_id, qty)
        log(f"成交 {to_fmz_symbol(sym)} {order_side} {position_side} {qty} 張，均價 {o.get('avgPrice')}，訂單 {order_id}")
        return o

    def plan(self, sym, target):
        """回傳 (目前淨部位, 要下的單列表)。單 = (動作說明, orderSide, positionSide, 張數, 持倉ID或None)。"""
        current, pos = self.net(sym)
        want_long, want_short = max(target, 0), max(-target, 0)
        steps = []
        for side, want in (("SHORT", want_short), ("LONG", want_long)):
            excess = self.total(pos[side]) - want
            for p in pos[side]:            # 先平倉，從最早的一筆開始
                if excess <= 0:
                    break
                closable = int(Decimal(str(p.get("availableCloseSize") or p.get("positionSize") or "0")))
                q = min(excess, closable)
                if q > 0:
                    steps.append(("平空" if side == "SHORT" else "平多",
                                  "BUY" if side == "SHORT" else "SELL", side, q, p.get("positionId")))
                    excess -= q
            if excess > 0:
                raise PluginError(f"{to_fmz_symbol(sym)} 有 {excess} 張{'空' if side == 'SHORT' else '多'}單目前不能平（可能有掛單佔用）")
        for side, want in (("LONG", want_long), ("SHORT", want_short)):
            add = want - self.total(pos[side])
            if add > 0:
                steps.append(("開多" if side == "LONG" else "開空",
                              "BUY" if side == "LONG" else "SELL", side, add, None))
        return current, steps

    def move_to(self, sym, target):
        if self.max_qty and abs(target) > self.max_qty:
            raise PluginError(f"目標持倉 {target} 張超過設定的上限 {self.max_qty} 張，不執行")
        current, steps = self.plan(sym, target)
        name = to_fmz_symbol(sym)
        if not steps:
            log(f"{name} 目前淨部位 {current} 張，已等於目標，不下單")
            return current
        desc = "、".join(f"{s[0]} {s[3]} 張" for s in steps)
        if self.dry_run:
            log(f"[試跑，不下單] {name} 目前 {current} 張 → 目標 {target} 張：{desc}")
            return current
        log(f"{name} 目前 {current} 張 → 目標 {target} 張：{desc}")
        for _, order_side, position_side, q, pid in steps:
            self._send(sym, order_side, position_side, q, pid)
        final = current
        for _ in range(10):
            final, _ = self.net(sym)
            if final == target:
                break
            time.sleep(POLL_INTERVAL)
        if final != target:
            raise PluginError(f"{name} 下單後淨部位 {final} 張，與目標 {target} 張不符，請人工核對")
        log(f"{name} 完成，淨部位 {final} 張")
        return final


class Receiver:
    """收訊號、驗證、排隊；背景執行緒依序執行。同一交易對只執行最新的一則目標。"""

    def __init__(self, executor, passphrase, allowed_ips=TRADINGVIEW_IPS, allowed_symbols=None):
        if not passphrase or len(passphrase) < 12:
            raise ValueError("TV_PASSPHRASE 至少需要 12 個字元")
        self.executor = executor
        self.passphrase = passphrase
        self.allowed_ips = None if allowed_ips is None else set(allowed_ips)
        self.allowed_symbols = None if allowed_symbols is None else {s.lower() for s in allowed_symbols}
        self.pending = {}
        self.cond = threading.Condition()
        self.history = []          # 最近的處理結果（給 /status 本機查詢）
        self.busy = False
        threading.Thread(target=self._worker, daemon=True).start()

    def client_allowed(self, peer, forwarded):
        # Caddy 會把真正的來源 IP 放在 X-Forwarded-For 最後一個；直接連本機（沒有經過 Caddy）視為本機測試
        if forwarded:
            ip = forwarded.split(",")[-1].strip()
        else:
            ip = peer
            if ip in ("127.0.0.1", "::1"):
                return True, ip
        return (self.allowed_ips is None or ip in self.allowed_ips), ip

    def accept(self, msg):
        if not isinstance(msg, dict) or not hmac.compare_digest(
                str(msg.get("passphrase") or "").encode(), self.passphrase.encode()):
            raise PermissionError("passphrase 錯誤")
        symbol, amount, unit, how = parse_signal(msg)
        try:
            sym = to_ob_symbol(symbol)
        except PluginError as e:
            raise SignalError(str(e))
        if self.allowed_symbols is not None and sym not in self.allowed_symbols:
            raise SignalError(f"{symbol} 不在允許的交易對清單")
        with self.cond:
            replaced = sym in self.pending
            self.pending[sym] = (amount, unit, how, time.time())
            self.cond.notify()
        log(f"收到訊號 {to_fmz_symbol(sym)} {how} unit={unit}" + ("（取代尚未執行的上一則）" if replaced else ""))
        return sym

    def _worker(self):
        while True:
            with self.cond:
                while not self.pending:
                    self.cond.wait()
                sym, (amount, unit, how, t) = next(iter(self.pending.items()))
                del self.pending[sym]
                self.busy = True
            result = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "symbol": to_fmz_symbol(sym), "signal": how}
            try:
                target = to_contracts(amount, unit, self.executor.contract_size(sym) if unit == "coin" else Decimal(1))
                result["target"] = target
                result["net"] = self.executor.move_to(sym, target)
                result["ok"] = True
            except Exception as e:   # 單一訊號失敗不影響後續訊號
                result["ok"] = False
                result["error"] = str(e)
                log(f"[失敗] {to_fmz_symbol(sym)} {how}：{e}")
            self.history = (self.history + [result])[-20:]
            with self.cond:
                self.busy = False

    def idle(self):
        with self.cond:
            return not self.pending and not self.busy


def make_handler(receiver):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OneBullEx-TV"
        sys_version = ""

        def log_message(self, fmt, *a):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            local = self.client_address[0] in ("127.0.0.1", "::1") and not self.headers.get("X-Forwarded-For")
            if path == "/status" and local:
                return self._send(200, {"dry_run": receiver.executor.dry_run, "recent": receiver.history})
            self._send(200, {"ok": True})

        def do_POST(self):
            ok, ip = receiver.client_allowed(self.client_address[0], self.headers.get("X-Forwarded-For"))
            if not ok:
                log(f"拒絕：來源 IP {ip} 不在允許清單")
                return self._send(403, {"ok": False, "error": "forbidden"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._send(400, {"ok": False, "error": "body size"})
            raw = self.rfile.read(length)
            try:
                msg = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                log(f"拒絕：來自 {ip} 的訊息不是 JSON（TradingView 警報訊息要填 JSON）")
                return self._send(400, {"ok": False, "error": "message must be JSON"})
            try:
                sym = receiver.accept(msg)
            except PermissionError:
                log(f"拒絕：來自 {ip} 的 passphrase 錯誤")
                return self._send(401, {"ok": False, "error": "unauthorized"})
            except SignalError as e:
                log(f"拒絕：來自 {ip} 的訊息格式錯誤：{e}")
                return self._send(400, {"ok": False, "error": str(e)})
            self._send(200, {"ok": True, "queued": to_fmz_symbol(sym)})

    return Handler


def env_list(name, default):
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    if v.lower() == "all":
        return None
    return [x.strip() for x in v.split(",") if x.strip()]


def main():
    env = os.environ.get("OBX_ENV", "test")
    key, secret = os.environ.get("OBX_API_KEY", ""), os.environ.get("OBX_SECRET", "")
    if not key or not secret:
        raise SystemExit("缺少 OBX_API_KEY / OBX_SECRET（請用 install_server.sh tv 設定）")
    client = OneBullExClient(BASE_URLS[env], key, secret)
    try:
        KNOWN_SYMBOLS.update(str(s).lower() for s in (client.request("GET", "/v2/public/symbol/all") or []))
    except PluginError as e:
        log(f"讀取交易對清單失敗（沿用名稱轉換）：{e}")
    dry = os.environ.get("TV_DRY_RUN", "1").strip() not in ("0", "false", "no")
    executor = Executor(client, dry_run=dry, max_qty=int(os.environ.get("TV_MAX_QTY", "0") or 0),
                        leverage=int(os.environ.get("TV_LEVERAGE", "0") or 0))
    receiver = Receiver(executor, os.environ.get("TV_PASSPHRASE", ""),
                        allowed_ips=env_list("TV_ALLOWED_IPS", list(TRADINGVIEW_IPS)),
                        allowed_symbols=env_list("TV_SYMBOLS", None))
    port = int(os.environ.get("TV_PORT", "8780"))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(receiver))
    log(f"TradingView 訊號接收程式啟動：127.0.0.1:{port}｜環境 {BASE_URLS[env]}｜"
        + ("試跑模式（不下單）" if dry else "正式下單") + "｜來源 IP "
        + ("不限" if receiver.allowed_ips is None else "、".join(sorted(receiver.allowed_ips))))
    server.serve_forever()


if __name__ == "__main__":
    main()
