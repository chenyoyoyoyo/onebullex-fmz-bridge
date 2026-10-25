#!/usr/bin/env python3
"""
OneBullEx x FMZ 通用協議轉接程式（合約版）

讓 FMZ（發明者量化）上的策略透過「通用協議」在 OneBullEx 永續合約上交易。
程式是一個本機 HTTP 服務，與 FMZ 託管者跑在同一台機器：

    FMZ 策略 -> 託管者 -> 本程式 (http://127.0.0.1:6666/OneBullEx) -> OneBullEx Open API V2

只用 Python 標準函式庫，不需要安裝任何套件（Python 3.8 以上）。

啟動（預設連測試環境）：
    python3 onebullex_fmz_plugin.py
    python3 onebullex_fmz_plugin.py --max-order-qty 50   # 選用：自己加單筆張數保護

連正式環境必須明確加上 --env prod。

下單模式（策略用 exchange.IO 切換，見 references/04-strategy-guide.md）：
  - 淨部位（預設）：Buy = 有空單就平空、否則開多；Sell = 有多單就平多、否則開空。
  - 雙向（同時持有多空）：新版 FMZ 託管者不轉送 SetDirection，改由策略呼叫
        exchange.IO("api", "POST", "/v2/fmz/direction", "direction=sell")
    設定之後下單的方向（buy 開多、sell 開空、closebuy 平多、closesell 平空、net 切回淨部位）。
  - 分倉（同方向多筆獨立持倉）：平倉預設平最早的一筆；也可在設定方向時加上
        "direction=closebuy&positionId=<持倉ID>"
    指定下一筆平倉的對象（只作用一次）。
  /v2/fmz/direction 由本程式處理，不會送到 OneBullEx。

依據文件：OneBullEx Open API V2（文件版本 2.1.1，2026-09-22）。
"""

import argparse
import hashlib
import hmac
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_URLS = {
    "test": "https://futures-openapi.1bullex.com",
    "prod": "https://futures-openapi.onebullex.com",
}

# FMZ K 線週期（分鐘）對應 OneBullEx interval
PERIOD_TO_INTERVAL = {
    1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m",
    60: "1h", 120: "2h", 240: "4h", 360: "6h", 720: "12h",
    1440: "1d", 10080: "1w",
}

# OneBullEx 訂單狀態對應 FMZ 通用協議狀態
ORDER_STATE = {
    "NEW": "pending",
    "PARTIALLY_FILLED": "partial-filled",
    "FILLED": "filled",
    "CANCELED": "canceled",
    "PARTIALLY_CANCELED": "partial-canceled",
    "REJECTED": "canceled",
    "EXPIRED": "canceled",
}

# FMZ 下單方向（SetDirection）+ 買賣 對應 OneBullEx orderSide / positionSide
DIRECTION_MAP = {
    ("buy", "buy"): ("BUY", "LONG", False),          # 開多
    ("sell", "sell"): ("SELL", "SHORT", False),      # 開空
    ("closebuy", "sell"): ("SELL", "LONG", True),    # 平多
    ("closesell", "buy"): ("BUY", "SHORT", True),    # 平空
}


class PluginError(Exception):
    """回給 FMZ 的錯誤，訊息會顯示在 FMZ 實盤日誌。"""


def _ssl_context():
    """macOS 上從 python.org 安裝的 Python 沒有內建憑證清單；
    有安裝 certifi 就用它的憑證，否則用系統預設。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = _ssl_context()


# ---------------------------------------------------------------------------
# OneBullEx Open API V2 用戶端
# ---------------------------------------------------------------------------

def _sign_value(v):
    """把參數值轉成簽名用字串：整數保持整數、小數保留原精度、不用科學記號。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return format(Decimal(repr(v)), "f")
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


def build_sign_string(nonce, timestamp, params):
    """依文件 3.3：nonce、timestamp 加上參數，按 key 排序後以 & 串接。
    params 只取頂層的字串、數字；None 與巢狀物件、陣列忽略。"""
    items = {"nonce": nonce, "timestamp": timestamp}
    for k, v in (params or {}).items():
        if v is None or isinstance(v, (dict, list, tuple)):
            continue
        items[k] = v
    return "&".join(f"{k}={_sign_value(items[k])}" for k in sorted(items))


