# 04 策略撰寫與調整

## 重要：用「現貨寫法」寫策略

新版 FMZ 託管者（v3.9 起）的通用協議只轉送現貨功能，合約專屬函數在託管者那一層就被擋下，不會送到 bridge：

| FMZ 函數 | 在通用協議下的實際行為 |
| --- | --- |
| `SetContractType` | 報錯 `not supported by Exchange` |
| `SetDirection` | 靜默忽略（回傳 undefined） |
| `SetMarginLevel` | 報錯 `setLeverage: unsupported` |
| `GetPositions` / `GetPosition` | 報錯 `unsupported rest method: positions` |

因此 bridge 採用**淨部位模式**，策略只需要用 `Buy` / `Sell`：

| 下單 | 目前持倉 | bridge 實際送出 |
| --- | --- | --- |
| `Buy` | 沒有空單 | 開多 |
| `Buy` | 有空單 | 平空（數量不可超過空單數量） |
| `Sell` | 沒有多單 | 開空 |
| `Sell` | 有多單 | 平多（數量不可超過多單數量） |

**不會自動反手**：持有多單 3 張時下 `Sell(-1, 5)` 會被擋下。要反手時，先平掉原部位，確認持倉為空，再開新方向。

以上行為已在 FMZ 實測：市價開多 1 張後持倉為 LONG 1 張，市價賣 1 張後自動平多，持倉清空。

## 支援的函數（已在 FMZ 實測）

| 用途 | 寫法 |
| --- | --- |
| 設定交易對 | `exchange.SetCurrency("BTC_USDT")` |
| 行情 | `exchange.GetTicker()`、`GetDepth()`、`GetTrades()`、`GetRecords(PERIOD_H1)` |
| 帳戶 | `exchange.GetAccount()`：`Balance` 為合約帳戶可用 USDT |
| 下單 | `exchange.Buy(price, amount)` / `exchange.Sell(price, amount)`；`price = -1` 為市價，其他為限價（GTC）；`amount` 為**整數張** |
| 查單 | `exchange.GetOrder(id)`：`Status` 0 = 未成交，1 = 已成交，2 = 已撤單；`Offset` 0 = 開倉，1 = 平倉 |
| 未成交訂單 | `exchange.GetOrders()` |
| 撤單 | `exchange.CancelOrder(id)` |
| 查持倉 | `exchange.IO("api", "GET", "/v2/position/list", "symbol=btc_usdt")` |
| 調整槓桿 | `exchange.IO("api", "POST", "/v2/position/adjust-leverage", "symbol=btc_usdt&leverage=5")`（不可超過上限） |

K 線已驗證 1 小時週期，其他週期請先在測試網確認。

**槓桿**：開倉單會自動帶上帳戶目前對該合約設定的槓桿。也可以用上面的 `exchange.IO` 調整，或請伺服器管理者設定 `/etc/onebullex-fmz.env` 的 `OBX_DEFAULT_LEV`。

## 共用函數（直接複製到策略裡）

```javascript
var SYMBOL = "BTC_USDT"                 // FMZ 交易對
var OB_SYMBOL = "btc_usdt"              // OneBullEx 交易對
var CONTRACT_SIZE = 0.0001              // 每張 0.0001 BTC，以 /v2/public/symbol/detail 的 contractSize 為準

// 淨部位（張）：多為正、空為負、無持倉為 0
function netPosition() {
    var r = exchange.IO("api", "GET", "/v2/position/list", "symbol=" + OB_SYMBOL)
    var rows = (r && r.data) || []
    var net = 0
    rows.forEach(function (p) {
        var size = Number(p.positionSize)
        net += (p.positionSide == "LONG" ? size : -size)
    })
    return net
}

// 把 USDT 金額換算成整數張（無條件捨去）
function toContracts(usdt, price) {
    return Math.floor(usdt / price / CONTRACT_SIZE)
}

// 等待訂單成交或撤銷（下單為非同步，剛下的單稍等再查）
function waitOrder(id, timeoutMs) {
    var t0 = Date.now()
    while (Date.now() - t0 < timeoutMs) {
        var o = exchange.GetOrder(id)
        if (o && (o.Status == ORDER_STATE_CLOSED || o.Status == ORDER_STATE_CANCELED)) return o
        Sleep(500)
    }
    return exchange.GetOrder(id)
}

// 調整到目標淨部位（例如 10 = 多 10 張，-5 = 空 5 張，0 = 平倉）；需要反手時先平倉再開倉
function moveTo(target) {
    var net = netPosition()
    if (net == target) return
    if (net > 0 && target < net) {                       // 先減多
        var n = Math.min(net, net - target)
        waitOrder(exchange.Sell(-1, n), 10000)
        net -= n
    } else if (net < 0 && target > net) {                // 先減空
        var m = Math.min(-net, target - net)
        waitOrder(exchange.Buy(-1, m), 10000)
        net += m
    }
    if (target > net && net >= 0) waitOrder(exchange.Buy(-1, target - net), 10000)    // 加多或從空手開多
    if (target < net && net <= 0) waitOrder(exchange.Sell(-1, net - target), 10000)   // 加空或從空手開空
}
```

## 範例：均線趨勢策略（示範用）

```javascript
// 參數：QTY = 10（張）
function main() {
    exchange.SetCurrency(SYMBOL)
    while (true) {
        var r = exchange.GetRecords(PERIOD_H1)
        if (r && r.length > 30) {
            var fast = TA.MA(r, 7), slow = TA.MA(r, 25)
            var up = fast[fast.length - 1] > slow[slow.length - 1]
            moveTo(up ? QTY : 0)                         // 多頭持有多單，否則空手
            LogStatus("淨部位：" + netPosition() + " 張")
        }
        Sleep(60 * 1000)
    }
}
```

## 從合約寫法改過來

| 原本的合約寫法 | 改成 |
| --- | --- |
| `SetContractType("swap")` | 刪除 |
| `SetMarginLevel(n)` | 刪除，或改用 `exchange.IO` 調整槓桿 |
| `SetDirection("buy"); Buy(p, n)` | `Buy(p, n)`（無空單時為開多） |
| `SetDirection("sell"); Sell(p, n)` | `Sell(p, n)`（無多單時為開空） |
| `SetDirection("closebuy"); Sell(p, n)` | `Sell(p, n)`（有多單時為平多） |
| `SetDirection("closesell"); Buy(p, n)` | `Buy(p, n)`（有空單時為平空） |
| `GetPositions()` | `netPosition()`，或直接用 `exchange.IO` 查持倉 |
| 同時持有多空的對沖邏輯 | 不支援，需改為單一淨部位 |

## 其他注意事項

- **數量是整數張**，不是幣數，也不是 USDT 金額。市價單也一樣。
- **下單是非同步的**，用 `waitOrder` 確認成交再進行下一步。
- **頻率**：bridge 預設每秒最多 5 筆下單；行情輪詢保持 `Sleep(1000)` 以上。
- 遇到 `不支援的方法：<名稱>`，記下函數名稱與 bridge 日誌回報 OneBullEx。

先在測試網跑，確認開平倉、日誌、持倉都正確，再考慮正式環境。
