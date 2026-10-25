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
| 交易對 | `BTC_USDT`，不加`.swap`；IO查詢用`btc_usdt` |
| 行情 | `GetTicker()`、`GetDepth()`、`GetTrades()` |
| K線 | `GetRecords(60)` 為1分鐘（FMZ參數單位秒）；也驗證過1小時。bridge協議內部period單位是分鐘，不可混用 |
| 帳戶 | `GetAccount().Balance` 是合約可用USDT；完整權益另外核對 |
| 下單 | `Buy/Sell` 回傳ID不代表成交，false/例外不代表交易所一定沒收到 |
| 查單 | `GetOrder(id)`：Status 0未成交、1已成交、2已撤單；另核對Amount、DealAmount、AvgPrice |
| 掛單 | `GetOrders()`；null/例外不是空陣列 |
| 撤單 | `CancelOrder(id)` 後再次查單、持倉；撤單與成交可能競爭 |
| 持倉 | `exchange.IO("api","GET","/v2/position/list","symbol=btc_usdt")` |
| 合約規格 | `exchange.IO("api","GET","/v2/public/symbol/detail","symbol=btc_usdt")` |
| 槓桿 | `exchange.IO("api","POST","/v2/position/adjust-leverage","symbol=btc_usdt&leverage=N")`，事前確認核准值 |

通用現貨介面的 `Type` 買/賣或 `Offset` 欄位不能單獨證明開/平倉。本次平多的GetOrder回應Offset仍為0；判斷依據是送單前淨部位、實際成交及送單後淨部位。`Sell` 可能是平多，不一定開空。

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
    }, {liveEnabled: false, maxOrderContracts: 1});
    Log("合約規格", execution.spec());
    Log("淨持倉", execution.position().net);
    Log("未送出的目標+1計畫", execution.plan(1));
}
```

實際轉換時由策略呼叫 `execution.moveTo(target)`：多N張為+N、空N張為-N、空手為0。改為送單模式前必須核對環境、帳戶、核准上限並取得使用者確認，正式啟動由本人操作。

模組在送單前保存意圖；確認全部成交、有效成交均價、交易所淨倉同步且無掛單才繼續。送單結果不明、部分成交、成交查不到或持倉不同步時停止，保留journal供人工對帳；**不自動重送**。不明journal不可直接刪除後重啟。

完整策略還須管理自己的訊號、預期持倉、均價、風險、跨K線及重啟狀態。例：`runtime.js` 在執行模組外另保存策略意圖，避免「成交後程序中斷」造成重複開倉。不要把這個執行模組當作完整策略或風險管理器。

## 轉換對照

| 合約寫法 | 通用協議替代 |
| --- | --- |
| `SetContractType("swap")` | 移除；帳戶/合約在部署時核對 |
| `SetDirection(...)` | 移除；以淨部位決定開平倉 |
| `SetMarginLevel(n)` | 經同意用IO調整，或沿用已確認的帳戶槓桿 |
| `GetPositions()` | IO持倉查詢或execution.position() |
| 幣數直接Buy/Sell | 依合約面值換成整數張，見09 |
| 同時多空 | 本工具包單向淨部位範例不適用，先釐清策略意圖 |

只有讀取可做有限次重試；永遠不要把 `_C` 或泛用重試器包在 Buy/Sell 外。查詢失敗不得當成空倉。合約核准範圍不變時，不必為排查訊號問題調高bridge上限。

完整範例見 [一分鐘策略](../examples/alligator-fractal/README.md)；Pine問題見 [08](08-pine-compatibility.md)，數量換算見 [09](09-quantity-and-risk.md)。
