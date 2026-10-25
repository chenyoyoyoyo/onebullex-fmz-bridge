#!/usr/bin/env python3
"""
不經過 FMZ，直接以 FMZ 託管者的請求格式呼叫轉接程式，在測試網跑一輪下單流程。

    python3 smoke_trade.py          掛一張不會成交的限價單 -> 查詢 -> 撤單（不產生持倉）
    python3 smoke_trade.py --fill   另外市價開多 1 張 -> 查持倉 -> 市價平多（約 8 美元，測平倉路徑）
    python3 smoke_trade.py --hedge  雙向：開多 1 張、再開空 1 張 -> 確認多空同時存在 -> 各自平倉
    python3 smoke_trade.py --split  分倉：暫時切成分倉 -> 開多兩次 -> 確認兩筆獨立持倉 -> 依序平倉 -> 切回合倉

只能在測試網執行。讀取環境變數 OBX_API_KEY / OBX_SECRET。
"""
import os
import sys
import time

import onebullex_fmz_plugin as p

SYM = "BTC_USDT"


def main():
    fill = "--fill" in sys.argv
    if os.environ.get("OBX_ENV", "test") != "test":
        sys.exit("這支腳本只能在測試網執行")
    key, secret = os.environ.get("OBX_API_KEY"), os.environ.get("OBX_SECRET")
    if not key or not secret:
        sys.exit("請先設定 OBX_API_KEY 和 OBX_SECRET")

    adapter = p.Adapter(p.BASE_URLS["test"], p.Limits(["btc_usdt"], 5, 10, 5))
    client = p.OneBullExClient(p.BASE_URLS["test"], key, secret)
    ok = True

    def call(label, method, params=None, expect_error=False):
        nonlocal ok
        req = {"access_key": key, "secret_key": secret, "method": method, "params": params or {}}
        try:
            r = adapter.handle(req)
        except p.PluginError as e:
            r = {"error": str(e)}
        bad = ("error" in r) != expect_error
        ok &= not bad
        print(("FAIL " if bad else "OK   ") + label + "：" + str(r.get("error", r.get("data")))[:300])
        return r.get("data")

    tk = call("報價", "ticker", {"symbol": SYM})
    if not tk:
        sys.exit("拿不到報價，停止")
    last = float(tk["last"])
    call("帳戶", "accounts")
    call("設定槓桿 5 倍", "io", {"code": 0, "args": [5], "symbol": SYM})
    call("設定方向：開多", "io", {"code": 1, "args": ["buy"]})

    price = round(last * 0.9, 1)
    o = call(f"掛限價開多 1 張 @ {price}（低於市價 10%，不會成交）", "trade",
             {"symbol": SYM, "type": "buy", "price": str(price), "amount": "1"})
    if o:
        oid = o["id"]
        info = None
        for _ in range(5):  # 非同步下單，稍等再查
            time.sleep(1)
            try:
                info = adapter.handle({"access_key": key, "secret_key": secret,
                                       "method": "order", "params": {"id": oid}})["data"]
                break
            except p.PluginError:
                continue
        ok &= info is not None
        print(("OK   " if info else "FAIL ") + f"查單：{info}")
        call("未成交訂單", "orders", {"symbol": SYM})
        call("撤單", "cancel", {"id": oid, "symbol": SYM})
        time.sleep(1)
        call("撤單後狀態", "order", {"id": oid})

    call("超過單筆上限（6 張）應被擋", "trade",
         {"symbol": SYM, "type": "buy", "price": str(price), "amount": "6"}, expect_error=True)
    call("非允許合約應被擋", "trade",
         {"symbol": "ETH_USDT", "type": "buy", "price": "1", "amount": "1"}, expect_error=True)

    if fill:
        print("\n--- 市價開平倉測試 ---")
        call("市價開多 1 張", "trade", {"symbol": SYM, "type": "buy", "price": "-1", "amount": "1"})
        time.sleep(2)
        call("持倉", "positions", {"symbol": SYM})
        call("設定方向：平多", "io", {"code": 1, "args": ["closebuy"]})
        call("市價平多 1 張", "trade", {"symbol": SYM, "type": "sell", "price": "-1", "amount": "1"})
        time.sleep(2)
        call("平倉後持倉（應為空）", "positions", {"symbol": SYM})

    def direction(d, pid=None):
        params = {"direction": d}
        if pid:
            params["positionId"] = pid
        call(f"設定方向：{d}" + (f"（持倉 {pid}）" if pid else ""), "__api_/v2/fmz/direction", params)

    def positions():
        rows = client.request("GET", "/v2/position/list", {"symbol": "btc_usdt"}, private=True) or []
        return [r for r in rows if float(r.get("positionSize") or 0) > 0]

    def report(label, cond, detail):
        nonlocal ok
        ok &= bool(cond)
        print(("OK   " if cond else "FAIL ") + f"{label}：{detail}")

    if "--hedge" in sys.argv:
        print("\n--- 雙向持倉測試（同時持有多空） ---")
        direction("buy")
        call("市價開多 1 張", "trade", {"symbol": SYM, "type": "buy", "price": "-1", "amount": "1"})
        time.sleep(2)
        direction("sell")
        call("市價開空 1 張（持有多單時）", "trade", {"symbol": SYM, "type": "sell", "price": "-1", "amount": "1"})
        time.sleep(2)
        sides = {r.get("positionSide"): r.get("positionSize") for r in positions()}
        report("多空同時存在", "LONG" in sides and "SHORT" in sides, sides)
        direction("closebuy")
        call("市價平多 1 張", "trade", {"symbol": SYM, "type": "sell", "price": "-1", "amount": "1"})
        time.sleep(2)
        direction("closesell")
        call("市價平空 1 張", "trade", {"symbol": SYM, "type": "buy", "price": "-1", "amount": "1"})
        time.sleep(2)
        left = positions()
        report("平倉後持倉（應為空）", not left, left)
        direction("net")

    if "--split" in sys.argv:
        print("\n--- 分倉測試（同方向多筆獨立持倉） ---")
        confs = client.request("GET", "/v2/position/confs", {"symbol": "btc_usdt"}, private=True) or []
        ptype = next((c.get("positionType") for c in confs if c.get("positionType")), "CROSSED")
        if positions():
            sys.exit("目前仍有持倉，請先平倉再跑分倉測試")
        print("切換為分倉：", client.request("POST", "/v2/position/change-type",
              {"symbol": "btc_usdt", "positionType": ptype, "positionModel": "DISAGGREGATION"}, private=True))
        try:
            direction("buy")
            call("市價開多 1 張（第一筆）", "trade", {"symbol": SYM, "type": "buy", "price": "-1", "amount": "1"})
            time.sleep(2)
            call("市價開多 1 張（第二筆）", "trade", {"symbol": SYM, "type": "buy", "price": "-1", "amount": "1"})
            time.sleep(2)
            longs = [r for r in positions() if r.get("positionSide") == "LONG"]
            report("同方向兩筆獨立持倉", len(longs) == 2, [(r.get("positionId"), r.get("positionSize")) for r in longs])
            if longs:
                print("持倉欄位（確認排序依據）：", sorted(longs[0].keys()))
            last_id = longs[-1].get("positionId") if longs else None
            direction("closebuy", last_id)
            call(f"指定平倉 {last_id}", "trade", {"symbol": SYM, "type": "sell", "price": "-1", "amount": "1"})
            time.sleep(2)
            left = [r.get("positionId") for r in positions()]
            report("指定的那筆已平、另一筆還在", last_id not in left and len(left) == 1, left)
            direction("closebuy")
            call("先進先出平倉剩下一筆", "trade", {"symbol": SYM, "type": "sell", "price": "-1", "amount": "1"})
            time.sleep(2)
            left = positions()
            report("平倉後持倉（應為空）", not left, left)
        finally:
            direction("net")
            if not positions():
                print("切回合倉：", client.request("POST", "/v2/position/change-type",
                      {"symbol": "btc_usdt", "positionType": ptype, "positionModel": "AGGREGATION"}, private=True))
            else:
                print("仍有持倉，未切回合倉。請到網頁平倉後，把持倉模式改回『合倉』")

    try:
        print("\n持倉模式設定：", client.request("GET", "/v2/position/confs", {"symbol": "btc_usdt"}, private=True))
    except p.PluginError as e:
        print("\n持倉模式設定查詢失敗：", e)
    print("\n全部符合預期" if ok else "\n有項目不符預期，請把輸出貼給我")


if __name__ == "__main__":
    main()
