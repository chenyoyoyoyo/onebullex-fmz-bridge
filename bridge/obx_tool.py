#!/usr/bin/env python3
"""
OneBullEx 帳戶小工具（讀取環境變數 OBX_API_KEY / OBX_SECRET，預設測試網）

    python3 obx_tool.py balance            查合約帳戶、資金帳戶、持倉
    python3 obx_tool.py transfer 1000      資金帳戶 -> 合約帳戶
    python3 obx_tool.py transfer-back 500  合約帳戶 -> 資金帳戶
    python3 obx_tool.py symbols            列出所有交易對（含斯巴達專屬交易對），不需金鑰
    python3 obx_tool.py spec BTCSPARTANS_USDT  查合約規格與 FMZ 對應寫法，不需金鑰
    python3 obx_tool.py leverage BTCSPARTANS_USDT 5  調整該合約槓桿

連正式環境請先 export OBX_ENV=prod
"""
import os
import sys
import uuid

from onebullex_fmz_plugin import (BASE_URLS, KNOWN_SYMBOLS, OneBullExClient, PluginError,
                                  to_fmz_symbol, to_ob_symbol)


PUBLIC_CMDS = ("symbols", "spec")


def client(need_key=True):
    key, secret = os.environ.get("OBX_API_KEY"), os.environ.get("OBX_SECRET")
    if need_key and (not key or not secret):
        sys.exit("請先設定 OBX_API_KEY 和 OBX_SECRET")
    return OneBullExClient(BASE_URLS[os.environ.get("OBX_ENV", "test")], key or "", secret or "")


def load(c):
    rows = c.request("GET", "/v2/public/symbol/all") or []
    KNOWN_SYMBOLS.clear()
    KNOWN_SYMBOLS.update(str(r).lower() for r in rows if r)
    return sorted(KNOWN_SYMBOLS)


def symbols(c):
    rows = load(c)
    sp = [r for r in rows if "spartans" in r]
    print(f"共 {len(rows)} 個交易對")
    print("斯巴達專屬交易對：" + ("、".join(f"{r}（FMZ 寫 {to_fmz_symbol(r)}）" for r in sp) if sp else "此環境沒有"))
    print("全部：" + ", ".join(rows))


def spec(c, name):
    load(c)
    sym = to_ob_symbol(name)
    d = c.request("GET", "/v2/public/symbol/detail", {"symbol": sym}) or {}
    keys = ("contractSize", "minQty", "quantityPrecision", "pricePrecision", "minStepPrice",
            "maxLeverage", "supportPositionType")
    print(f"交易所名稱：{sym}｜FMZ 交易對寫：{to_fmz_symbol(sym)}")
    for k in keys:
        if k in d:
            print(f"  {k}：{d[k]}")
    cs = float(d.get("contractSize") or 0)
    if cs:
        print(f"  → 1 張 = {cs:g} 個{to_fmz_symbol(sym).split('_')[0]}；策略的 Buy/Sell 數量要填整數張")


def leverage(c, name, lev):
    load(c)
    sym = to_ob_symbol(name)
    c.request("POST", "/v2/position/adjust-leverage", {"symbol": sym, "leverage": int(lev)}, private=True)
    print(f"{sym} 槓桿已設為 {int(lev)} 倍")


def balance(c):
    fund = c.request("GET", "/v2/balance/funding", private=True) or {}
    print(f"資金帳戶（Funding）：可用 {fund.get('available')}，凍結 {fund.get('frozen')}，合計 {fund.get('balance')}")
    for b in c.request("GET", "/v2/balance/list", private=True) or []:
        print(f"合約帳戶（Futures）{str(b.get('coin')).upper()}：錢包 {b.get('walletBalance')}，可用 {b.get('availableBalance')}")
    try:
        r = c.request("GET", "/v2/bot/redeeming-info", private=True) or {}
        print(f"待處理贖回：{r.get('pendingCount')} 筆，金額 {r.get('estimatedAmount')}")
    except PluginError:
        pass
    pos = [p for p in (c.request("GET", "/v2/position/list", private=True) or []) if float(p.get("positionSize") or 0) > 0]
    print("持倉：" + ("無" if not pos else ""))
    for p in pos:
        print(f"  {p['symbol']} {p['positionSide']} {p['positionSize']} 張，均價 {p['entryPrice']}，槓桿 {p['leverage']}")


def transfer(c, amount, src, dst):
    no = c.request("POST", "/v2/balance/transfer",
                   {"billNo": uuid.uuid4().hex, "from": src, "to": dst, "amount": amount}, private=True)
    print(f"已轉帳 {amount} USDT：{src} -> {dst}，編號 {no}\n")
    balance(c)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    c = client(need_key=cmd not in PUBLIC_CMDS)
    try:
        if cmd == "symbols":
            symbols(c)
        elif cmd == "spec" and len(sys.argv) == 3:
            spec(c, sys.argv[2])
        elif cmd == "leverage" and len(sys.argv) == 4:
            leverage(c, sys.argv[2], sys.argv[3])
        elif cmd == "balance":
            balance(c)
        elif cmd == "transfer" and len(sys.argv) == 3:
            transfer(c, sys.argv[2], "FUNDING", "CONTRACT")
        elif cmd == "transfer-back" and len(sys.argv) == 3:
            transfer(c, sys.argv[2], "CONTRACT", "FUNDING")
        else:
            sys.exit(__doc__)
    except PluginError as e:
        sys.exit(f"失敗：{e}")


if __name__ == "__main__":
    main()
