#!/usr/bin/env python3
"""
離線測試：啟動一個模擬 OneBullEx 的伺服器（獨立實作簽名驗證）與轉接程式，
再以 FMZ 託管者的格式送出請求，檢查每個功能的回應。

執行：python3 tests/test_plugin.py
"""
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import onebullex_fmz_plugin as plugin  # noqa: E402

API_KEY, SECRET = "test_key", "test_secret"
MOCK_PORT, PLUGIN_PORT = 18901, 18902

# ---------------- 模擬 OneBullEx ----------------

STATE = {"orders": {}, "visible_at": {}, "next_id": 1000, "leverage": 20, "adjust_calls": [],
         "positions": [{"symbol": "btc_usdt", "positionId": "555", "positionType": "CROSSED",
                        "positionSide": "LONG", "positionSize": "3", "availableCloseSize": "3",
                        "entryPrice": "60000", "isolatedMargin": "0", "leverage": 10,
                        "contractSize": "0.001"}],
         "last_body": None}


def mock_verify(headers, params):
    """獨立依文件 3.3 重算簽名。"""
    items = {"nonce": headers.get("X-Nonce"), "timestamp": headers.get("X-Timestamp")}
    for k, v in params.items():
        if v is None or isinstance(v, (dict, list)):
            continue
        items[k] = v if isinstance(v, str) else json.dumps(v)
    s = "&".join(f"{k}={items[k]}" for k in sorted(items))
    expect = hmac.new(SECRET.encode(), s.encode(), hashlib.sha256).hexdigest()
    if headers.get("X-API-KEY") != API_KEY:
        return "not-find-user-api"
    if abs(int(headers.get("X-Timestamp", 0)) - time.time()) > 30:
        return "timestamp-error"
    if headers.get("X-Signature") != expect:
        return "code-sign-not-match"
    return None


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, data, code=0, msg="success"):
        body = json.dumps({"code": code, "msg": msg, "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def route(self, method):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        if method == "GET":
            params = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        else:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            params = json.loads(raw or b"{}")
            STATE["last_body"] = params
        if not path.startswith("/v2/public/"):
            err = mock_verify(self.headers, params)
            if err:
                return self.reply(None, 1, err)

        if path == "/v2/public/symbol/all":
            return self.reply(["btc_usdt", "eth_usdt", "btcspartans_usdt", "ethspartans_usdt", "xauspartans_usdt"])
        if path == "/v2/public/q/agg-ticker":
            return self.reply({"t": 1760500000000, "s": params["symbol"], "c": "61000", "h": "62000",
                               "l": "59000", "a": "1234", "v": "75000000", "o": "60000", "r": "0.016",
                               "bp": "60999.5", "ap": "61000.5"})
        if path == "/v2/public/q/depth":
            return self.reply({"t": 1760500000000, "s": params["symbol"], "u": 1,
                               "b": [["60999.5", "10"], ["60999", "5"]],
                               "a": [["61000.5", "8"], ["61001", "4"]]})
        if path == "/v2/public/q/deal":
            return self.reply([{"t": 1760500000002, "s": params["symbol"], "p": "61000", "a": "2", "m": "SELL"},
                               {"t": 1760500000001, "s": params["symbol"], "p": "60999", "a": "1", "m": "BUY"}])
        if path == "/v2/public/q/kline":
            assert params["interval"] == "1h", params
            return self.reply([{"s": params["symbol"], "t": 1760503600000, "o": "2", "c": "3", "h": "4", "l": "1", "a": "9", "v": "0"},
                               {"s": params["symbol"], "t": 1760500000000, "o": "1", "c": "2", "h": "3", "l": "0.5", "a": "8", "v": "0"}])
        if path == "/v2/public/q/symbol-mark-price":
            return self.reply({"s": params["symbol"], "p": "61000", "t": 1760500000000})
        if path == "/v2/balance/list":
            return self.reply([{"coin": "usdt", "walletBalance": "1000", "availableBalance": "800"}])
        if path == "/v2/order/create":
            # 與正式行為一致：開倉單的槓桿必須等於持倉設定的槓桿
            if not params.get("positionId") and params.get("leverage") != STATE["leverage"]:
                return self.reply(None, 1, "order_leverage_not_match_position_leverage")
            oid = STATE["next_id"]
            STATE["next_id"] += 1
            STATE["visible_at"][oid] = time.time() + 0.6
            STATE["orders"][oid] = dict(params, orderId=str(oid), state="NEW", executedQty="0", avgPrice="0", createdTime=1760500000000 + oid)
            return self.reply(str(oid))
        if path == "/v2/order/detail":
            if time.time() < STATE["visible_at"].get(int(params["orderId"]), 0):
                return self.reply(None, 1, "invalid_order")
            o = STATE["orders"].get(int(params["orderId"]))
            return self.reply(o) if o else self.reply(None, 1, "invalid_order")
        if path == "/v2/order/all/listUnfinished":
            return self.reply([o for o in STATE["orders"].values() if o["state"] == "NEW"])
        if path == "/v2/order/list-history":
            return self.reply({"items": [o for o in STATE["orders"].values() if o["state"] != "NEW"],
                               "hasPrev": False, "hasNext": False})
        if path == "/v2/order/cancel":
            o = STATE["orders"].get(int(params["orderId"]))
            if not o:
                return self.reply(None, 1, "invalid_order")
            o["state"] = "CANCELED"
            return self.reply(True)
        if path == "/v2/position/list":
            return self.reply(STATE["positions"])
        if path == "/v2/position/adjust-leverage":
            STATE["leverage"] = params["leverage"]
            STATE["adjust_calls"].append(params["leverage"])
            return self.reply(True)
        if path == "/v2/position/confs":
            return self.reply([{"symbol": params["symbol"], "positionType": "CROSSED", "positionSide": s,
                                "positionModel": "AGGREGATION", "leverage": STATE["leverage"]}
                               for s in ("BOTH", "LONG", "SHORT")])
        return self.reply(None, 1, "not_found:" + path)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


# ---------------- 測試 ----------------

def fmz(method, params=None, key=API_KEY, secret=SECRET, path="/OneBullEx", http_method=None):
    body = json.dumps({"access_key": key, "secret_key": secret, "method": method,
                       "nonce": time.time_ns(), "params": params or {}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PLUGIN_PORT}{path}", data=body, method="POST")
    if http_method:
        req.add_header("Http-Method", http_method)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  -> {detail}" if not cond else ""))


def main():
    # 1. 簽名字串與官方文件範例逐字比對
    s = plugin.build_sign_string("abc123xyz", "1711900000",
                                 {"symbol": "btc_usdt", "timeRangeType": "UTC_P_8"})
    check("簽名字串（GET 文件範例）",
          s == "nonce=abc123xyz&symbol=btc_usdt&timeRangeType=UTC_P_8&timestamp=1711900000", s)
    s = plugin.build_sign_string("def456uvw", "1711900000",
                                 {"symbol": "btc_usdt", "orderSide": "BUY", "price": "50000", "origQty": "1",
                                  "orderType": "LIMIT", "positionSide": "LONG", "timeInForce": "GTC"})
    check("簽名字串（POST 文件範例）",
          s == "nonce=def456uvw&orderSide=BUY&orderType=LIMIT&origQty=1&positionSide=LONG"
               "&price=50000&symbol=btc_usdt&timeInForce=GTC&timestamp=1711900000", s)

    # 2. 啟動模擬伺服器與轉接程式
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Mock).serve_forever, daemon=True).start()
    limits = plugin.Limits(["btc_usdt", "eth_usdt"], max_order_qty=10, max_leverage=20, max_orders_per_sec=50)
    adapter = plugin.Adapter(f"http://127.0.0.1:{MOCK_PORT}", limits)
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", PLUGIN_PORT),
                     plugin.make_handler(adapter, "/OneBullEx", False)).serve_forever, daemon=True).start()
    time.sleep(0.3)

    # 3. 行情
    r = fmz("ticker", {"symbol": "BTC_USDT.swap"})
    check("GetTicker", r.get("data", {}).get("buy") == "60999.5" and r["data"]["sell"] == "61000.5", r)
    r = fmz("depth", {"symbol": "BTC_USDT", "limit": "30"})
    check("GetDepth", r.get("data", {}).get("asks", [[0]])[0] == [61000.5, 8.0], r)
    r = fmz("trades", {"symbol": "BTC_USDT"})
    check("GetTrades（時間由舊到新）", [t["type"] for t in r.get("data", [])] == ["buy", "sell"], r)
    r = fmz("records", {"symbol": "BTC_USDT", "period": "60", "limit": "500"})
    check("GetRecords（秒、由舊到新）", r.get("data", [[0]])[0][0] == 1760500000, r)

    # 4. 帳戶
    r = fmz("accounts")
    check("GetAccount", r.get("data") == [{"currency": "USDT", "free": "800.0", "frozen": "200.0"}], r)
    r = fmz("accounts", secret="wrong")
    check("錯誤金鑰會回報簽名錯誤", "code-sign-not-match" in r.get("error", ""), r)

    # 5. 槓桿、方向
    r = fmz("io", {"code": 0, "args": [10]})
    check("SetMarginLevel(10)", r.get("data") == 10 and STATE["leverage"] == 10, r)
    r = fmz("io", {"code": 0, "args": [50]})
    check("槓桿超過上限被擋", "超過上限" in r.get("error", ""), r)
    r = fmz("io", {"code": 2, "args": ["quarter"]})
    check("非永續合約被擋", "永續" in r.get("error", ""), r)

    # 6. 開多限價單
    fmz("io", {"code": 1, "args": ["buy"]})
    r = fmz("trade", {"symbol": "BTC_USDT", "type": "buy", "price": "60500", "amount": "2"})
    oid = r.get("data", {}).get("id", "")
    body = STATE["last_body"] or {}
    check("開多限價單", oid.startswith("BTC_USDT,") and body.get("orderSide") == "BUY"
          and body.get("positionSide") == "LONG" and body.get("orderType") == "LIMIT"
          and body.get("leverage") == 10, (r, body))

    r = fmz("order", {"id": oid, "symbol": "BTC_USDT"})
    check("GetOrder", r.get("data", {}).get("status") == "pending" and r["data"]["offset"] == 0 and r["data"]["time"] > 0, r)
    r = fmz("orders", {"symbol": "BTC_USDT"})
    check("GetOrders", len(r.get("data", [])) == 1, r)
    r = fmz("cancel", {"id": oid, "symbol": "BTC_USDT"})
    check("CancelOrder", r.get("data") is True, r)
    r = fmz("historyorders", {"symbol": "BTC_USDT", "since": 0, "limit": 0})
    check("GetHistoryOrders", r.get("data", [{}])[0].get("status") == "canceled", r)

    # 7. 平多市價單（自動帶 positionId）
    fmz("io", {"code": 1, "args": ["closebuy"]})
    r = fmz("trade", {"symbol": "BTC_USDT", "type": "sell", "price": "-1", "amount": "3"})
    body = STATE["last_body"] or {}
    check("平多市價單帶上持倉 ID", "data" in r and body.get("positionId") == 555
          and body.get("orderType") == "MARKET" and "leverage" not in body, (r, body))
    r = fmz("trade", {"symbol": "BTC_USDT", "type": "sell", "price": "-1", "amount": "4"})
    check("平倉超過持倉被擋", "超過可平數量" in r.get("error", ""), r)
    r = fmz("trade", {"symbol": "BTC_USDT", "type": "buy", "price": "-1", "amount": "1"})
    check("方向不符被擋（closebuy 卻買入）", "不符" in r.get("error", ""), r)

    # 8. 持倉
    r = fmz("io", {"code": 3, "args": []})
    p = (r.get("data") or [{}])[0]
    check("GetPosition（含未實現盈虧）", p.get("Amount") == 3 and p.get("Type") == 0
          and abs(p.get("Profit", 0) - 3.0) < 1e-9, r)

    # 9. 安全限制
    fmz("io", {"code": 1, "args": ["buy"]})
    r = fmz("trade", {"symbol": "SOL_USDT", "type": "buy", "price": "100", "amount": "1"})
    check("不在允許清單的合約被擋", "允許清單" in r.get("error", ""), r)
    r = fmz("trade", {"symbol": "BTC_USDT", "type": "buy", "price": "60000", "amount": "11"})
    check("單筆超過張數上限被擋", "上限" in r.get("error", ""), r)
    r = fmz("trade", {"symbol": "BTC_USDT", "type": "buy", "price": "60000", "amount": "1.5"})
    check("非整數張被擋", "整數張" in r.get("error", ""), r)
    r = fmz("ticker", {"symbol": "BTC_USDT"}, path="/Wrong")
    check("路徑錯誤會提示", "路徑錯誤" in r.get("error", ""), r)

    limits.max_orders_per_sec = 2
    limits._order_times.clear()
    errs = [fmz("trade", {"symbol": "BTC_USDT", "type": "buy", "price": "60000", "amount": "1"}).get("error", "")
            for _ in range(4)]
    check("下單頻率超過上限被擋", sum("頻率" in e for e in errs) == 2, errs)
    limits.max_orders_per_sec = 50

    # 10. 淨部位模式：新版 FMZ 託管者不轉送 SetDirection / SetMarginLevel
    adapter._states.clear()
    STATE["leverage"] = 20
    STATE["positions"][0]["positionSize"] = STATE["positions"][0]["availableCloseSize"] = "3"
    r = fmz("trade", {"symbol": "btc_usdt", "type": "sell", "price": "90000", "amount": "2"})
    body = STATE["last_body"] or {}
    check("淨部位：持有多單時賣出 = 平多", "data" in r and body.get("positionSide") == "LONG"
          and body.get("orderSide") == "SELL" and body.get("positionId") == 555, (r, body))
    r = fmz("trade", {"symbol": "btc_usdt", "type": "sell", "price": "90000", "amount": "4"})
    check("淨部位：賣出超過多單數量被擋（不自動反手）", "反手" in r.get("error", ""), r)
    r = fmz("trade", {"symbol": "btc_usdt", "type": "buy", "price": "60000", "amount": "1"})
    body = STATE["last_body"] or {}
    check("淨部位：沒有空單時買入 = 開多，自動帶帳戶槓桿", "data" in r and body.get("positionSide") == "LONG"
          and body.get("leverage") == 20 and "positionId" not in body, (r, body))
    saved = STATE["positions"]
    STATE["positions"] = []
    r = fmz("trade", {"symbol": "btc_usdt", "type": "sell", "price": "90000", "amount": "1"})
    body = STATE["last_body"] or {}
    check("淨部位：沒有多單時賣出 = 開空", "data" in r and body.get("positionSide") == "SHORT"
          and body.get("orderSide") == "SELL" and body.get("leverage") == 20, (r, body))
    STATE["positions"] = saved

    # 11. 透過 exchange.IO 調整槓桿
    r = fmz("__api_/v2/position/adjust-leverage", {"symbol": "btc_usdt", "leverage": "5"}, http_method="POST")
    check("exchange.IO 調整槓桿", r.get("data") == 5 and STATE["leverage"] == 5, r)
    r = fmz("trade", {"symbol": "btc_usdt", "type": "buy", "price": "60000", "amount": "1"})
    check("調整後開倉帶新槓桿", "data" in r and (STATE["last_body"] or {}).get("leverage") == 5, r)
    r = fmz("__api_/v2/position/adjust-leverage", {"symbol": "btc_usdt", "leverage": "50"}, http_method="POST")
    check("exchange.IO 槓桿超過上限被擋", "超過上限" in r.get("error", ""), r)
    r = fmz("__api_/v2/order/create", {"symbol": "btc_usdt"}, http_method="POST")
    check("exchange.IO 不能直接下單", "只開放" in r.get("error", ""), r)
    r = fmz("__api_/v2/position/list", {"symbol": "btc_usdt"})
    check("exchange.IO 查持倉", isinstance(r.get("data"), list) and r["data"][0]["positionId"] == "555", r)

    # 12. 啟動參數指定預設槓桿
    adapter._states.clear()
    adapter.default_leverage = 7
    STATE["adjust_calls"].clear()
    r = fmz("trade", {"symbol": "btc_usdt", "type": "buy", "price": "60000", "amount": "1"})
    check("預設槓桿：先套用到合約再開倉", "data" in r and STATE["adjust_calls"] == [7]
          and (STATE["last_body"] or {}).get("leverage") == 7, (r, STATE["adjust_calls"]))
    fmz("trade", {"symbol": "btc_usdt", "type": "buy", "price": "60000", "amount": "1"})
    check("預設槓桿：不重複呼叫調整", STATE["adjust_calls"] == [7], STATE["adjust_calls"])
    adapter.default_leverage = 0

    # 13. 非同步下單：剛下的單查不到時，轉接程式內部等待後再查
    fmz("io", {"code": 1, "args": ["buy"]})
    r = fmz("trade", {"symbol": "BTC_USDT", "type": "buy", "price": "60000", "amount": "1"})
    t0 = time.time(); q = fmz("order", {"id": r["data"]["id"]})
    check("剛下的單會等待後查到，不回錯誤", "data" in q and 0.4 < time.time() - t0 < 2.5, (q, time.time() - t0))
    t0 = time.time(); q = fmz("order", {"id": "BTC_USDT,999999"})
    check("真的不存在的單在約 2 秒後回錯誤", "查無此訂單" in q.get("error", "") and time.time() - t0 < 3.5, q)

    # 14. 斯巴達專屬交易對與預設不限制
    STATE["last_ticker_symbol"] = None
    r = fmz("ticker", {"symbol": "BTCSPARTANS_USDT"})
    check("斯巴達專屬交易對：BTCSPARTANS_USDT 查報價", r.get("data", {}).get("symbol") == "BTCSPARTANS_USDT", r)
    saved_limits, saved_pos = adapter.limits, STATE["positions"]
    adapter.limits = plugin.Limits(None, 0, 0, 0)   # 與安裝預設相同：不限交易對、張數、槓桿
    adapter._states.clear()
    STATE["positions"] = []
    r = fmz("trade", {"symbol": "XAUSPARTANS_USDT", "type": "buy", "price": "-1", "amount": "500"})
    body = STATE["last_body"] or {}
    check("斯巴達專屬交易對：XAUSPARTANS_USDT 開多 500 張（預設不限張數）",
          "data" in r and body.get("symbol") == "xauspartans_usdt" and body.get("origQty") in ("500", 500)
          and r["data"]["id"].startswith("XAUSPARTANS_USDT,"), (r, body))
    r = fmz("__api_/v2/position/adjust-leverage", {"symbol": "ethspartans_usdt", "leverage": "50"}, http_method="POST")
    check("預設不限槓桿：exchange.IO 設 50 倍", r.get("data") == 50, r)
    r = fmz("__api_/v2/public/q/symbol-mark-price", {"symbol": "BTCSPARTANS_USDT"})
    check("exchange.IO 查詢時交易對名稱自動對應", (r.get("data") or {}).get("s") == "btcspartans_usdt", r)
    adapter.limits, STATE["positions"] = saved_limits, saved_pos
    saved_known = set(plugin.KNOWN_SYMBOLS)
    plugin.KNOWN_SYMBOLS.clear(); plugin.KNOWN_SYMBOLS.update({"btc_usdt", "btcspartansusdt"})
    check("交易所名稱沒有底線時也能對應",
          plugin.to_ob_symbol("BTCSPARTANS_USDT") == "btcspartansusdt"
          and plugin.to_fmz_symbol("btcspartansusdt") == "BTCSPARTANS_USDT",
          (plugin.to_ob_symbol("BTCSPARTANS_USDT"), plugin.to_fmz_symbol("btcspartansusdt")))
    plugin.KNOWN_SYMBOLS.clear(); plugin.KNOWN_SYMBOLS.update(saved_known)

    passed = sum(ok for _, ok in RESULTS)
    print(f"\n{passed}/{len(RESULTS)} 項通過")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
