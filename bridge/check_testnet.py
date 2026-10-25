#!/usr/bin/env python3
"""
拿到測試環境 API key 後的連線檢查（只讀取，不下單）。

用法（Mac / Linux）：
    export OBX_API_KEY=你的AccessKey
    export OBX_SECRET=你的SecretKey
    python3 check_testnet.py

會依序檢查：伺服器時間差、公開行情、合約規格、簽名驗證（查餘額）、持倉查詢。
預設檢查 BTC_USDT；要檢查其他交易對（例如斯巴達專屬交易對）：
    OBX_SYMBOL=BTCSPARTANS_USDT python3 check_testnet.py
"""
import os
import sys
import time

from onebullex_fmz_plugin import BASE_URLS, KNOWN_SYMBOLS, OneBullExClient, PluginError, to_ob_symbol


def step(name, fn):
    try:
        result = fn()
        print(f"OK   {name}：{result}")
        return True
    except PluginError as e:
        print(f"FAIL {name}：{e}")
        return False


def main():
    env = os.environ.get("OBX_ENV", "test")
    key, secret = os.environ.get("OBX_API_KEY", ""), os.environ.get("OBX_SECRET", "")
    c = OneBullExClient(BASE_URLS[env], key, secret)
    print(f"檢查環境：{BASE_URLS[env]}\n")
    try:
        KNOWN_SYMBOLS.update(str(r).lower() for r in (c.request("GET", "/v2/public/symbol/all") or []))
    except PluginError:
        pass
    sym = to_ob_symbol(os.environ.get("OBX_SYMBOL", "BTC_USDT"))

    ok = step("伺服器時間差", lambda: f"{abs(int(c.request('GET', '/v2/public/time')) / 1000 - time.time()):.1f} 秒（需小於 30 秒）")
    ok &= step(f"{sym} 報價", lambda: {k: v for k, v in c.request(
        "GET", "/v2/public/q/agg-ticker", {"symbol": sym, "timeRangeType": "H24"}).items() if k in ("c", "bp", "ap")})
    ok &= step(f"{sym} 合約規格", lambda: {k: v for k, v in c.request(
        "GET", "/v2/public/symbol/detail", {"symbol": sym}).items()
        if k in ("contractSize", "minQty", "pricePrecision", "minStepPrice", "supportPositionType")})
    if not key or not secret:
        print("\n未設定 OBX_API_KEY / OBX_SECRET，略過私有端點檢查")
        sys.exit(0 if ok else 1)
    ok &= step("簽名驗證（查餘額）", lambda: [(b.get("coin"), b.get("availableBalance")) for b in
                                         c.request("GET", "/v2/balance/list", private=True)])
    ok &= step("持倉模式", lambda: c.request("GET", "/v2/position/confs", {"symbol": sym}, private=True))
    print("\n全部通過，可以啟動轉接程式並到 FMZ 設定交易所" if ok else "\n有項目失敗，請對照 references/06-troubleshooting.md")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
