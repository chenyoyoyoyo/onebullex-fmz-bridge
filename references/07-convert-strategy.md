# 07 把合約寫法的 FMZ 策略轉成 OneBullEx 可用的寫法

給 AI 助手的轉換流程。新版 FMZ 託管者的通用協議只轉送現貨功能（見 `04-strategy-guide.md`），所以使用合約函數的策略必須轉換才能接 OneBullEx。

## 0. 取得策略程式碼（擇一）

| 方式 | 說明 |
| --- | --- |
| **FMZ 官方 AI 接入（建議）** | 依 https://www.fmz.com/agent/setup.md 接上 FMZ 的 MCP。使用者在瀏覽器按一次同意。權限只勾 `read` 和 `write`（讀取、儲存策略），**不要勾 `trade`、`danger`**。授權取得的 secret 不可寫進對話、日誌或程式碼庫 |
| 瀏覽器 | 若你能操作使用者的瀏覽器，打開 FMZ 策略編輯頁讀取程式碼。登入由使用者自己完成 |
| 貼上 | 請使用者從 FMZ 策略編輯器複製整段程式碼貼給你 |

不要索取使用者的 FMZ 密碼。

## 1. 掃描：列出所有需要處理的地方

逐一搜尋下列寫法，整理成表格（行號、原寫法、問題、改法）給使用者看：

| 搜尋 | 問題 | 處理 |
| --- | --- | --- |
| `SetContractType(` | 託管者報錯 | 刪除 |
| `SetMarginLevel(` | 託管者報錯 | 改用 `exchange.IO("api", "POST", "/v2/position/adjust-leverage", "symbol=...&leverage=N")`，不可超過 bridge 上限 |
| `SetDirection(` | 被靜默忽略，方向會錯 | 刪除，改用淨部位邏輯（見第 2 步） |
| `GetPosition(` / `GetPositions(` | 託管者報錯 | 改用 `netPosition()` |
| `PD_LONG` / `PD_SHORT` / `.Type` / `.Amount`（持倉物件） | 持倉資料來源改變 | 改用淨部位的正負號 |
| `CreateOrder(` | 新版 API 的下單寫法，未在通用協議下驗證 | 改為 `Buy` / `Sell` |
| `exchange.IO("cross"` / `"dual"` / 其他非 `"api"` 的 IO | 交易所專屬設定，通用協議不支援 | 刪除，並告知使用者 |
| `GetTickers(` / `GetMarkets(` / `GetFundings(` | 通用協議未支援 | 改用 `exchange.IO("api", "GET", ...)` 查 OneBullEx 公開端點，或移除 |
| `exchanges[1]` 等多交易所 | bridge 只接 OneBullEx 一個交易所物件 | 確認用途；跨交易所套利不適用 |
| 交易對帶 `.swap`（例如 `"BTC_USDT.swap"`） | 通用協議用 `BTC_USDT` | 去掉 `.swap` |
| 連續兩張單之間沒有等成交（例如先平倉再立刻開倉） | OneBullEx 非同步下單，第二張可能被判定為反手而擋下 | 改用 `moveTo(target)` |

## 2. 轉換：改成「目標淨部位」

1. 在策略最上方加入共用函數（`04-strategy-guide.md` 的 `netPosition`、`waitOrder`、`moveTo`）。交易對用 `exchange.GetCurrency().toLowerCase()` 取得，不要寫死。
2. 把原本的開平倉邏輯改寫成「這一刻要持有多少淨部位」：多 N 張 = `N`、空 N 張 = `-N`、空手 = `0`，再呼叫 `moveTo(target)`。
   - 原本：有空單就 `closesell` 平空，沒多單就 `buy` 開多 QTY → 改成 `moveTo(QTY)`
   - 原本：有多單就 `closebuy` 平多，沒空單就 `sell` 開空 QTY → 改成 `moveTo(-QTY)`
   - 原本：平掉所有持倉 → 改成 `moveTo(0)`
