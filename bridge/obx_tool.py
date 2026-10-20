#!/usr/bin/env python3
"""
OneBullEx 帳戶小工具（讀取環境變數 OBX_API_KEY / OBX_SECRET，預設測試網）

    python3 obx_tool.py balance            查合約帳戶、資金帳戶、持倉
    python3 obx_tool.py transfer 1000      資金帳戶 -> 合約帳戶
    python3 obx_tool.py transfer-back 500  合約帳戶 -> 資金帳戶

連正式環境請先 export OBX_ENV=prod
"""
import os
import sys
import uuid

from onebullex_fmz_plugin import BASE_URLS, OneBullExClient, PluginError


def client():
    key, secret = os.environ.get("OBX_API_KEY"), os.environ.get("OBX_SECRET")
    if not key or not secret:
        sys.exit("請先設定 OBX_API_KEY 和 OBX_SECRET")
    return OneBullExClient(BASE_URLS[os.environ.get("OBX_ENV", "test")], key, secret)


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
    cmd, c = sys.argv[1], client()
    try:
        if cmd == "balance":
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