def sign(secret, sign_string):
    return hmac.new(secret.encode(), sign_string.encode(), hashlib.sha256).hexdigest()


class OneBullExClient:
    def __init__(self, base_url, api_key="", secret="", timeout=10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.secret = secret
        self.timeout = timeout

    def request(self, method, path, params=None, private=False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        # 網站防火牆會擋 Python 預設的 User-Agent（Python-urllib），需明確指定
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "Mozilla/5.0 (compatible; OneBullEx-FMZ-Adapter/1.0)"}
        url = self.base_url + path
        body = None
        if method == "GET" and params:
            url += "?" + urllib.parse.urlencode({k: _sign_value(v) for k, v in params.items()})
        if method == "POST":
            body = json.dumps(params, separators=(",", ":")).encode()

        if private:
            if not self.api_key or not self.secret:
                raise PluginError("缺少 API key 或 Secret Key，請在 FMZ 交易所設定中填入")
            nonce = uuid.uuid4().hex
            timestamp = str(int(time.time()))
            headers.update({
                "X-API-KEY": self.api_key,
                "X-Nonce": nonce,
                "X-Timestamp": timestamp,
                "X-Signature": sign(self.secret, build_sign_string(nonce, timestamp, params)),
            })

        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CONTEXT) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                payload = json.loads(raw)
            except Exception:
                snippet = " ".join(raw.split())[:200]
                raise PluginError(f"OneBullEx HTTP {e.code}：{snippet}")
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                raise PluginError("HTTPS 憑證驗證失敗：請先執行 python3 -m pip install certifi 後再試")
            raise PluginError(f"連線 OneBullEx 失敗：{e.reason}")
        except json.JSONDecodeError:
            raise PluginError("OneBullEx 回應不是 JSON")

        if not isinstance(payload, dict) or payload.get("code") != 0:
            msg = payload.get("msg") if isinstance(payload, dict) else payload
            raise PluginError(f"OneBullEx 錯誤：{msg}")
        return payload.get("data")


# ---------------------------------------------------------------------------
# 選用的自我保護（預設不限制；由主機管理者自行設定，交易所端的規則仍以 OneBullEx 為準）
# ---------------------------------------------------------------------------

class Limits:
    def __init__(self, allowed_symbols, max_order_qty, max_leverage, max_orders_per_sec):
        self.allowed_symbols = {s.lower() for s in allowed_symbols} if allowed_symbols else None
        self.max_order_qty = max_order_qty
        self.max_leverage = max_leverage
        self.max_orders_per_sec = max_orders_per_sec
        self._lock = threading.Lock()
        self._order_times = []

    def check_symbol(self, symbol):
        if self.allowed_symbols is not None and symbol not in self.allowed_symbols:
            raise PluginError(f"交易對 {symbol} 不在允許清單內：{sorted(self.allowed_symbols)}")

    def check_qty(self, qty):
        if self.max_order_qty and qty > self.max_order_qty:
            raise PluginError(f"單筆數量 {qty} 張超過上限 {self.max_order_qty} 張")

    def check_leverage(self, lev):
        if self.max_leverage and lev > self.max_leverage:
            raise PluginError(f"槓桿 {lev} 倍超過上限 {self.max_leverage} 倍")

    def check_rate(self):
        if not self.max_orders_per_sec:
            return
        now = time.time()
        with self._lock:
            self._order_times = [t for t in self._order_times if now - t < 1.0]
            if len(self._order_times) >= self.max_orders_per_sec:
                raise PluginError(f"下單頻率超過每秒 {self.max_orders_per_sec} 筆上限")
            self._order_times.append(now)


# ---------------------------------------------------------------------------
# FMZ 請求 -> OneBullEx 轉換
# ---------------------------------------------------------------------------

# OneBullEx 的交易對清單（/v2/public/symbol/all），用來對應寫法不同的名稱，
# 例如 FMZ 的 BTCSPARTANS_USDT 對應交易所的斯巴達專屬交易對。
KNOWN_SYMBOLS = set()


def _squash(s):
    return s.replace("_", "").replace("-", "")