3. 原本的訊號計算、參數、日誌、`LogStatus` 保持不變，只改下單與持倉的部分。

## 3. 必須問使用者的情況（不要自己決定）

- **對沖邏輯**：策略同時持有多單和空單（例如雙向網格、鎖倉）。OneBullEx 帳戶為單向持倉，無法照原意運作。說明限制，請使用者決定改成單一淨部位或放棄。
- **數量單位**：原策略的數量若是依其他交易所的合約面值或幣數設定，在 OneBullEx 會差很多倍（OneBullEx BTC 每張 0.0001 BTC，以 `/v2/public/symbol/detail` 的 `contractSize` 為準）。列出換算結果，請使用者確認。
- **交易對**：bridge 預設只允許 BTC、ETH 合約。策略若交易其他幣種，需先取得 OneBullEx 同意。
- 任何你不確定原意的程式邏輯。

## 4. 儲存：另存新策略，不覆蓋原策略

- 先把第 1 步的表格與轉換後的完整程式碼給使用者看，**取得同意後**才儲存。
- 存成新策略，名稱加上後綴，例如 `原名-OneBullEx版`。原策略保持不變。
- 儲存後重新讀取一次，確認內容完整，且不再含有 `SetContractType(`、`SetDirection(`、`SetMarginLevel(`、`GetPositions(`（註解除外）。

## 5. 驗證：在測試網跑核心函數

在 FMZ 調試工具（託管者選裝了 bridge 的機器、交易所選測試網設定）執行下列腳本，把轉換後的共用函數貼在 `main` 之前。**這會在測試網實際下單，必須由使用者確認或親手按執行。**

```javascript
function main() {
    Log("設定槓桿", exchange.IO("api", "POST", "/v2/position/adjust-leverage", "symbol=" + exchange.GetCurrency().toLowerCase() + "&leverage=5"))
    Log("開始淨部位", netPosition())
    moveTo(1);  Sleep(1500); Log("目標 +1 → ", netPosition())
    moveTo(-1); Sleep(1500); Log("目標 -1（反手）→ ", netPosition())
    moveTo(0);  Sleep(1500); Log("目標 0（平倉）→ ", netPosition())
}
```

預期淨部位依序為 `0 → 1 → -1 → 0`。全部正確後，才建議使用者以轉換後的策略在**測試網**建立實盤觀察一段時間。不要替使用者啟動正式環境的實盤。

## 6. 回報

最後給使用者一份簡短摘要：

- 改了哪些地方（第 1 步的表格）
- 行為上的差異（單向持倉、不自動反手、數量單位）
- 驗證結果
- 尚未驗證的部分（例如未在測試網跑過的 K 線週期）

## 範例

轉換前（合約寫法，節錄）：

```javascript
exchange.SetContractType("swap")
exchange.SetMarginLevel(5)
var pos = exchange.GetPositions() || []
// ...計算 longAmt、shortAmt...
if (up) {
    if (shortAmt > 0) { exchange.SetDirection("closesell"); exchange.Buy(-1, shortAmt) }
    if (longAmt == 0) { exchange.SetDirection("buy"); exchange.Buy(-1, QTY) }
} else {
    if (longAmt > 0) { exchange.SetDirection("closebuy"); exchange.Sell(-1, longAmt) }
    if (shortAmt == 0) { exchange.SetDirection("sell"); exchange.Sell(-1, QTY) }
}
```

轉換後（加上共用函數後）：

```javascript
exchange.IO("api", "POST", "/v2/position/adjust-leverage", "symbol=" + obSymbol() + "&leverage=" + LEVERAGE)
// ...訊號計算不變...
moveTo(up ? QTY : -QTY)
var net = netPosition()
LogStatus("多 " + Math.max(net, 0) + " 張，空 " + Math.max(-net, 0) + " 張")
```

此範例已在 OneBullEx 測試網經 FMZ 實測，淨部位依序為 0 → 1 → -1 → 0。
