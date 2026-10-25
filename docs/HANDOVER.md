# 公開交接指南：FMZ 接入 Spartans

本包供每位FMZ使用者接入**自己的**Spartans bot。你需要自己的FMZ帳號、bot API憑證與雲端主機。不要沿用他人的主機、API key或測試實盤。

## 1. 準備與安裝

1. 讀 [概覽](../references/01-overview.md)，確認單向淨部位適用。
2. 依 [主機指南](../references/02-server-setup.md)建立專用Linux主機；主機費用由本人確認。
3. 依 [安裝指南](../references/03-install-and-verify.md)安裝bridge與官方FMZ託管者。所有shell指令貼到**伺服器SSH終端機**，JavaScript貼到**FMZ策略編輯器或調試工具**，不要混貼。
4. bridge與託管者必須同機；不要對外開6666埠。確認兩個systemd服務可用、報價正常、FMZ託管者在線。
5. 按OneBullEx要求綁定固定IP白名單。能查公開行情不代表私有交易權限已通過。

憑證由本人在終端機隱藏輸入或官方服務表單私下填寫。不要貼到聊天、GitHub issue、截圖、日誌或範例程式。

## 2. 在 FMZ 接上帳戶

- 新增「通用協議」，服務地址 `http://127.0.0.1:6666/OneBullEx`。
- Access Key / Secret Key 使用自己的OneBullEx bot憑證，**不是FMZ密碼或AWS金鑰**。
- 可將FMZ交易所設定命名為 `OneBullEx-Spartans`，或自訂名稱並同步範例的 `AF_ACCOUNT_LABEL`。
- 調試與實盤選安裝bridge的**私有託管者**，不要選自動分配或公用主機。
- 建立實盤選好交易所後，還要按 **＋**，確認已出現 `設定名稱/交易對` 標籤（例如 `OneBullEx-Spartans/BTCSPARTANS_USDT`）。選單顯示的候選平台不是已加入的平台。
- 斯巴達的 BTC、ETH、黃金策略建議用專屬交易對 `BTCSPARTANS_USDT`、`ETHSPARTANS_USDT`、`XAUSPARTANS_USDT`。**交易對下拉選單裡找不到，要在欄位直接輸入名稱，再點下方出現的選項。** 面值與一般交易對可能不同，見 [04](../references/04-strategy-guide.md)。
- 先唯讀查行情、規格、餘額、持倉與掛單，再小量送單測試。

## 3. 選策略與數量

JavaScript依 [04](../references/04-strategy-guide.md)調整。Pine先讀 [08](../references/08-pine-compatibility.md)，審核移植後的完整程式與參數。數量依 [09](../references/09-quantity-and-risk.md)換算。下單張數與槓桿由策略決定，bridge 預設不限制；槓桿設定方式見 04「槓桿」。

可從 [一分鐘鱷魚碎形範例](../examples/alligator-fractal/README.md)開始。這不是獲利推薦，是可檢查的訊號與執行範例；它不會強制產生交易，也不保證下一分鐘有訊號。

## 4. 分階段驗收

| 階段 | 必須確認 | 不能據此宣稱 |
| --- | --- | --- |
| 離線測試 | 指標、數量、成交/異常控制流程 | 交易所已成交 |
| 唯讀連線 | 正確帳戶、報價、規格、持倉/掛單查詢 | 交易權限與送單可用 |
| PAPER | 新K線更新、自然訊號、模擬開平、狀態恢復 | 已真實下單 |
| 小量真實測試 | 訂單ID、全部成交、成交均價、持倉同步、平倉後無掛單 | 所有方向/策略/數量均已驗證 |
| 正式部署 | 維運與故障處理、一段時間觀察 | 無風險或保證收益 |

先測試網，正式前完成 [上線檢查](../references/05-go-live.md)。PAPER不會改變bridge所連環境；`AF_RUN_MODE=1`表示送真實訂單，但送到測試網還是正式環境，由伺服器`OBX_ENV`與所選憑證決定，不能只看實盤名稱。

先停止個體再更新參數，重新讀回確認。範例的PAPER與LIVE狀態分開保存，首次切LIVE不會沿用PAPER持倉；歷史日誌仍會保留，請用本次啟動時間與 `LIVE_CONFIRMED` 區別。正式啟動或重啟由使用者親自操作。

## 5. 看懂結果

- `SIGNAL` 是意圖，`PAPER_FILL` 是模擬；`LIVE_CONFIRMED` 表示策略已查單並核對成交與持倉，仍可再次唯讀對帳。
- `REVERSE_SHORT` 是反向訊號名稱，不代表已持有空單。看 `from` / `target`：+1→0是平多，0→-1才是開空。
- `AF_MAX_ROUND_TRIPS=1` 時平倉便結束，反手新倉不再開；正常持續運行設為0。
- `complete=true`、`net=0`、`closedTrades=1`、FMZ「已完成」才表示本次驗證結束。介面不同區塊可能暫未同步，重新整理並對照同一時間的日誌。
- 不明送單結果保留journal，先唯讀查單、成交、持倉、掛單，不要清空狀態或重送。

## 6. 維運與公開回報

維持託管者與bridge在線。範例出場由主機判斷，不是交易所原生止損；程序崩潰、網路中斷或停止不會自動平倉。持倉期間發生故障時，由帳戶操作者核對並處理，不要盲目重啟。

公開回報只附：版本/commit、執行模式、週期、經遮蔽的錯誤與重現步驟。原始訂單與帳戶識別交由本人私下保存；不得上傳金鑰、密碼、完整主機設定、私人IP或帳戶截圖。

下載可直接用GitHub ZIP；維護者可執行 `python3 scripts/package_public.py` 產生同內容的公開交接ZIP。授權範圍見 [NOTICE](../NOTICE.md)。
