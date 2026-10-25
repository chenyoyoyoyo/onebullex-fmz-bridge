# 01 概覽：架構、準備事項與限制

## 架構

```
FMZ 平台（網頁）
   │ 下發策略、顯示日誌
   ▼
FMZ 託管者（fmz-robot 服務）      ← 策略實際在這裡執行
   │ 通用協議 POST http://127.0.0.1:6666/OneBullEx
   ▼
bridge 轉接程式（onebullex-fmz 服務）← 翻譯請求、執行安全限制、簽名
   │ HTTPS
   ▼
OneBullEx Open API V2（斯巴達機器人帳戶）
```

- 託管者和 bridge 必須在**同一台機器**，因為 bridge 只監聽本機 `127.0.0.1`。
- 因此不能使用 FMZ 平台「一鍵租用」的主機（無法在上面安裝 bridge），也不建議用家用電腦（關機就停、IP 會變動）。最合適的是自己租一台雲端 Linux 主機。
- 伺服器只需要開放 SSH，不需要開放其他連接埠：託管者是主動連出到 FMZ，bridge 只接受本機連線。

## 使用者需要準備

| 項目 | 說明 |
| --- | --- |
| FMZ 帳號 | fmz.com 國際站（fmz.cn 已轉為國內期貨股票平台，與本案無關） |
| OneBullEx 斯巴達機器人 API key | 由 OneBullEx 核發，**先拿測試網的**。正式環境的 key 在測試完成後再申請 |
| 機器人帳戶有資金 | 測試網由 OneBullEx 提供測試資金；資金需從資金帳戶轉到合約帳戶才能下單 |
| 一台 Linux 伺服器 | Ubuntu 22.04 或 24.04，64 位元（amd64 或 arm64），最低規格即可 |
| 雲端主控台與 SSH | 能登入雲端主控台、能用 SSH 連到伺服器 |

## 已知限制（請先確認策略適用）

1. **只支援永續合約**：策略不呼叫 `SetContractType`；交易對寫成 `BTC_USDT` 形式。斯巴達專屬交易對寫成 `BTCSPARTANS_USDT`、`ETHSPARTANS_USDT`、`XAUSPARTANS_USDT`，見 `04-strategy-guide.md`。
2. **三種持倉模式**：預設為淨部位模式（`Buy`／`Sell` 有反向持倉就平倉，沒有就開倉），適合單一方向策略。同時持有多空的對沖策略用雙向模式；同方向多筆獨立持倉用分倉模式。後兩者以 `exchange.IO` 設定下單方向，見 `04-strategy-guide.md` 的「三種持倉模式」。
3. **數量以「張」為單位且必須是整數**：例如 BTC 每張 0.0001 BTC，最少 1 張。策略需把幣數換算成張數。
4. **下單是非同步的**：`Buy`/`Sell` 回傳訂單 ID 不代表已成交，需用 `GetOrder` 確認，剛下的單約 1 秒後查得到。
5. **bridge 不限制交易對、張數與槓桿**：下單數量與槓桿由使用者的策略決定，交易所端的規則（合約規格、各槓桿級距的持倉上限、API 限頻）以 OneBullEx 為準。bridge 只預設每秒最多 5 筆，防止策略迴圈失控連續送單。想替自己加防呆（例如單筆最多幾張），見 `09-quantity-and-risk.md`。
6. **策略要用現貨寫法**：新版 FMZ 託管者的通用協議不轉送 `SetContractType`、`SetDirection`、`SetMarginLevel`、`GetPositions`。bridge 預設以淨部位模式處理 `Buy`／`Sell`，雙向與分倉策略以 `exchange.IO` 設定方向；持倉與槓桿也改用 `exchange.IO`。現有的合約寫法策略需要修改，見 `04-strategy-guide.md`。
7. **exchange.IO 直通只開放查詢、調整槓桿與設定下單方向**，下單一律走 `Buy`／`Sell`。

## 斯巴達帳戶的資金流

- 認購的資金先進**資金帳戶（Funding）**，不能交易。
- 需轉到**合約帳戶（Futures）**才能當保證金下單：`python3 obx_tool.py transfer <金額>`。
- 贖回從資金帳戶支付，所以**資金帳戶要保留餘額**，不要全部轉走。
- 詳細規則見 https://github.com/Onebullex-dev/spartan-strategy-partner-skill

Pine策略先讀 [08](08-pine-compatibility.md)；張數、權益比例與止損風險換算見 [09](09-quantity-and-risk.md)。
