# 04 策略介面與成交確認

## 以現貨函數介面操作合約淨部位

在已測試的 FMZ 託管者 v3.9.2 通用協議路徑，`SetContractType`、`SetMarginLevel`、`GetPositions/GetPosition` 不支援，`SetDirection` 可能被忽略。這裡的「現貨寫法」只指函數介面，**實際交易仍是永續合約**。

| 呼叫 | 目前持倉 | 實際作用 |
| --- | --- | --- |
| `Buy(price, amount)` | 沒有空倉 | 開多 |
| `Buy(price, amount)` | 有空倉 | 平空，數量不能超過空倉 |
| `Sell(price, amount)` | 沒有多倉 | 開空 |
| `Sell(price, amount)` | 有多倉 | 平多，數量不能超過多倉 |

amount 是**整數張**；price=-1 表示市價。持有3張多倉時，不能直接Sell 5張來反手。先平3張、確認成交與空倉，再另開2張空倉。

## 已驗證介面

| 用途 | 寫法與注意 |
| --- | --- |
| 交易對 | `BTC_USDT`、`BTCSPARTANS_USDT` 等，不加`.swap`；IO查詢可寫`btc_usdt`或FMZ寫法，bridge會自動對應 |
| 行情 | `GetTicker()`、`GetDepth()`、`GetTrades()` |
| K線 | `GetRecords(60)` 為1分鐘（FMZ參數單位秒）；也驗證過1小時。bridge協議內部period單位是分鐘，不可混用 |
| 帳戶 | `GetAccount().Balance` 是合約可用USDT；完整權益另外核對 |
| 下單 | `Buy/Sell` 回傳ID不代表成交，false/例外不代表交易所一定沒收到 |
| 查單 | `GetOrder(id)`：Status 0未成交、1已成交、2已撤單；另核對Amount、DealAmount、AvgPrice |
| 掛單 | `GetOrders()`；null/例外不是空陣列 |
| 撤單 | `CancelOrder(id)` 後再次查單、持倉；撤單與成交可能競爭 |
| 持倉 | `exchange.IO("api","GET","/v2/position/list","symbol=btc_usdt")` |
| 合約規格 | `exchange.IO("api","GET","/v2/public/symbol/detail","symbol=btc_usdt")`；每個交易對的 `contractSize` 不同，不要套用BTC_USDT的值 |
| 槓桿 | `exchange.IO("api","POST","/v2/position/adjust-leverage","symbol=btc_usdt&leverage=N")`，見下方「槓桿」 |

通用現貨介面的 `Type` 買/賣或 `Offset` 欄位不能單獨證明開/平倉。本次平多的GetOrder回應Offset仍為0；判斷依據是送單前淨部位、實際成交及送單後淨部位。`Sell` 可能是平多，不一定開空。

## 斯巴達專屬交易對

OneBullEx 為斯巴達提供三個專屬交易對，風險限額遠高於一般交易對，適合資金池規模大的機器人。斯巴達的 BTC、ETH、黃金策略建議交易這三個：

| 資產 | FMZ 交易對寫法 | 1 張 | 價格跳動 |
| --- | --- | --- | --- |
| BTC | `BTCSPARTANS_USDT` | 0.0001 BTC | 0.1 |
| ETH | `ETHSPARTANS_USDT` | 0.01 ETH | 0.01 |
| 黃金 | `XAUSPARTANS_USDT` | 0.001 | 0.01 |

（2026-10 正式環境查詢結果，最小都是 1 張；部署時仍以 `obx_tool.py spec` 為準。）

**FMZ 的交易對下拉選單裡沒有這三個選項，要自己打字：**

1. 在實盤或調試工具的交易對欄位點一下（預設顯示 `BTC_USDT`）。
2. 直接輸入 `BTCSPARTANS_USDT`。
3. 下方出現同名選項，點它即可。

也可以在策略開頭寫 `exchange.SetCurrency("BTCSPARTANS_USDT")`，效果相同。
- bridge 啟動後會讀取交易所的交易對清單，自動把 FMZ 寫法對應到交易所的名稱。
- **每張的面值（contractSize）、最小張數、價格跳動可能和 BTC_USDT 不同**。上線前在伺服器執行 `python3 obx_tool.py spec BTCSPARTANS_USDT`，用實際的面值換算張數（見 `09-quantity-and-risk.md`）。
- 想確認目前環境有哪些交易對：`python3 obx_tool.py symbols`（不需要金鑰）。
- 範例的 [execution.js](../examples/alligator-fractal/execution.js) 與 [runtime.js](../examples/alligator-fractal/runtime.js) 會依實盤所選的交易對讀取規格，BTC_USDT 與專屬交易對都能用。