def to_ob_symbol(fmz_symbol):
    """BTC_USDT / BTC_USDT.swap / btc_usdt -> btc_usdt；
    BTCSPARTANS_USDT -> 交易所清單中對應的名稱（例如 btcspartans_usdt）"""
    s = str(fmz_symbol or "").strip()
    if not s:
        raise PluginError("缺少交易對（symbol）")
    s = s.split(".")[0].lower()
    if KNOWN_SYMBOLS and s not in KNOWN_SYMBOLS:
        for k in KNOWN_SYMBOLS:
            if _squash(k) == _squash(s):
                return k
    if "_" not in s and s not in KNOWN_SYMBOLS:
        raise PluginError(f"交易對格式錯誤：{fmz_symbol}，應為 BTC_USDT 或 BTCSPARTANS_USDT")
    return s


def to_fmz_symbol(ob_symbol):
    s = str(ob_symbol or "")
    if s and "_" not in s and s.lower().endswith("usdt"):
        s = s[:-4] + "_" + s[-4:]
    return s.upper()


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class AccountState:
    """每個 API key 各自記住 FMZ 的 SetDirection / SetContractType / SetMarginLevel。"""

    def __init__(self):
        self.direction = "buy"
        self.direction_set = False   # 新版 FMZ 託管者的通用協議不轉送 SetDirection，此時改用淨部位模式
        self.contract_type = "swap"
        self.margin_level = None
        self.symbol = None
        self.leverage = {}           # 每個合約目前的槓桿（快取）
        self.close_pid = None        # 分倉時指定下一筆平倉的持倉 ID（只作用一次）


