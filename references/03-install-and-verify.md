# 03 安裝與測試網驗證

## 1. 取得 bridge

登入伺服器（把路徑、IP 換成實際值）：

```bash
ssh -i <私鑰.pem> ubuntu@<固定IP>
```

在伺服器上下載程式（之後的指令都以 `~/onebullex_fmz` 為準）：

```bash
git clone https://github.com/chenyoyoyoyo/onebullex-fmz-bridge ~/onebullex-fmz-bridge
ln -sfn ~/onebullex-fmz-bridge/bridge ~/onebullex_fmz
```

日後更新：`cd ~/onebullex-fmz-bridge && git pull`，再執行 `sudo bash ~/onebullex_fmz/install_server.sh adapter`（設定檔會保留）。

伺服器無法連 GitHub 時，改從自己的電腦上傳：`scp -i <私鑰.pem> -r <倉庫路徑>/bridge ubuntu@<固定IP>:~/onebullex_fmz`。

## 2. 安裝 bridge 轉接程式

在伺服器上：

```bash
cd ~/onebullex_fmz
sudo bash install_server.sh adapter
```

成功時最後會印出 BTC 報價（含 `"last"`）與 `轉接程式安裝完成`。

- 安裝位置：`/opt/onebullex_fmz`
- 設定檔：`/etc/onebullex-fmz.env`（預設 `OBX_ENV=test` 測試網）
- 服務：`onebullex-fmz`，開機自動啟動，以受限帳號 `obxfmz` 執行

## 3. 安裝 FMZ 託管者

1. 使用者登入 FMZ →「託管者」→「添加託管者」→「手動部署」，下載 Linux 版（依伺服器架構選 amd64 或 arm64），並記下頁面上的**通訊地址**（`node.fmz.com/數字`）
2. 上傳到伺服器：`scp -i <私鑰.pem> <下載的壓縮檔> ubuntu@<固定IP>:~`
3. 在伺服器上執行，並由**使用者本人**輸入通訊地址、FMZ 密碼（不會顯示）、託管者名稱：

   ```bash
   cd ~/onebullex_fmz
   sudo bash install_server.sh docker ~/<下載的壓縮檔>
   ```

4. 到 FMZ「託管者」頁面確認顯示為**在線**

- 安裝位置：`/opt/robot`；密碼存於 `/opt/robot/robot.conf`（只有 root 可讀）
- 服務：`fmz-robot`，開機自動啟動；策略以受限帳號 `fmzstrat` 執行

## 4. 取得對外 IP 並綁定白名單

```bash
sudo bash install_server.sh status
```

把「本機對外 IP」提供給 OneBullEx 聯絡窗口，綁定 API key 白名單。綁定前呼叫私有 API 會出現 `not-at-white-list`。

## 5. 測試網驗證

在伺服器上，由**使用者本人**設定金鑰（不要貼進對話）：

```bash
cd /opt/onebullex_fmz
export OBX_API_KEY=<測試網 Access Key>
read -rs OBX_SECRET && export OBX_SECRET   # 貼上 Secret Key 後按 Enter，不會顯示
```

依序執行，每一步都要成功：

| 指令 | 預期結果 |
| --- | --- |
| `python3 check_testnet.py` | 五項 OK：時間差、BTC 報價、合約規格、簽名（查餘額）、持倉模式 |
| `python3 obx_tool.py balance` | 看到資金帳戶與合約帳戶餘額 |
| `python3 obx_tool.py transfer 1000` | 若合約帳戶為 0，從資金帳戶轉入測試用金額（保留部分在資金帳戶） |
| `python3 smoke_trade.py` | 限價掛單、查單、撤單，以及超過上限被擋，全部 OK；不產生持倉 |
| `python3 smoke_trade.py --fill` | 再加上市價開多 1 張、查持倉、市價平多，最後持倉為空 |

`smoke_trade.py` 只能在測試網執行。

## 6. 在 FMZ 新增交易所

1. FMZ →「交易所」→「添加交易所」
2. 協議：**通用協議**
3. 服務地址：`http://127.0.0.1:6666/OneBullEx`
4. Access Key、Secret Key：OneBullEx 機器人 API key
5. 建立實盤或使用調試工具時，**託管者要選這台伺服器**

用 FMZ 調試工具先只查詢：

```javascript
function main() {
    exchange.SetCurrency("BTC_USDT")
    Log("報價", exchange.GetTicker())
    Log("帳戶", exchange.GetAccount())
    Log("持倉", exchange.IO("api", "GET", "/v2/position/list", "symbol=btc_usdt"))
}
```

再下一張不會成交的限價單並撤掉（不產生持倉）：

```javascript
function main() {
    exchange.SetCurrency("BTC_USDT")
    var t = exchange.GetTicker()
    var id = exchange.Buy(_N(t.Last * 0.9, 1), 1)   // 低於市價 10%，不會成交
    Sleep(1500)
    Log("查單", exchange.GetOrder(id))
    Log("撤單", exchange.CancelOrder(id))
}
```

最後用市價開平 1 張，確認淨部位模式（會實際成交 1 張，測試網）：

```javascript
function main() {
    exchange.SetCurrency("BTC_USDT")
    var pos = function () { return exchange.IO("api", "GET", "/v2/position/list", "symbol=btc_usdt") }
    var id1 = exchange.Buy(-1, 1)          // 沒有空單 → 開多 1 張
    Sleep(2000)
    Log("買單", exchange.GetOrder(id1), "持倉", pos())
    var id2 = exchange.Sell(-1, 1)         // 有多單 → 平多 1 張
    Sleep(2000)
    Log("賣單", exchange.GetOrder(id2), "持倉（應為空）", pos())
}
```

`SetContractType`、`SetDirection`、`SetMarginLevel`、`GetPositions` 在通用協議下不可用，策略寫法見 `04-strategy-guide.md`。

## 7. 日常維運

| 要做的事 | 指令 |
| --- | --- |
| 查看狀態與 IP | `sudo bash ~/onebullex_fmz/install_server.sh status` |
| bridge 即時日誌 | `sudo journalctl -u onebullex-fmz -f` |
| 託管者日誌 | `sudo tail -f /opt/robot/logs/docker.log` |
| 重啟 bridge | `sudo systemctl restart onebullex-fmz` |
| 重啟託管者 | `sudo systemctl restart fmz-robot` |
| 更新 bridge | `cd ~/onebullex-fmz-bridge && git pull`，再重跑 `sudo bash ~/onebullex_fmz/install_server.sh adapter`（設定檔保留） |
| 升級託管者 | 重跑 `sudo bash install_server.sh docker <新壓縮檔>`（帳號與實盤資料保留） |