## 槓桿

FMZ 的 `SetMarginLevel` 不會被託管者轉送，槓桿用以下任一方式設定（優先順序由上而下）：

| 方式 | 做法 | 適合 |
| --- | --- | --- |
| 策略內設定 | `exchange.IO("api","POST","/v2/position/adjust-leverage","symbol=BTCSPARTANS_USDT&leverage=5")`，回傳 `5` 代表成功；可做成 FMZ 策略參數（範例的 `AF_LEVERAGE`） | 想在 FMZ 介面調整 |
| 主機預設 | `/etc/onebullex-fmz.env` 的 `OBX_DEFAULT_LEV=5`，每個合約第一次開倉前自動套用 | 所有策略用同一個槓桿 |
| 帳戶設定 | 都不設時，沿用帳戶該合約目前的槓桿；也可用 `python3 obx_tool.py leverage BTCSPARTANS_USDT 5` 設定 | 不想改策略 |

有持倉時是否能改槓桿、各合約允許的最高槓桿與各級距的持倉上限，以 OneBullEx 為準。槓桿只影響需要的保證金；同樣張數下，價格變動的盈虧不因槓桿改變。

## 可重用執行模組

使用 [execution.js](../examples/alligator-fractal/execution.js) 的 `createSpartansExecution`，而不是用Sleep後手動對本地持倉加減。此模組預設不送單，適用已驗證BTC整數張路徑：

```javascript
// 把 execution.js 完整貼在 main 前。此範例只列計畫，不會下單。
function main() {
    var execution = createSpartansExecution({
        exchange: exchange,
        now: function () { return Date.now(); }, sleep: Sleep,
        load: function () { return _G("example-order-journal"); },
        save: function (j) { _G("example-order-journal", j); },
        log: function () { Log.apply(null, arguments); }
    }, {liveEnabled: false, maxOrderContracts: 0});   // 0 = 不限；交易對依 exchange.GetCurrency()
    Log("合約規格", execution.spec());
    Log("淨持倉", execution.position().net);
    Log("未送出的目標+1計畫", execution.plan(1));
}
```

實際轉換時由策略呼叫 `execution.moveTo(target)`：多N張為+N、空N張為-N、空手為0。改為送單模式前必須核對環境、帳戶、交易對與張數並取得使用者確認，正式啟動由本人操作。`maxOrderContracts` 是使用者自選的單筆防呆，0 表示不限。

模組在送單前保存意圖；確認全部成交、有效成交均價、交易所淨倉同步且無掛單才繼續。送單結果不明、部分成交、成交查不到或持倉不同步時停止，保留journal供人工對帳；**不自動重送**。不明journal不可直接刪除後重啟。

完整策略還須管理自己的訊號、預期持倉、均價、風險、跨K線及重啟狀態。例：`runtime.js` 在執行模組外另保存策略意圖，避免「成交後程序中斷」造成重複開倉。不要把這個執行模組當作完整策略或風險管理器。

## 轉換對照

| 合約寫法 | 通用協議替代 |
| --- | --- |
| `SetContractType("swap")` | 移除；帳戶/合約在部署時核對 |
| `SetDirection(...)` | 移除；以淨部位決定開平倉 |
| `SetMarginLevel(n)` | 用IO調整（見上方「槓桿」），或沿用帳戶槓桿 |
| `GetPositions()` | IO持倉查詢或execution.position() |
| 幣數直接Buy/Sell | 依合約面值換成整數張，見09 |
| 同時多空 | 本工具包單向淨部位範例不適用，先釐清策略意圖 |

只有讀取可做有限次重試；永遠不要把 `_C` 或泛用重試器包在 Buy/Sell 外。查詢失敗不得當成空倉。

完整範例見 [一分鐘策略](../examples/alligator-fractal/README.md)；Pine問題見 [08](08-pine-compatibility.md)，數量換算見 [09](09-quantity-and-risk.md)。
