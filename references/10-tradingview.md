# 10 TradingView 訊號接入斯巴達 bot

給在 TradingView 寫策略或指標的人：不用 FMZ，TradingView 警報直接打到自己的斯巴達 bot。

```
TradingView 警報（webhook）
   │ HTTPS POST https://<主機>/webhook
   ▼
Caddy（自動 HTTPS）→ 訊號接收程式 tv_webhook.py（onebullex-tv 服務）
   │ 查持倉 → 補差額 → 確認成交 → 核對持倉
   ▼
OneBullEx 斯巴達 bot 帳戶
```

- **費用**：只有一台雲端主機（例如 AWS Lightsail 最低方案）。不需要 FMZ。
- **訊號是「目標持倉」**：每則訊息說「這個交易對現在應該持有多少」，程式查實際持倉後補差額。TradingView 重送同一則訊號不會重複下單；漏掉一則，下一則到時也會自動對齊。
- 同一個 bot 帳戶的同一個交易對，不要同時用 TradingView 和 FMZ（或手動）下單，目標持倉會互相打架。

## 需要準備

| 項目 | 說明 |
| --- | --- |
| TradingView 付費方案 | webhook 警報不支援免費方案；並且**必須開啟兩步驟驗證**，否則不能填 webhook |
| OneBullEx 斯巴達機器人 API key | 先用測試網；正式環境的 key 要綁主機的固定 IP 白名單 |
| 一台 Linux 雲端主機 | 見 `02-server-setup.md`；要有固定 IP |
| 雲端防火牆開放 80、443 | 80 給 HTTPS 憑證申請，443 接收 TradingView 訊號（TradingView 只送 80／443 埠） |

## 安裝

在主機上（SSH 登入後）：

```bash
git clone https://github.com/chenyoyoyoyo/onebullex-fmz-bridge ~/onebullex-fmz-bridge
cd ~/onebullex-fmz-bridge
sudo bash bridge/install_server.sh tv
```

依提示輸入：

1. 連線環境 `test` 或 `prod`
2. OneBullEx 機器人 API Key
3. API Secret（輸入時不會顯示）

完成後畫面會印出一組 **passphrase**，等一下要放進 TradingView 警報訊息。設定存在 `/etc/onebullex-tv.env`（只有 root 和服務帳號讀得到）。**安裝後預設為試跑模式（`TV_DRY_RUN=1`），只記錄要下的單，不會送出。**

接著到雲端主控台開放 80、443 埠。Lightsail：主機 → Networking → IPv4 Firewall → Add rule，加入 HTTP（80）與 HTTPS（443）。然後：

```bash
sudo bash bridge/install_server.sh https
```

它會安裝 Caddy，用主機 IP 組成免費網域（例如 `18-142-92-78.sslip.io`）並自動申請 HTTPS 憑證，最後印出 **Webhook URL**，例如 `https://18-142-92-78.sslip.io/webhook`。有自己的網域時可以改用：`sudo bash bridge/install_server.sh https bot.example.com`（網域要先指到主機 IP）。

## 在 TradingView 建立警報

1. 圖表上加入你的策略 → 建立警報（Alert）
2. **Condition（條件）**：選你的策略，觸發選「Order fills only」或「alert() function calls」皆可
3. **Notifications（通知）**：勾選 Webhook URL，貼上安裝時印出的網址
4. **Message（訊息）**：整段換成下面其中一個範本（必須是有效的 JSON，passphrase 換成你的）

### 範本 A：策略警報（建議）

```json
{"passphrase": "你的passphrase", "symbol": "BTCSPARTANS_USDT", "market_position": "{{strategy.market_position}}", "size": "{{strategy.market_position_size}}", "unit": "coin"}
```

- `{{strategy.market_position}}` 會被 TradingView 換成 `long`、`short`、`flat`；`{{strategy.market_position_size}}` 換成策略目前持倉數量。
- `unit: "coin"`：TradingView 策略的數量是**幣數**（在 BTCUSDT 圖上就是 BTC）。程式會用合約面值換成張數，例如 0.0003 BTC = 3 張；不是整數張時無條件捨去。
- 想讓實盤數量和 TradingView 回測不同，加 `"multiplier": 0.1`（實盤 = 回測 × 0.1）。

### 範本 B：指標警報或固定張數

```json
{"passphrase": "你的passphrase", "symbol": "BTCSPARTANS_USDT", "action": "long", "qty": 2}
```

- `action`：`long`（持有多單 qty 張）、`short`（持有空單 qty 張）、`close`（平到空手）。
- 這裡的 qty 是**張數**，而且是「目標持倉」：連續收到兩次 `long 2`，結果仍是多 2 張，不會加到 4 張。
- 也可以直接寫 `"target": 2`（多 2 張）、`"target": -2`（空 2 張）、`"target": 0`（空手）。

### 交易對

| 資產 | symbol | 1 張 |
| --- | --- | --- |
| BTC（斯巴達專屬，建議） | `BTCSPARTANS_USDT` | 0.0001 BTC |
| ETH（斯巴達專屬，建議） | `ETHSPARTANS_USDT` | 0.01 ETH |
| 黃金（斯巴達專屬，建議） | `XAUSPARTANS_USDT` | 0.001 |
| 一般交易對 | `BTC_USDT` 等 | 以 `obx_tool.py spec` 查詢 |

