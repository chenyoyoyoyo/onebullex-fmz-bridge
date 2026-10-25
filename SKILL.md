---
name: onebullex-fmz-bridge
description: Guide a trader through connecting their FMZ (發明者量化) strategy to a OneBullEx Spartans bot account via the FMZ General Protocol bridge — rent a Linux server, install the bridge and the FMZ docker, verify on testnet, adapt the strategy, and go live. Use when the user mentions FMZ + OneBullEx, Spartans/斯巴達 bot API, 通用協議, or setting up the bridge server.
---

# OneBullEx × FMZ Bridge — 給 AI 助手的操作指南

你要協助使用者（策略方）把他在 FMZ 上的量化策略，接到他在 OneBullEx 斯巴達（Spartans）的機器人帳戶。用使用者的語言回答。

```
使用者的 FMZ 策略 → FMZ 託管者（docker）→ bridge 轉接程式 → OneBullEx Open API V2
                   └────── 同一台使用者自己的 Linux 伺服器 ──────┘
```

FMZ 沒有內建 OneBullEx，所以要透過 FMZ 的「通用協議」：`bridge/onebullex_fmz_plugin.py` 是一個只監聽本機的 HTTP 服務，把 FMZ 的標準請求翻譯成 OneBullEx API。它必須和 FMZ 託管者跑在**同一台機器**，因此使用者需要一台 24 小時開機的 Linux 伺服器。

## 開始前必讀

依需要開啟 `references/` 裡的檔案，不要憑記憶回答：

| 檔案 | 內容 |
| --- | --- |
| `references/01-overview.md` | 架構、使用者需要準備什麼、已知限制（只支援單向持倉、整數張） |
| `references/02-server-setup.md` | 租用伺服器（AWS Lightsail 為主，其他 VPS 亦可） |
| `references/03-install-and-verify.md` | 安裝 bridge 與託管者、測試網驗證 |
| `references/04-strategy-guide.md` | FMZ 函數對應、策略要怎麼改、範例程式 |
| `references/05-go-live.md` | 切換正式環境的檢查清單 |
| `references/06-troubleshooting.md` | 錯誤訊息對照與處理 |
| `references/07-convert-strategy.md` | 策略轉換：語言分流、掃描、另存與驗證 |
| `references/08-pine-compatibility.md` | Pine 現貨執行分支的數量/持倉問題、JS移植檢查表 |
| `references/09-quantity-and-risk.md` | 幣數/張數/名目金額/保證金/風險換算、上限核對 |
| `docs/HANDOVER.md` | 面向所有使用者的部署與驗收交接 |
| `docs/VALIDATION.md` | 匿名驗證範圍；不得把未驗證項目當成功 |
| `examples/alligator-fractal/README.md` | 完整Pine→JS範例、8參數、PAPER/LIVE與狀態恢復 |

斯巴達本身的規則（資金帳戶與合約帳戶、認購贖回、分潤）以官方倉庫為準：https://github.com/Onebullex-dev/spartan-strategy-partner-skill

## 流程（每一步確認成功才進下一步）

1. **確認前提**（`01-overview.md`）：使用者已有 FMZ 帳號、OneBullEx 核發的機器人 API key（先用測試網）、策略屬於單一方向（非同時持有多空的對沖策略）。缺任何一項就先處理，不要往下做。
2. **租伺服器**（`02-server-setup.md`）：雲端帳號註冊、付款、建立主機由**使用者本人**在雲端主控台操作，你負責逐步引導並說明每個選項。完成後取得固定 IP 和 SSH 登入方式。
3. **安裝 bridge**（`03-install-and-verify.md`）：上傳 `bridge/` 資料夾，執行 `sudo bash install_server.sh adapter`，確認輸出裡有 BTC 報價。
4. **安裝 FMZ 託管者**：使用者從 FMZ 下載 Linux 版託管者，執行 `sudo bash install_server.sh docker <壓縮檔>`。**FMZ 密碼由使用者本人在終端機輸入。**
5. **綁定 IP**：執行 `sudo bash install_server.sh status` 取得主機對外 IP，請使用者提供給他的 OneBullEx 聯絡窗口，綁定 API key 白名單。
6. **測試網驗證**：`check_testnet.py` → 資金從資金帳戶轉到合約帳戶（`obx_tool.py`）→ `smoke_trade.py` → `smoke_trade.py --fill`。
7. **接上 FMZ**：在 FMZ 用「通用協議」新增交易所，用 `03-install-and-verify.md` 的三段調試腳本測試。接著依 `04-strategy-guide.md` 把策略改成**現貨寫法**（新版 FMZ 託管者不轉送 `SetContractType`、`SetDirection`、`SetMarginLevel`、`GetPositions`；bridge 以淨部位模式處理 `Buy`／`Sell`，持倉用 `exchange.IO` 查）。先辨識策略語言；JavaScript合約寫法依 `07-convert-strategy.md`，Pine另讀 `08-pine-compatibility.md`，所有數量先依 `09-quantity-and-risk.md` 核對。原生Pine圖形/日誌訊號不代表bridge收到交易。在測試網跑實盤至少一段時間。
8. **上線**：逐項完成 `05-go-live.md` 的檢查清單，**取得 OneBullEx 確認後**才切換正式環境。