class Adapter:
    def __init__(self, base_url, limits, timeout=10, default_leverage=0):
        self.base_url = base_url
        self.limits = limits
        self.timeout = timeout
        self.default_leverage = default_leverage
        self._states = {}
        self._lock = threading.Lock()
        self._symbols_loaded_at = 0.0

    def load_symbols(self, client, force=False):
        """取得交易所的交易對清單（公開資料，每 10 分鐘最多更新一次）；失敗時沿用原本的名稱轉換。"""
        if not force and time.time() - self._symbols_loaded_at < 600:
            return
        self._symbols_loaded_at = time.time()
        try:
            rows = client.request("GET", "/v2/public/symbol/all")
            if isinstance(rows, list) and rows:
                KNOWN_SYMBOLS.clear()
                KNOWN_SYMBOLS.update(str(r).lower() for r in rows if r)
        except Exception:
            pass

    def state(self, api_key):
        with self._lock:
            return self._states.setdefault(api_key, AccountState())

    def handle(self, req):
        method = req.get("method", "")
        params = req.get("params") or {}
        api_key = req.get("access_key", "")
        client = OneBullExClient(self.base_url, api_key, req.get("secret_key", ""), self.timeout)
        st = self.state(api_key)
        self.load_symbols(client)
        if "symbol" in params and params["symbol"]:
            st.symbol = to_ob_symbol(params["symbol"])

        if method == "ticker":
            return self.ticker(client, params)
        if method == "depth":
            return self.depth(client, params)
        if method == "trades":
            return self.trades(client, params)
        if method == "records":
            return self.records(client, params)
        if method in ("accounts", "assets"):
            return self.accounts(client)
        if method == "trade":
            return self.trade(client, st, params)
        if method == "orders":
            return self.orders(client, params)
        if method == "order":
            return self.order(client, params)
        if method == "historyorders":
            return self.history_orders(client, params)
        if method == "cancel":
            return self.cancel(client, params)
        if method == "positions":
            return self.positions(client, st, params)
        if method == "io":
            return self.io(client, st, params)
        if method.startswith("__api_"):
            return self.raw_api(client, st, method[len("__api_"):], params, req.get("_http_method", "GET"))
        raise PluginError(f"不支援的方法：{method}")

    # ---------------- 行情 ----------------

    def ticker(self, client, params):
        sym = to_ob_symbol(params.get("symbol"))
        d = client.request("GET", "/v2/public/q/agg-ticker", {"symbol": sym, "timeRangeType": "H24"})
        return {"data": {
            "symbol": to_fmz_symbol(d.get("s", sym)),
            "buy": d.get("bp"), "sell": d.get("ap"),
            "high": d.get("h"), "low": d.get("l"), "open": d.get("o"),
            "last": d.get("c"), "vol": d.get("a"), "time": d.get("t"),
        }, "raw": d}

    def depth(self, client, params):
        sym = to_ob_symbol(params.get("symbol"))
        level = int(_f(params.get("limit"), 30)) or 30
        level = max(1, min(level, 50))
        d = client.request("GET", "/v2/public/q/depth", {"symbol": sym, "level": level})
        return {"data": {
            "time": d.get("t"),
            "asks": [[_f(p), _f(q)] for p, q in d.get("a", [])],
            "bids": [[_f(p), _f(q)] for p, q in d.get("b", [])],
        }}

    def trades(self, client, params):
        sym = to_ob_symbol(params.get("symbol"))
        rows = client.request("GET", "/v2/public/q/deal", {"symbol": sym, "num": 50}) or []
        out = [{
            "id": int(r.get("t", 0)), "time": r.get("t"),
            "price": _f(r.get("p")), "amount": _f(r.get("a")),
            "type": str(r.get("m", "")).lower(),
        } for r in rows]
        out.sort(key=lambda x: x["time"] or 0)
        return {"data": out}

    def records(self, client, params):
        sym = to_ob_symbol(params.get("symbol"))
        period = int(_f(params.get("period"), 60))
        interval = PERIOD_TO_INTERVAL.get(period)
        if not interval:
            raise PluginError(f"不支援的 K 線週期：{period} 分鐘")
        limit = max(1, min(int(_f(params.get("limit"), 500)) or 500, 1500))
        rows = client.request("GET", "/v2/public/q/kline",
                              {"symbol": sym, "interval": interval, "limit": limit}) or []
        out = [[int(r["t"]) // 1000, _f(r.get("o")), _f(r.get("h")), _f(r.get("l")),
                _f(r.get("c")), _f(r.get("a"))] for r in rows]
        out.sort(key=lambda x: x[0])
        return {"data": out}

    # ---------------- 帳戶 ----------------

    def accounts(self, client):
        rows = client.request("GET", "/v2/balance/list", private=True) or []
        out = []
        for r in rows:
            wallet = _f(r.get("walletBalance"))
            avail = _f(r.get("availableBalance"))
            out.append({"currency": str(r.get("coin", "")).upper(),
                        "free": str(avail), "frozen": str(max(wallet - avail, 0))})
        return {"data": out, "raw": rows}

    # ---------------- 交易 ----------------

    @staticmethod
    def _position_age(p):
        """排序用：先看建立時間，沒有就用持倉 ID（遞增）。"""
        t = _f(p.get("createdTime"), 0) or _f(p.get("openTime"), 0)
        try:
            pid = int(p.get("positionId"))
        except (TypeError, ValueError):
            pid = 0
        return (t if t else float("inf"), pid)

    def _find_position_id(self, client, symbol, position_side, target_pid=None):
        """找要平倉的持倉，回傳 (持倉ID, 可平張數, 同方向持倉筆數)。
        合倉時同方向只有一筆；分倉時同方向可能有多筆，預設取最早開的一筆（先進先出），
        或由 target_pid 指定。"""
        rows = client.request("GET", "/v2/position/list", {"symbol": symbol}, private=True) or []
        found = sorted((p for p in rows
                        if p.get("positionSide") == position_side and _f(p.get("positionSize")) > 0),
                       key=self._position_age)
        if target_pid is not None:
            for p in found:
                if str(p.get("positionId")) == str(target_pid):
                    return p.get("positionId"), _f(p.get("availableCloseSize"), _f(p.get("positionSize"))), len(found)
            name = "多" if position_side == "LONG" else "空"
            raise PluginError(f"{to_fmz_symbol(symbol)} 找不到指定的{name}單持倉 ID {target_pid}")
        if found:
            p = found[0]
            return p.get("positionId"), _f(p.get("availableCloseSize"), _f(p.get("positionSize"))), len(found)
        return None, 0.0, 0

    @staticmethod
    def _close_limit_msg(name, closable, count):
        if count > 1:
            return (f"分倉模式下同方向有 {count} 筆{name}單，一張平倉單只能平其中一筆；"
                    f"這一筆最多可平 {closable:g} 張。請分批平倉，或用 exchange.IO 指定 positionId")
        return f"目前持有{name}單 {closable:g} 張，單筆最多只能平 {closable:g} 張"

    DIRECTIONS = ("buy", "sell", "closebuy", "closesell")

    def _set_direction(self, st, d, position_id=None):
        d = str(d or "").strip().lower()
        if d == "net":
            st.direction = "buy"
            st.direction_set = False
        elif d in self.DIRECTIONS:
            st.direction = d
            st.direction_set = True
        else:
            raise PluginError(f"不支援的下單方向：{d}，可用 buy、sell、closebuy、closesell、net")
        if position_id not in (None, ""):
            pid = str(position_id).strip()
            if not pid.isdigit():
                raise PluginError(f"持倉 ID 格式錯誤：{position_id}")
            st.close_pid = pid
        else:
            st.close_pid = None
        return d

    def _leverage_for_open(self, client, st, sym, position_side):
        """開倉單必須帶上與持倉設定一致的槓桿，否則 OneBullEx 回 order_leverage_not_match_position_leverage。
        優先順序：策略 SetMarginLevel > 啟動參數 --default-leverage > 帳戶目前設定。"""
        if st.margin_level:
            return int(st.margin_level)
        if self.default_leverage:
            if st.leverage.get(sym) != self.default_leverage:
                self.limits.check_leverage(self.default_leverage)
                client.request("POST", "/v2/position/adjust-leverage",
                               {"symbol": sym, "leverage": self.default_leverage}, private=True)
                st.leverage[sym] = self.default_leverage
            return self.default_leverage
        if sym not in st.leverage:
            confs = client.request("GET", "/v2/position/confs", {"symbol": sym}, private=True) or []
            lev = None
            for c in confs:
                if c.get("positionSide") in (position_side, "BOTH") and c.get("leverage"):
                    lev = int(c["leverage"])
                    if c.get("positionSide") == position_side:
                        break
            st.leverage[sym] = lev
        return st.leverage.get(sym)

    def _resolve_side(self, client, st, sym, side, qty):
        """回傳 (orderSide, positionSide, 是否平倉, 持倉ID)。"""
        if st.direction_set:
            key = (st.direction, side)
            if key not in DIRECTION_MAP:
                raise PluginError(
                    f"下單方向與 SetDirection 不符：direction={st.direction}，下單={side}。"
                    "開多用 buy+Buy、開空用 sell+Sell、平多用 closebuy+Sell、平空用 closesell+Buy")
            order_side, position_side, is_close = DIRECTION_MAP[key]
            pid = None
            if is_close:
                name = "多" if position_side == "LONG" else "空"
                pid, closable, count = self._find_position_id(client, sym, position_side, st.close_pid)
                if not pid:
                    raise PluginError(f"{to_fmz_symbol(sym)} 沒有可平的{name}倉")
                if qty > closable:
                    raise PluginError(f"平倉數量 {qty} 張超過可平數量 {closable:g} 張。"
                                      + (self._close_limit_msg(name, closable, count) if count > 1 else ""))
            return order_side, position_side, is_close, pid

        # 淨部位模式（新版 FMZ 託管者不轉送 SetDirection 時）：
        # 買 = 有空單就平空，否則開多；賣 = 有多單就平多，否則開空。不自動反手。
        order_side = "BUY" if side == "buy" else "SELL"
        if side not in ("buy", "sell"):
            raise PluginError(f"不支援的下單類型：{side}")
        opposite = "SHORT" if side == "buy" else "LONG"
        pid, closable, count = self._find_position_id(client, sym, opposite, st.close_pid)
        if pid:
            name = "空" if opposite == "SHORT" else "多"
            if qty > closable:
                raise PluginError(
                    self._close_limit_msg(name, closable, count) + "。"
                    f"要反手請先平掉全部{name}單，確認持倉為空後再開新方向")
            return order_side, opposite, True, pid
        return order_side, ("LONG" if side == "buy" else "SHORT"), False, None

    def trade(self, client, st, params):
        sym = to_ob_symbol(params.get("symbol"))
        self.limits.check_symbol(sym)
        side = str(params.get("type", "")).lower()

        amount = Decimal(str(params.get("amount", "0")))
        if amount != amount.to_integral_value():
            raise PluginError(f"OneBullEx 合約數量必須是整數張，收到 {amount}")
        qty = int(amount)
        if qty < 1:
            raise PluginError("下單數量至少 1 張")
        self.limits.check_qty(qty)
        self.limits.check_rate()
        try:
            order_side, position_side, is_close, pid = self._resolve_side(client, st, sym, side, qty)
        finally:
            st.close_pid = None      # 指定的平倉對象只作用一次

        price = Decimal(str(params.get("price", "-1")))
        body = {
            "symbol": sym,
            "orderSide": order_side,
            "positionSide": position_side,
            "origQty": str(qty),
            "clientOrderId": "fmz" + uuid.uuid4().hex[:20],
        }
        if price > 0:
            body["orderType"] = "LIMIT"
            body["price"] = format(price.normalize(), "f")
            body["timeInForce"] = "GTC"
        else:
            body["orderType"] = "MARKET"

        if is_close:
            body["positionId"] = int(pid)
        else:
            lev = self._leverage_for_open(client, st, sym, position_side)
            if lev:
                body["leverage"] = lev

        order_id = client.request("POST", "/v2/order/create", body, private=True)
        # OneBullEx 為非同步下單，回傳 ID 不代表已成交；策略需以 GetOrder 確認狀態
        return {"data": {"id": f"{to_fmz_symbol(sym)},{order_id}"}}

    @staticmethod
    def _order_id(fmz_id):
        oid = str(fmz_id).split(",")[-1].strip()
        if not oid.isdigit():
            raise PluginError(f"訂單 ID 格式錯誤：{fmz_id}")
        return int(oid)

    @staticmethod
    def _map_order(o):
        sym = to_fmz_symbol(o.get("symbol", ""))
        # FMZ 的 Offset：0 = 開倉（ORDER_OFFSET_OPEN），1 = 平倉（ORDER_OFFSET_CLOSE）
        offset = 1 if (o.get("orderSide") == "SELL") == (o.get("positionSide") == "LONG") else 0
        return {
            "id": f"{sym},{o.get('orderId')}",
            "symbol": sym,
            "time": int(_f(o.get("createdTime"), 0)),
            "amount": _f(o.get("origQty")),
            "price": _f(o.get("price")),
            "deal_amount": _f(o.get("executedQty")),
            "avg_price": _f(o.get("avgPrice")),
            "type": "buy" if o.get("orderSide") == "BUY" else "sell",
            "status": ORDER_STATE.get(o.get("state"), "pending"),
            "offset": offset,
            "contract_type": "swap",
        }

    def orders(self, client, params):
        sym = to_ob_symbol(params.get("symbol"))
        rows = client.request("GET", "/v2/order/all/listUnfinished", {"list": sym}, private=True) or []
        return {"data": [self._map_order(o) for o in rows]}

    ORDER_LOOKUP_RETRIES = 6        # OneBullEx 為非同步下單，剛下的單要稍等才查得到
    ORDER_LOOKUP_INTERVAL = 0.4     # 秒；最多約等 2 秒

    def order(self, client, params):
        oid = self._order_id(params.get("id"))
        last_err = None
        for attempt in range(self.ORDER_LOOKUP_RETRIES):
            try:
                o = client.request("GET", "/v2/order/detail", {"orderId": oid}, private=True)
                if o:
                    return {"data": self._map_order(o)}
            except PluginError as e:
                if "invalid_order" not in str(e):
                    raise
                last_err = e
            if attempt < self.ORDER_LOOKUP_RETRIES - 1:
                time.sleep(self.ORDER_LOOKUP_INTERVAL)
        raise PluginError("查無此訂單（OneBullEx 為非同步下單，等候約 2 秒後仍查不到，請稍後再查）"
                          + (f"：{last_err}" if last_err else ""))

    def history_orders(self, client, params):
        sym = to_ob_symbol(params.get("symbol"))
        q = {"symbol": sym}
        limit = int(_f(params.get("limit"), 0))
        since = int(_f(params.get("since"), 0))
        if limit > 0:
            q["limit"] = limit
        if since > 0:
            q["startTime"] = since
        d = client.request("GET", "/v2/order/list-history", q, private=True) or {}
        items = d.get("items", []) if isinstance(d, dict) else d
        return {"data": [self._map_order(o) for o in items]}

    def cancel(self, client, params):
        client.request("POST", "/v2/order/cancel",
                       {"orderId": self._order_id(params.get("id"))}, private=True)
        return {"data": True}

    # ---------------- 合約專屬 ----------------

    def positions(self, client, st, params):
        sym = to_ob_symbol(params.get("symbol")) if params.get("symbol") else st.symbol
        q = {"symbol": sym} if sym else {}
        rows = client.request("GET", "/v2/position/list", q, private=True) or []
        out = []
        for p in rows:
            size = _f(p.get("positionSize"))
            if size <= 0:
                continue
            entry = _f(p.get("entryPrice"))
            csize = _f(p.get("contractSize"), 1.0)
            is_long = p.get("positionSide") == "LONG"
            profit = 0.0
            try:
                mark = client.request("GET", "/v2/public/q/symbol-mark-price", {"symbol": p.get("symbol")})
                mark_px = _f(mark.get("p")) if isinstance(mark, dict) else 0.0
                if mark_px:
                    profit = (mark_px - entry) * size * csize * (1 if is_long else -1)
            except PluginError:
                pass
            out.append({
                "Symbol": to_fmz_symbol(p.get("symbol")) + ".swap",
                "MarginLevel": int(_f(p.get("leverage"), 0)),
                "Amount": size,
                "FrozenAmount": max(size - _f(p.get("availableCloseSize"), size), 0),
                "Price": entry,
                "Profit": round(profit, 8),
                "Type": 0 if is_long else 1,
                "ContractType": "swap",
                "Margin": _f(p.get("isolatedMargin")),
                "Info": p,
            })
        return {"data": out}

    def io(self, client, st, params):
        code = str(params.get("code"))
        args = params.get("args") or []
        if code == "0":   # SetMarginLevel
            lev = int(_f(args[0] if args else 0))
            if lev < 1:
                raise PluginError("槓桿必須至少 1 倍")
            self.limits.check_leverage(lev)
            st.margin_level = lev
            if st.symbol:
                client.request("POST", "/v2/position/adjust-leverage",
                               {"symbol": st.symbol, "leverage": lev}, private=True)
                st.leverage[st.symbol] = lev
            return {"data": lev}
        if code == "1":   # SetDirection（舊版託管者才會轉送）
            return {"data": self._set_direction(st, args[0] if args else "")}
        if code == "2":   # SetContractType
            ct = str(args[0] if args else "").lower()
            if ct != "swap":
                raise PluginError(f"OneBullEx 目前只有永續合約，請使用 SetContractType(\"swap\")，收到 {ct}")
            st.contract_type = ct
            return {"data": {"InstrumentID": to_fmz_symbol(st.symbol or "") , "ContractType": "swap"}}
        if code == "3":   # GetPosition
            return self.positions(client, st, {})
        raise PluginError(f"不支援的 io 代碼：{code}")

    def raw_api(self, client, st, path, params, http_method):
        """exchange.IO("api", ...) 直通 OneBullEx：開放 GET 查詢，以及 POST 調整槓桿（受槓桿上限保護）。
        下單一律走 exchange.Buy / Sell，以免繞過安全限制。
        /v2/fmz/direction 由本程式處理：設定下單方向（與分倉的平倉對象），不送到 OneBullEx。"""
        if path.rstrip("/") == "/v2/fmz/direction":
            if not params.get("direction"):
                return {"data": {"direction": st.direction if st.direction_set else "net",
                                 "positionId": st.close_pid}}
            d = self._set_direction(st, params.get("direction"), params.get("positionId"))
            return {"data": d}
        if not path.startswith("/v2/"):
            raise PluginError("路徑必須以 /v2/ 開頭")
        if http_method.upper() == "POST" and path == "/v2/position/adjust-leverage":
            sym = to_ob_symbol(params.get("symbol") or st.symbol)
            lev = int(_f(params.get("leverage"), 0))
            if lev < 1:
                raise PluginError("槓桿必須至少 1 倍")
            self.limits.check_symbol(sym)
            self.limits.check_leverage(lev)
            client.request("POST", path, {"symbol": sym, "leverage": lev}, private=True)
            st.leverage[sym] = lev
            st.margin_level = lev
            return {"data": lev}
        if http_method.upper() != "GET":
            raise PluginError("exchange.IO 直通只開放 GET 查詢與調整槓桿；下單請用 exchange.Buy / Sell")
        private = not path.startswith("/v2/public/")
        if params.get("symbol"):
            params = dict(params, symbol=to_ob_symbol(params["symbol"]))
        return {"data": client.request("GET", path, params, private=private)}


