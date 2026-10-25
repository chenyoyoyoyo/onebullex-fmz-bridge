# OneBullEx × FMZ Bridge

讓 FMZ（發明者量化）策略透過通用協議，交易自己的 OneBullEx 斯巴達（Spartans）bot 帳戶。適合需要自架託管者、調整策略、確認訂單與持倉的 FMZ 使用者。

```text
策略訊號 → FMZ JavaScript → 自架 FMZ 託管者 → 本機 bridge → Spartans bot
```

**已完成一分鐘策略的自然訊號 → 正式 BTC 1 張開多 → 確認成交 → 平多 → 空倉停止。** 這證明一回合串接可用，不代表策略獲利、所有 Pine 策略相容或長期穩定性已驗證。匿名驗證範圍見 [驗證紀錄](docs/VALIDATION.md)。

## 從哪裡開始

- **第一次使用**：[公開交接指南](docs/HANDOVER.md)，依序完成主機、bridge、託管者、測試網與正式驗收。
- **已有 FMZ JavaScript 策略**：[策略介面](references/04-strategy-guide.md)與[轉換流程](references/07-convert-strategy.md)。
- **已有 Pine 策略**：先讀 [Pine 相容性與轉換](references/08-pine-compatibility.md)。本次成功路徑是 Pine 邏輯移植至 JavaScript；**不是原生 Pine 直接透過本 bridge 下單成功**。
- **需要可執行範例**：[一分鐘鱷魚與碎形突破](examples/alligator-fractal/README.md)，附完整 FMZ 程式、原始 Pine、8 個參數、建置程式與離線測試；預設 PAPER 不下單。
- **張數怎麼算**：[數量、名目金額、保證金與風險](references/09-quantity-and-risk.md)。`Buy/Sell` 的 amount 是整數張，不是 BTC，也不是 USDT。

## 交給 AI 助手

> 讀 https://github.com/chenyoyoyoyo/onebullex-fmz-bridge ，從 SKILL.md 開始。依 references/ 和 docs/HANDOVER.md 一步步協助我把自己的 FMZ 策略接到自己的 Spartans bot。先判斷策略語言；若為 Pine，先讀相容性與數量換算，不要把圖上訊號當作真實成交。每一步核對成功再繼續，修改策略先展示完整版本並另存。密碼與金鑰由我在終端機或服務官方表單私下輸入，不貼到聊天。每次涉及真實交易先說明環境與張數，由我確認並親自啟動。回答前讀相關檔案。

單檔入口：[SKILL.md 原始檔](https://raw.githubusercontent.com/chenyoyoyoyo/onebullex-fmz-bridge/main/SKILL.md)。不能讀網頁的助手，可使用 GitHub 的 **Code → Download ZIP**。

```bash
# 下載工具包；這一步不安裝服務、不下單
git clone https://github.com/chenyoyoyoyo/onebullex-fmz-bridge
cd onebullex-fmz-bridge
```

可讀取本機技能的 AI 工具，也能將整個倉庫放到其技能目錄；入口是 `SKILL.md`。不要只複製入口而遺漏 references 與 examples。

## 前提與邊界

- 自己的 FMZ 帳號、OneBullEx 核發的 bot API 憑證、可交易的合約帳戶資金及核准範圍。
- 自架 Linux 主機；FMZ 託管者與 bridge 在同一台。bridge 僅監聽 `127.0.0.1:6666`，不要對公網開放該埠。
- 先測試網；PAPER 只驗證真實行情與策略邏輯，**不會測試交易所下單鏈路**。正式小量測試需額外確認並對帳。
- 使用單向淨部位。反手分成「平舊倉 → 成交及空倉確認 → 開新倉」，不能用一張超過現有持倉的反向單代替。
- 1 張是範例的初始驗證設定，並非平台永久限制。正常張數由策略、合約規格、可用保證金及帳戶核准上限共同決定；不拆單繞過限制。
- 不明送單結果不得自動重送。程序停止也不代表持倉自動平掉；此範例的出場依賴主機持續運作。

## 目錄

| 路徑 | 用途 |
| --- | --- |
| [SKILL.md](SKILL.md) | AI 助手操作入口 |
| [docs/HANDOVER.md](docs/HANDOVER.md) | 給所有 FMZ 使用者的交接與驗收步驟 |
| [docs/VALIDATION.md](docs/VALIDATION.md) | 已驗證與未驗證的範圍 |
| [references/](references/) | 安裝、交易介面、Pine、數量換算與排錯 |
| [bridge/](bridge/) | Python bridge、安裝器、測試網工具與測試 |
| [examples/alligator-fractal/](examples/alligator-fractal/) | Pine 邏輯移植 JavaScript 的通用範例 |
| [scripts/package_public.py](scripts/package_public.py) | 只封裝 Git 已追蹤公開檔案，產生 ZIP 與 SHA-256 |

## 開發者驗證與封裝

離線測試不連交易所、不產生訂單。需要 Python 3.8+；範例建置與測試使用 Node.js 22+。

```bash
python3 bridge/tests/test_plugin.py
node examples/alligator-fractal/build.js
node --test examples/alligator-fractal/*.test.js
python3 scripts/package_public.py
```

輸出為 `dist/onebullex-fmz-bridge-public.zip` 與同名 `.sha256`。請勿把自己的部署資料夾直接壓縮上傳；金鑰、日誌、帳戶截圖及本機工作檔不屬於公開包。

## 授權

橋接工具與文件採 [MIT](LICENSE)。`examples/alligator-fractal/` 的 Pine 衍生範例採 [MPL-2.0](LICENSES/MPL-2.0.txt)，詳見 [NOTICE.md](NOTICE.md)。未附入 FMZ 託管者二進位或官方 Pine 核心原始碼，請從官方取得。

本工具包提供技術串接，不構成投資建議。每位使用者應以自己的帳戶、憑證及核准範圍驗證，斯巴達規則以 OneBullEx 官方為準。
