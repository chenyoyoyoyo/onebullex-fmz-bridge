# 07 把合約寫法的 FMZ 策略轉成 OneBullEx 可用的寫法

給 AI 助手的轉換流程。新版 FMZ 託管者的通用協議只轉送現貨功能（見 `04-strategy-guide.md`），所以使用合約函數的策略必須轉換才能接 OneBullEx。

## 先辨識語言與執行層

本節表格主要處理FMZ JavaScript合約寫法。若來源是Pine，先讀 [08](08-pine-compatibility.md)，完整移植訊號、狀態與下單；不能僅刪SetDirection或更改精度。所有策略的數量先讀 [09](09-quantity-and-risk.md)。

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
| `SetMarginLevel(` | 託管者報錯 | 改用 `exchange.IO("api", "POST", "/v2/position/adjust-leverage", "symbol=...&leverage=N")`，見 `04-strategy-guide.md`「槓桿」 |
| `SetDirection(` | 被靜默忽略，方向會錯 | 單一方向策略：刪除，改用淨部位邏輯（見第 2 步）。同時多空或分倉策略：改成 `setDirection(`（見 `04-strategy-guide.md` 的「三種持倉模式」），其餘開平倉邏輯保留 |
| `GetPosition(` / `GetPositions(` | 託管者報錯 | 改用 `netPosition()` |
| `PD_LONG` / `PD_SHORT` / `.Type` / `.Amount`（持倉物件） | 持倉資料來源改變 | 單一方向策略改用淨部位的正負號；雙向、分倉策略改讀 `/v2/position/list` 的 `positionSide`、`positionSize`、`positionId` |
| `CreateOrder(` | 新版 API 的下單寫法，未在通用協議下驗證 | 改為 `Buy` / `Sell` |
| `exchange.IO("cross"` / `"dual"` / 其他非 `"api"` 的 IO | 交易所專屬設定，通用協議不支援 | 刪除，並告知使用者 |
| `GetTickers(` / `GetMarkets(` / `GetFundings(` | 通用協議未支援 | 改用 `exchange.IO("api", "GET", ...)` 查 OneBullEx 公開端點，或移除 |
| `exchanges[1]` 等多交易所 | bridge 只接 OneBullEx 一個交易所物件 | 確認用途；跨交易所套利不適用 |
| 交易對帶 `.swap`（例如 `"BTC_USDT.swap"`） | 通用協議用 `BTC_USDT` | 去掉 `.swap` |
| 連續兩張單之間沒有等成交（例如先平倉再立刻開倉） | OneBullEx 非同步下單，第二張可能被判定為反手而擋下 | 改用 `moveTo(target)` |

## 2. 轉換：改成「目標淨部位」

1. 在策略最上方加入04連結的 `execution.js`，用 `createSpartansExecution` 建立執行器並保存訂單journal；策略另存訊號意圖。交易對用 `exchange.GetCurrency().toLowerCase()` 取得，不要寫死。
2. 把原本的開平倉邏輯改寫成「這一刻要持有多少淨部位」：多 N 張 = `N`、空 N 張 = `-N`、空手 = `0`，再呼叫 `execution.moveTo(target)`。
   - 原本：有空單就 `closesell` 平空，沒多單就 `buy` 開多 QTY → 改成 `moveTo(QTY)`
   - 原本：有多單就 `closebuy` 平多，沒空單就 `sell` 開空 QTY → 改成 `moveTo(-QTY)`
   - 原本：平掉所有持倉 → 改成 `moveTo(0)`
3. 原本的訊號計算、參數、日誌、`LogStatus` 保持不變，只改下單與持倉的部分。

## 3. 必須問使用者的情況（不要自己決定）

- **持倉模式**：策略同時持有多單和空單（雙向網格、鎖倉）用雙向模式；同方向分批進場且每筆各自出場用分倉模式。這兩種都保留原本的開平倉邏輯，只把 `exchange.SetDirection(d)` 換成 `setDirection(d)`，不要改寫成淨部位。轉換前先向使用者確認策略屬於哪一種。
- **數量單位**：原策略的數量若是依其他交易所的合約面值或幣數設定，在 OneBullEx 會差很多倍（OneBullEx BTC 每張 0.0001 BTC，以 `/v2/public/symbol/detail` 的 `contractSize` 為準）。列出換算結果，請使用者確認。
- **交易對**：斯巴達的 BTC、ETH、黃金策略建議改用專屬交易對 `BTCSPARTANS_USDT`、`ETHSPARTANS_USDT`、`XAUSPARTANS_USDT`（風險限額較高）。改交易對時面值可能不同，張數要用 `obx_tool.py spec` 查到的面值重新換算，請使用者確認。
- 任何你不確定原意的程式邏輯。

## 4. 儲存：另存新策略，不覆蓋原策略

- 先把第 1 步的表格與轉換後的完整程式碼給使用者看，**取得同意後**才儲存。
- 存成新策略，名稱加上後綴，例如 `原名-OneBullEx版`。原策略保持不變。
- 儲存後重新讀取一次，確認內容完整，且不再含有 `SetContractType(`、`exchange.SetDirection(`、`SetMarginLevel(`、`GetPositions(`（註解除外）。

## 5. 驗證與回報

以 [完整範例](../examples/alligator-fractal/README.md) 與 [交接指南](../docs/HANDOVER.md) 的分階段流程驗收。先離線與PAPER，再經同意於測試網驗證目標部位0→+1→0、0→-1→0，反手則每一腿都要確認成交/淨倉歸零；未驗證的方向如實列出，不挪用其他案例的成功。

每個真實測試先說明環境、帳戶與張數並取得同意；正式實盤由使用者親自啟動。回報改動、參數差異、數量算法、驗證證據及未驗證範圍。PAPER或回測成功不能代替交易所成交驗收。