# ---------------------------------------------------------------------------
# HTTP 服務
# ---------------------------------------------------------------------------

def make_handler(adapter, path, verbose):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            pass

        def _send(self, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send({"error": "FMZ 通用協議只使用 POST"})

        def do_POST(self):
            if self.path.split("?")[0].rstrip("/") != path:
                self._send({"error": f"路徑錯誤，請在 FMZ 服務地址填 ...{path}"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                req["_http_method"] = self.headers.get("Http-Method", "GET")
                resp = adapter.handle(req)
            except PluginError as e:
                resp = {"error": str(e)}
            except Exception as e:  # 不讓單一請求錯誤拖垮服務
                resp = {"error": f"轉接程式內部錯誤：{type(e).__name__}: {e}"}
            if verbose:
                safe = {k: v for k, v in req.items() if k not in ("secret_key", "access_key")} \
                    if isinstance(locals().get("req"), dict) else {}
                print(time.strftime("%H:%M:%S"), json.dumps(safe, ensure_ascii=False)[:300],
                      "->", json.dumps(resp, ensure_ascii=False)[:300], flush=True)
            self._send(resp)

    return Handler


def main():
    ap = argparse.ArgumentParser(description="OneBullEx x FMZ 通用協議轉接程式")
    ap.add_argument("--env", choices=["test", "prod"], default="test",
                    help="連線環境，預設 test（測試網）；正式環境需明確指定 prod")
    ap.add_argument("--base-url", help="自訂 API 網址（覆蓋 --env，供測試用）")
    ap.add_argument("--host", default="127.0.0.1", help="監聽位址，預設只允許本機")
    ap.add_argument("--port", type=int, default=6666)
    ap.add_argument("--path", default="/OneBullEx", help="服務路徑，預設 /OneBullEx")
    ap.add_argument("--allowed-symbols", default="all",
                    help="選用：只允許這些合約，逗號分隔；預設 all 表示不限制")
    ap.add_argument("--max-order-qty", type=int, default=0, help="選用：單筆最大張數（防止下錯單），預設 0 表示不限制")
    ap.add_argument("--max-leverage", type=int, default=0, help="選用：最大槓桿，預設 0 表示不限制")
    ap.add_argument("--max-orders-per-sec", type=int, default=5, help="每秒最多下單筆數，0 表示不限制")
    ap.add_argument("--default-leverage", type=int, default=0,
                    help="開倉預設槓桿（會先套用到合約設定）；0 表示沿用帳戶目前設定")
    ap.add_argument("--timeout", type=int, default=10, help="呼叫 OneBullEx 的逾時秒數")
    ap.add_argument("-v", "--verbose", action="store_true", help="印出每筆請求與回應（不含金鑰）")
    a = ap.parse_args()

    base_url = a.base_url or BASE_URLS[a.env]
    allowed = None if a.allowed_symbols.strip().lower() == "all" else \
        [s.strip() for s in a.allowed_symbols.split(",") if s.strip()]
    limits = Limits(allowed, a.max_order_qty, a.max_leverage, a.max_orders_per_sec)
    if a.default_leverage:
        limits.check_leverage(a.default_leverage)
    adapter = Adapter(base_url, limits, a.timeout, a.default_leverage)
    path = "/" + a.path.strip("/")

    server = ThreadingHTTPServer((a.host, a.port), make_handler(adapter, path, a.verbose))
    print(f"OneBullEx 轉接程式啟動：http://{a.host}:{a.port}{path}")
    print(f"  連線環境：{base_url}")
    print(f"  允許合約：{'不限' if allowed is None else ', '.join(allowed)}"
          f"｜單筆上限：{a.max_order_qty or '不限'} 張｜槓桿上限：{a.max_leverage or '不限'} 倍"
          f"｜下單頻率：{a.max_orders_per_sec or '不限'} 筆/秒"
          f"｜預設槓桿：{a.default_leverage or '沿用帳戶設定'}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
