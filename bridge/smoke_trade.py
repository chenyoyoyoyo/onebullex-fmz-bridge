#!/usr/bin/env python3
"""
不經過 FMZ，直接以 FMZ 託管者的請求格式呼叫轉接程式，在測試網跑一輪下單流程。

    python3 smoke_trade.py          掛一張不會成交的限價單 -> 查詢 -> 撤單（不產生持倉）
    python3 smoke_trade.py --fill   另外市價開多 1 張 -> 查持倉 -> 市價平多（約 8 美元，測平倉路徑）
    python3 smoke_trade.py --hedge  雙向：開多 1 張、再開空 1 張 -> 確認多空同時存在 -> 各自平倉
    python3 smoke_trade.py --split  分倉：暫時切成分倉 -> 開多兩次 -> 確認兩筆獨立持倉 -> 依序平倉 -> 切回合倉

預設在測試網執行。讀取環境變數 OBX_API_KEY / OBX_SECRET。

正式環境小量驗證（會實際成交，需輸入 YES 確認）：
    python3 smoke_trade.py --prod --hedge
    python3 smoke_trade.py --prod --split --symbol BTCSPARTANS_USDT
正式環境的保護：
  - 該交易對必須完全沒有持倉，否則停止（避免平到既有策略的持倉）
  - 不更改帳戶槓桿；單筆最多 5 張；每一步只下 1 張
"""
import os
import sys
import time

import onebullex_fmz_plugin as p

SYM = "BTC_USDT"


def main():
    global SYM
    fill = "--fill" in sys.argv
    prod = "--prod" in sys.argv
    if "--symbol" in sys.argv:
        i = sys.argv.index("--symbol")
        if i + 1 >= len(sys.argv):
            sys.exit("--symbol 後面要接交易對，例如 BTCSPARTANS_USDT")
        SYM = sys.argv[i + 1].upper()
    env = "prod" if prod else "test"
    if not prod and os.environ.get("OBX_ENV", "test") != "test":
        sys.exit("OBX_ENV 不是 test；要在正式環境驗證請明確加上 --prod")
    key, secret = os.environ.get("OBX_API_KEY"), os.environ.get("OBX_SECRET")
    if not key or not secret:
        sys.exit("請先設定 OBX_API_KEY 和 OBX_SECRET")

    base = p.BASE_URLS[env]
    client = p.OneBullExClient(base, key, secret)
    adapter = p.Adapter(base, p.Limits(None, 5, 0, 5))
    adapter.load_symbols(client, force=True)
    ob_sym = p.to_ob_symbol(SYM)
    adapter.limits = p.Limits([ob_sym], 5, 0 if prod else 10, 5)
    ok = True

    if prod:
        trades = [x for x in ("--fill", "--hedge", "--split") if x in sys.argv]
        held = [r for r in (client.request("GET", "/v2/position/list", {"symbol": ob_sym}, private=True) or [])
                if float(r.get("positionSize") or 0) > 0]
        if held and trades:
            sys.exit(f"{SYM} 目前有持倉 {[(r.get('positionSide'), r.get('positionSize')) for r in held]}，"
                     "為避免動到既有策略的持倉，請在沒有持倉的帳戶或交易對上驗證")
        print(f"*** 正式環境 {base} ***")
        print(f"交易對 {SYM}；要執行：{' '.join(trades) or '只掛單後撤單（不成交）'}")
        print("每一步只下 1 張市價單，會實際成交並產生手續費；不更改帳戶槓桿。")
        if "--split" in sys.argv:
            print("--split 會暫時把此交易對切成『分倉』，結束後切回『合倉』；請確認沒有策略正在這個帳戶上跑。")
        if input("確認執行請輸入 YES：").strip() != "YES":
            sys.exit("已取消")

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
    if not prod:
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
        rows = client.request("GET", "/v2/position/list", {"symbol": ob_sym}, private=True) or []
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
        confs = client.request("GET", "/v2/position/confs", {"symbol": ob_sym}, private=True) or []
        ptype = next((c.get("positionType") for c in confs if c.get("positionType")), "CROSSED")
        if positions():
            sys.exit("目前仍有持倉，請先平倉再跑分倉測試")
        print("切換為分倉：", client.request("POST", "/v2/position/change-type",
              {"symbol": ob_sym, "positionType": ptype, "positionModel": "DISAGGREGATION"}, private=True))
        try:
            direction("buy")
            call("市價開多 1 張（第一筆）", "trade", {"symbol": SYM, "type": "buy", "price": "-1", "amount": "1"})
            time.sleep(2)
            call("市價開多 1 張（第二筆）", "trade", {"symbol": SYM, "type": "buy", "price": "-1", "amount": "1"})
            time.sleep(2)
            longs = sorted((r for r in positions() if r.get("positionSide") == "LONG"),
                           key=lambda r: int(r.get("positionId") or 0))
            report("同方向兩筆獨立持倉", len(longs) == 2, [(r.get("positionId"), r.get("positionSize")) for r in longs])
            if len(longs) == 2:
                oldest, newest = longs[0].get("positionId"), longs[1].get("positionId")
                direction("closebuy")
                call("先進先出平倉（應平最早的一筆）", "trade", {"symbol": SYM, "type": "sell", "price": "-1", "amount": "1"})
                time.sleep(2)
                left = [r.get("positionId") for r in positions()]
                report(f"最早的 {oldest} 已平、{newest} 還在", left == [newest], left)
                direction("closebuy", newest)
                call(f"指定平倉 {newest}", "trade", {"symbol": SYM, "type": "sell", "price": "-1", "amount": "1"})
                time.sleep(2)
            left = positions()
            report("平倉後持倉（應為空）", not left, left)
        finally:
            direction("net")
            if not positions():
                client.request("POST", "/v2/position/change-type",
                               {"symbol": ob_sym, "positionType": ptype, "positionModel": "AGGREGATION"}, private=True)
                models = set()
                for _ in range(10):      # 設定生效可能要幾秒
                    time.sleep(1)
                    confs = client.request("GET", "/v2/position/confs", {"symbol": ob_sym}, private=True) or []
                    models = {c.get("positionModel") for c in confs}
                    if models == {"AGGREGATION"}:
                        break
                report("已切回合倉", models == {"AGGREGATION"}, models)
            else:
                print("仍有持倉，未切回合倉。請到網頁平倉後，把持倉模式改回『合倉』")

    try:
        print("\n持倉模式設定：", client.request("GET", "/v2/position/confs", {"symbol": ob_sym}, private=True))
    except p.PluginError as e:
        print("\n持倉模式設定查詢失敗：", e)
    print("\n全部符合預期" if ok else "\n有項目不符預期，請把輸出貼給我")


if __name__ == "__main__":
    main()
