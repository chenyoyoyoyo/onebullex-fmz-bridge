#!/usr/bin/env python3
"""
離線測試：TradingView 訊號接收程式（tv_webhook.py）。
模擬 OneBullEx（訂單立即成交、可同時持有多空、支援分倉多筆持倉），不連網、不下真單。

執行：python3 tests/test_tv.py
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import onebullex_fmz_plugin as plugin  # noqa: E402
import tv_webhook as tv  # noqa: E402

MOCK_PORT, TV_PORT = 18911, 18912
PASS = "correct-horse-battery"
tv.POLL_INTERVAL = 0.05

S = {"positions": [], "orders": {}, "next_oid": 5000, "next_pid": 100, "created": [], "leverage": 20,
     "adjust": [], "fail_next": False}
SPECS = {"btc_usdt": "0.0001", "btcspartans_usdt": "0.0001", "ethspartans_usdt": "0.01"}


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
        if method == "GET":
            p = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        else:
            p = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        path = u.path
        if path == "/v2/public/symbol/all":
            return self.reply(list(SPECS))
        if path == "/v2/public/symbol/detail":
            return self.reply({"symbol": p["symbol"], "contractSize": SPECS[p["symbol"]], "minQty": "1"})
        if path == "/v2/position/list":
            return self.reply([x for x in S["positions"] if x["symbol"] == p.get("symbol", x["symbol"])])
        if path == "/v2/position/confs":
            return self.reply([{"symbol": p["symbol"], "positionSide": s, "leverage": S["leverage"]}
                               for s in ("LONG", "SHORT")])
        if path == "/v2/position/adjust-leverage":
            S["leverage"] = p["leverage"]
            S["adjust"].append(p["leverage"])
            return self.reply(True)
        if path == "/v2/order/create":
            S["created"].append(p)
            qty = int(p["origQty"])
            oid = S["next_oid"]
            S["next_oid"] += 1
            if S["fail_next"]:
                S["fail_next"] = False
                S["orders"][oid] = {"orderId": oid, "state": "CANCELED", "executedQty": "0"}
                return self.reply(str(oid))
            if "positionId" in p:      # 平倉
                pos = next(x for x in S["positions"] if int(x["positionId"]) == p["positionId"])
                assert pos["positionSide"] == p["positionSide"] and qty <= int(pos["positionSize"]), (pos, p)
                left = int(pos["positionSize"]) - qty
                if left:
                    pos["positionSize"] = pos["availableCloseSize"] = str(left)
                else:
                    S["positions"].remove(pos)
            else:                      # 開倉：合倉時併入同方向
                if p.get("leverage") != S["leverage"]:
                    return self.reply(None, 1, "order_leverage_not_match_position_leverage")
                same = [x for x in S["positions"] if x["symbol"] == p["symbol"] and x["positionSide"] == p["positionSide"]]
                if same and not S.get("split"):
                    n = int(same[0]["positionSize"]) + qty
                    same[0]["positionSize"] = same[0]["availableCloseSize"] = str(n)
                else:
                    S["positions"].append({"symbol": p["symbol"], "positionSide": p["positionSide"],
                                           "positionSize": str(qty), "availableCloseSize": str(qty),
                                           "positionId": str(S["next_pid"]), "contractSize": SPECS[p["symbol"]]})
                    S["next_pid"] += 1
            S["orders"][oid] = {"orderId": oid, "state": "FILLED", "executedQty": str(qty), "avgPrice": "80000"}
            return self.reply(str(oid))
        if path == "/v2/order/detail":
            o = S["orders"].get(int(p["orderId"]))
            return self.reply(o) if o else self.reply(None, 1, "invalid_order")
        return self.reply(None, 1, "not_found:" + path)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


def post(obj, xff=None, raw=None):
    data = raw if raw is not None else json.dumps(obj).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{TV_PORT}/webhook", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if xff:
        req.add_header("X-Forwarded-For", xff)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def settle(receiver):
    for _ in range(200):
        if receiver.idle():
            time.sleep(0.15)
            if receiver.idle():
                return
        time.sleep(0.05)


def net(sym="btcspartans_usdt"):
    return sum(int(p["positionSize"]) * (1 if p["positionSide"] == "LONG" else -1)
               for p in S["positions"] if p["symbol"] == sym)


def main():
    # 純函式
    check("張數換算：0.0003 BTC = 3 張", tv.to_contracts(Decimal("0.0003"), "coin", Decimal("0.0001")) == 3)
    check("張數換算：浮點誤差 0.00029999999 BTC 視為 3 張",
          tv.to_contracts(Decimal("0.00029999999"), "coin", Decimal("0.0001")) == 3)
    check("張數換算：0.00025 BTC 無條件捨去為 2 張", tv.to_contracts(Decimal("0.00025"), "coin", Decimal("0.0001")) == 2)
    check("張數換算：空單 -0.02 ETH = -2 張", tv.to_contracts(Decimal("-0.02"), "coin", Decimal("0.01")) == -2)
    check("訊息：market_position=short size=2 → -2",
          tv.parse_signal({"symbol": "X_USDT", "market_position": "short", "size": "2"})[1] == -2)
    check("訊息：flat → 0", tv.parse_signal({"symbol": "X_USDT", "market_position": "flat", "size": "0"})[1] == 0)
    check("訊息：action long qty 3 → +3（目標持倉，不是加碼）",
          tv.parse_signal({"symbol": "X_USDT", "action": "long", "qty": 3})[1] == 3)
    check("訊息：multiplier 0.5 × target 4 → 2",
          tv.parse_signal({"symbol": "X_USDT", "target": 4, "multiplier": 0.5})[1] == 2)
    try:
        tv.parse_signal({"symbol": "X_USDT", "market_position": "{{strategy.market_position}}"})
        check("訊息：沒替換的 TradingView 變數會被擋下", False)
    except tv.SignalError:
        check("訊息：沒替換的 TradingView 變數會被擋下", True)

    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Mock).serve_forever, daemon=True).start()
    client = plugin.OneBullExClient(f"http://127.0.0.1:{MOCK_PORT}", "k", "s")
    plugin.KNOWN_SYMBOLS.update(SPECS)
    ex = tv.Executor(client, dry_run=False)
    rc = tv.Receiver(ex, PASS)
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", TV_PORT), tv.make_handler(rc)).serve_forever,
                     daemon=True).start()
    time.sleep(0.2)
    TVIP = tv.TRADINGVIEW_IPS[0]
    base = {"passphrase": PASS, "symbol": "BTCSPARTANS_USDT"}

    # 安全
    code, _ = post(dict(base, target=1), xff="1.2.3.4")
    check("非 TradingView IP 被拒（403）", code == 403)
    code, _ = post(dict(base, passphrase="wrong-pass-123", target=1), xff=TVIP)
    check("passphrase 錯誤被拒（401）", code == 401)
    code, _ = post(None, xff=TVIP, raw=b"BUY BTC now")
    check("非 JSON 訊息被拒（400）", code == 400)
    code, r = post(dict(base, market_position="long"), xff=TVIP)
    check("market_position=long 但沒有 size：視為目標 0，不下單", code == 200, r)
    settle(rc)
    check("沒有下任何單", S["created"] == [] and net() == 0, S["created"])

    # 目標持倉
    code, r = post(dict(base, market_position="long", size="0.0002", unit="coin"), xff=TVIP)
    settle(rc)
    check("開多 2 張（0.0002 BTC 換算），帶上帳戶槓桿",
          code == 200 and net() == 2 and S["created"][-1]["leverage"] == 20 and S["created"][-1]["orderType"] == "MARKET",
          (code, r, S["positions"], S["created"]))
    n = len(S["created"])
    post(dict(base, market_position="long", size="0.0002", unit="coin"), xff=TVIP)
    settle(rc)
    check("重送同一則訊號不會重複下單", len(S["created"]) == n and net() == 2)
    post(dict(base, target=-3), xff=TVIP)
    settle(rc)
    last2 = S["created"][-2:]
    check("反手：先平多 2 張，再開空 3 張",
          net() == -3 and last2[0]["positionSide"] == "LONG" and last2[0]["orderSide"] == "SELL"
          and last2[0]["origQty"] == "2" and "positionId" in last2[0]
          and last2[1]["positionSide"] == "SHORT" and last2[1]["origQty"] == "3", (last2, S["positions"]))
    post(dict(base, target=-1), xff=TVIP)
    settle(rc)
    check("減倉：平空 2 張，剩空 1 張", net() == -1 and S["created"][-1]["origQty"] == "2")
    post(dict(base, action="close"), xff=TVIP)
    settle(rc)
    check("action=close 平到空手", net() == 0 and not S["positions"])

    # 同時有多空（雙向帳戶殘留）→ 目標 +1：平掉空單，多單保留
    S["positions"] = [{"symbol": "btcspartans_usdt", "positionSide": "LONG", "positionSize": "1",
                       "availableCloseSize": "1", "positionId": "900"},
                      {"symbol": "btcspartans_usdt", "positionSide": "SHORT", "positionSize": "1",
                       "availableCloseSize": "1", "positionId": "901"}]
    post(dict(base, target=1), xff=TVIP)
    settle(rc)
    check("多空同時存在時目標 +1：只平空 1 張", net() == 1 and len(S["positions"]) == 1
          and S["created"][-1]["positionSide"] == "SHORT")

    # 分倉：多筆多單，目標 0 → 依序平每一筆
    S["split"] = True
    S["positions"] = [{"symbol": "btcspartans_usdt", "positionSide": "LONG", "positionSize": s,
                       "availableCloseSize": s, "positionId": pid} for s, pid in (("2", "950"), ("1", "940"))]
    n = len(S["created"])
    post(dict(base, target=0), xff=TVIP)
    settle(rc)
    pids = [c.get("positionId") for c in S["created"][n:]]
    check("分倉：先平最早的一筆（ID 小），再平下一筆", net() == 0 and pids == [940, 950], pids)
    S["split"] = False

    # 成交失敗 → 停止、記錄錯誤，不繼續下一張
    S["fail_next"] = True
    n = len(S["created"])
    post(dict(base, target=2), xff=TVIP)
    settle(rc)
    check("訂單未成交時記錄失敗、不重送", len(S["created"]) == n + 1 and rc.history[-1]["ok"] is False
          and "未完整成交" in rc.history[-1]["error"], rc.history[-1])

    # 試跑模式
    ex.dry_run = True
    n = len(S["created"])
    post(dict(base, target=5), xff=TVIP)
    settle(rc)
    check("試跑模式：只記錄，不下單", len(S["created"]) == n and net() == 0)
    ex.dry_run = False

    # 持倉上限、交易對清單、槓桿設定
    ex.max_qty = 3
    post(dict(base, target=4), xff=TVIP)
    settle(rc)
    check("超過自設的持倉上限不執行", net() == 0 and "上限" in rc.history[-1].get("error", ""))
    ex.max_qty = 0
    rc.allowed_symbols = {"btc_usdt"}
    code, _ = post(dict(base, target=1), xff=TVIP)
    check("不在允許清單的交易對被拒（400）", code == 400)
    rc.allowed_symbols = None
    ex.leverage = 5
    post(dict(base, symbol="ETHSPARTANS_USDT", target=1), xff=TVIP)
    settle(rc)
    check("TV_LEVERAGE：開倉前設定槓桿並帶入", S["adjust"] == [5] and S["created"][-1]["leverage"] == 5
          and net("ethspartans_usdt") == 1, (S["adjust"], S["created"][-1]))

    # 連續訊號只執行最新的一則
    ex.leverage = 0
    S["leverage"] = 5
    orig = ex.move_to
    calls = []

    def slow(sym, target):
        calls.append(target)
        time.sleep(0.3)
        return orig(sym, target)
    ex.move_to = slow
    for t in (1, 2, 3):
        post(dict(base, target=t), xff=TVIP)
    time.sleep(1.2)
    settle(rc)
    check("執行中收到多則訊號：只補做最新的目標", calls[-1] == 3 and 2 not in calls and net() == 3, calls)
    ex.move_to = orig

    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} 項通過")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