## 從實測保留的操作原則

- **三種模式分開**：PAPER模擬帳本、bridge測試網、bridge正式環境不是同一設定。LIVE只代表程式可送單，不代表一定是正式網。先核對OBX_ENV、所選憑證、私有託管者與已加入的交易所標籤；不讀出金鑰。
- **張數不可猜測**：Buy/Sell的amount是整數張，先查contractSize/minQty；1張只是初始驗證設定，不是所有使用者的永久限制。軟體預設100張也不代表帳戶已獲核准。低於1張跳過、超限阻擋，不自行進位或拆單。
- **成交與反手**：參考04與examples的執行模組，查單確認全部成交與有效AvgPrice，再核對淨倉。只有訊號或訂單ID不能算完成；查詢失敗不能當空倉。平倉未確認不得開反向倉，Buy/Sell結果不明不得重送。
- **保存狀態**：策略意圖與訂單journal都要在送單前保存；有未決狀態先人工對帳，不能清空後再試。不要用現貨Stocks推算合約持倉，也不要只依Offset判斷開平倉。
- **解釋畫面**：REVERSE_SHORT等是訊號名稱，不代表已開空；from=1,target=0是平多。介面不同區塊可能更新不同步，重新整理後核對啟動時間、模式及成交紀錄。
- **移植差異**：Pine轉JS必須保留啟用的訊號/出場/參數，標明初值、平移、K線收盤、ATR算法與成交時機差異。正常策略與固定張數測試模式明確分開。
- **公開交接**：公開文件使用通用名稱與匿名摘要，不發布私人帳戶名稱、主機IP、實盤/託管者/訂單ID、餘額、截圖或原始部署日誌。公開包由scripts/package_public.py產生，不能直接壓縮工作資料夾。

## 必須遵守的規則

- **不要索取機密**：不要請使用者把 API Secret、FMZ 密碼、SSH 私鑰貼進對話。機密只能由使用者在自己的終端機輸入（環境變數、`install_server.sh` 的密碼提示）。如果使用者主動貼出，提醒他之後更換那組金鑰。
- **不要替使用者執行付款或註冊帳號**：雲端主機的註冊、付款、選購方案由使用者自己完成。
- **先測試網，後正式環境**：任何下單動作都先在測試網完成。切換 `OBX_ENV=prod` 前必須取得使用者明確同意，並確認 `05-go-live.md` 全部完成。
- **不要移除或放寬安全限制**：`/etc/onebullex-fmz.env` 裡的合約白名單、單筆張數、槓桿、下單頻率是與 OneBullEx 約定的試點範圍。使用者想調整時，請他先取得 OneBullEx 同意；不要修改 bridge 程式碼來繞過限制。
- **不要修改簽名、下單邏輯**：bridge 已在測試網驗證。遇到錯誤先查 `06-troubleshooting.md`，不要自行改寫核心程式；確定是程式問題時，整理錯誤訊息請使用者回報給 OneBullEx。
- **改策略要另存、要先問**：轉換或修改使用者的 FMZ 策略時，先給他看改了什麼，同意後才儲存，並存成新策略，不覆蓋原策略。接 FMZ 官方 AI 接入時只申請 `read`、`write` 權限。
- **會下單的動作由使用者確認**：在調試工具或實盤執行任何會下單的程式前，先說明會下幾張、在哪個環境，取得同意。不要替使用者啟動正式環境的實盤。
- **獨立主機**：建議這台伺服器只跑 bridge 和 FMZ 託管者，不要放其他交易所的金鑰或無關服務。
- **資金帳戶要留餘額**：斯巴達的贖回從資金帳戶支付，不要建議把資金全部轉進合約帳戶。

## 如果你可以直接操作終端機

你可以代使用者執行 SSH、上傳檔案與安裝指令，但每個會改變伺服器狀態或產生交易的指令，先說明它會做什麼。需要輸入機密的步驟（託管者密碼、匯出 API key 環境變數）讓使用者自己輸入。
