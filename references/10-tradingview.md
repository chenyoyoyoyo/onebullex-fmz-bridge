# 10 TradingView 訊號接入（已移到獨立倉庫）

想讓 **TradingView 的策略或指標警報**直接在 OneBullEx 斯巴達機器人帳戶下單（不經過 FMZ），請改用獨立的程式包：

**https://github.com/chenyoyoyoyo/onebullex-tradingview-bridge**

那邊有完整的安裝腳本、HTTPS 設定、警報訊息範本、試跑與正式下單流程，以及給 AI 助手的 `SKILL.md`。本倉庫只處理 FMZ 通用協議的轉接。

同一個機器人帳戶的同一個交易對，不要同時用 TradingView 和 FMZ（或手動）下單，持倉會互相打架。