TradingView 的圖表可以用任何交易所的 BTCUSDT，訊息裡的 symbol 決定在 OneBullEx 交易哪一個合約。

## 先試跑，再正式下單

1. 開一個視窗看即時紀錄：`sudo journalctl -u onebullex-tv -f`
2. 讓 TradingView 觸發一次警報。紀錄應出現：
   - `收到訊號 BTCSPARTANS_USDT market_position=long size=...`
   - `[試跑，不下單] BTCSPARTANS_USDT 目前 0 張 → 目標 N 張：開多 N 張`
3. 確認張數和方向都對，再改成正式下單：

```bash
sudo sed -i 's/^TV_DRY_RUN=.*/TV_DRY_RUN=0/' /etc/onebullex-tv.env
sudo systemctl restart onebullex-tv
```

4. 第一次正式下單用最小數量（1 張），確認紀錄出現 `成交 ... 均價 ...` 與 `完成，淨部位 N 張`，並到 OneBullEx 核對持倉。

## 下單規則

- 先平倉、確認成交，再開倉、確認成交，最後核對淨部位等於目標。
- 反手（多 → 空）：先平掉全部多單，再開空單。
- 帳戶同時有多單和空單時，會平到只剩目標方向。分倉帳戶有多筆持倉時，從最早開的一筆開始平。
- 一律市價單。開倉槓桿沿用帳戶設定；要固定槓桿，在設定檔填 `TV_LEVERAGE=5`。
- 訂單沒有完整成交或下單失敗時：停止這則訊號、記錄錯誤，**不會自動重送**。下一則訊號到達時，會依實際持倉重新計算。
- 處理中又收到同一交易對的新訊號：只執行最新的一則。

## 安全

- **passphrase**：訊息裡沒有正確 passphrase 一律拒絕。它就是下單的鑰匙，不要截圖分享警報設定。外流時改 `/etc/onebullex-tv.env` 的 `TV_PASSPHRASE`、重啟服務，再更新 TradingView 警報。
- **來源 IP**：預設只接受 TradingView 官方的 4 個 webhook IP（52.89.214.238、34.212.75.30、54.218.53.128、52.32.178.7）。
- **API key**：只開交易權限、綁主機 IP 白名單；存在主機的設定檔，不要放進 TradingView 訊息。
- 選用防呆：`TV_SYMBOLS`（只允許某些交易對）、`TV_MAX_QTY`（目標持倉超過幾張就不執行）。

## 日常維運

| 要做的事 | 指令 |
| --- | --- |
| 即時紀錄 | `sudo journalctl -u onebullex-tv -f` |
| 最近 20 則訊號的處理結果 | `curl -s http://127.0.0.1:8780/status` |
| 狀態總覽與 Webhook URL | `sudo bash ~/onebullex-fmz-bridge/bridge/install_server.sh status` |
| 修改設定 | `sudo nano /etc/onebullex-tv.env`，存檔後 `sudo systemctl restart onebullex-tv` |
| 更新程式 | `cd ~/onebullex-fmz-bridge && git pull && sudo bash bridge/install_server.sh tv`（設定保留） |

## 疑難排解

| 狀況 | 原因與處理 |
| --- | --- |
| 警報觸發了，紀錄沒有任何東西 | 防火牆未開 443、Webhook URL 打錯、TradingView 未開兩步驟驗證或方案不支援 webhook。在 TradingView 警報紀錄看錯誤 |
| `拒絕：來源 IP ... 不在允許清單` | 不是從 TradingView 送來的請求。自己測試請在主機上直接送到 `http://127.0.0.1:8780/webhook` |
| `拒絕：... passphrase 錯誤` | 訊息裡的 passphrase 與設定檔不同 |
| `拒絕：... 訊息不是 JSON` | 訊息要是完整 JSON：雙引號、逗號、大括號都要正確；TradingView 變數要放在雙引號內 |
| `market_position 只能是 long、short、flat` | 警報條件沒選策略，TradingView 沒有替換 `{{strategy...}}` 變數。指標警報請用範本 B |
| 目標是 0 張、沒有下單 | 幣數換算後不足 1 張（例如 0.00005 BTC）。調大 TradingView 策略數量或用 `multiplier` |
| `not-at-white-list` | 正式環境 key 未綁主機 IP |
| `order_leverage_not_match_position_leverage` | 帳戶槓桿設定讀取異常；在設定檔指定 `TV_LEVERAGE` |
| `未完整成交`、`未確認成交`、`淨部位與目標不符` | 到 OneBullEx 核對訂單與持倉；必要時手動處理，下一則訊號會依實際持倉重算 |
| `https` 步驟連不到網址 | 80 埠未開放導致憑證申請失敗：`sudo journalctl -u caddy -n 30` |

## 限制

- TradingView 警報偶爾會延遲或漏送；本程式不會補發，而是靠下一則目標持倉對齊。
- 實盤成交價與 TradingView 回測不同（市價單、滑價、手續費、資金費）。
- TradingView 策略若會「重繪」（repaint），實盤訊號可能和回測不一致，請先用試跑模式觀察。
- 出場依賴 TradingView 送出訊號；主機或網路中斷期間不會自動平倉。
