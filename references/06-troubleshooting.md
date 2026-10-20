# 06 疑難排解

先看 bridge 日誌：`sudo journalctl -u onebullex-fmz -n 100`。錯誤也會顯示在 FMZ 實盤或調試工具的日誌。

## 連線與驗證

| 錯誤訊息 | 原因與處理 |
| --- | --- |
| `HTTPS 憑證驗證失敗` / `CERTIFICATE_VERIFY_FAILED` | Python 缺少憑證。伺服器上執行 `sudo apt-get install -y python3-certifi`；Mac 上執行 `python3 -m pip install certifi` 或「Install Certificates.command」 |
| `OneBullEx HTTP 403` | 被網站防火牆擋下。確認使用的是最新版 bridge（已帶 User-Agent），並回報 OneBullEx |
| `連線 OneBullEx 失敗` | 伺服器網路或 DNS 問題。在伺服器執行 `curl -s https://futures-openapi.1bullex.com/v2/public/time` 測試 |
| `not-at-white-list` | 伺服器 IP 未綁定白名單。用 `install_server.sh status` 取得 IP，提供給 OneBullEx |
| `code-sign-not-match` | Secret Key 錯誤或有多餘空白。重新確認金鑰 |
| `timestamp-error` | 伺服器時間不準（誤差需小於 30 秒）。執行 `timedatectl`，確認 `System clock synchronized: yes` |
| `not-find-user-api` / `user-api-is-forbidden` | API key 不存在、已刪除或停用。聯絡 OneBullEx |
| `open-auth-version-err` | 不是 V2 的 API key。向 OneBullEx 申請 V2 key |
| `不支援的方法：<名稱>` | FMZ 呼叫了 bridge 尚未實作的函數。記下函數名稱與 bridge 日誌，回報 OneBullEx |
| `路徑錯誤` | FMZ 服務地址不正確，應為 `http://127.0.0.1:6666/OneBullEx` |
| FMZ 顯示連不到服務 | bridge 沒在跑，或託管者不在同一台機器。執行 `install_server.sh status` |

## 下單

| 錯誤訊息 | 原因與處理 |
| --- | --- |
| `目前持有多單／空單 N 張，單筆最多只能平 N 張` | 淨部位模式不自動反手。先平掉原部位，確認持倉為空再開新方向（見 `04-strategy-guide.md` 的 `moveTo`） |
| `order_leverage_not_match_position_leverage` | 開倉槓桿與合約設定不符。確認使用最新版 bridge（會自動帶入帳戶槓桿） |
| `not supported by Exchange` / `unsupported rest method` | FMZ 託管者擋下合約專屬函數（`SetContractType`、`SetMarginLevel`、`GetPositions`）。改用現貨寫法，見 `04-strategy-guide.md` |
| `下單方向與 SetDirection 不符` | 只會出現在舊版託管者有轉送 `SetDirection` 時：方向與下單函數沒有成對 |
| `合約數量必須是整數張` / `invalid_quantity` | 數量要換算成整數張 |
| `不在允許清單內` | 合約不在 `OBX_ALLOWED`。要新增請先取得 OneBullEx 同意 |
| `超過上限`（張數、槓桿、頻率） | 觸發安全限制。調整策略，或取得 OneBullEx 同意後修改設定檔 |
| `沒有可平的多倉／空倉` / `超過可平數量` | 平倉前用 `exchange.IO` 查持倉確認數量 |
| `invalid_price` | 價格精度或最小跳動不符。BTC 價格精度 1 位小數、最小跳動 0.1 |
| `查無此訂單` | 下單為非同步；bridge 會自動等候約 2 秒再查。仍查不到時，稍後再查或確認訂單 ID |
| 合約帳戶可用為 0 | 資金在資金帳戶。執行 `obx_tool.py transfer <金額>` |
| `transfer failed` | 資金帳戶餘額不足，或認購尚未入帳（每小時處理一次） |
| `invalid_leverage` | 槓桿超出該合約允許範圍 |

## 服務

| 狀況 | 處理 |
| --- | --- |
| FMZ 顯示託管者離線 | `sudo systemctl status fmz-robot`、`sudo tail -n 50 /opt/robot/logs/docker.log` |
| 託管者密碼錯誤或要換帳號 | `sudo rm /opt/robot/robot.conf` 後重跑 `install_server.sh docker <壓縮檔>` |
| 策略無法啟動（權限相關錯誤） | 託管者以 `-u fmzstrat` 執行策略。若確認是權限問題，回報 OneBullEx 協助判斷，不要直接改成以 root 執行 |

## 回報問題時請提供

- 錯誤訊息全文與發生時間
- `sudo bash install_server.sh status` 的輸出
- `sudo journalctl -u onebullex-fmz -n 100` 的輸出
- 不要附上 API Secret、FMZ 密碼或私鑰
