# OneBullEx × FMZ Bridge

把你在 FMZ（發明者量化）上的策略，接到 OneBullEx 斯巴達（Spartans）機器人帳戶的工具包，人和 AI 助手都能使用。

## 交給你的 AI 助手

把下面這段貼給你的 AI 助手（它要能開網頁）：

> 讀 https://github.com/chenyoyoyoyo/onebullex-fmz-bridge ，從 `SKILL.md` 開始。依照裡面的流程，一步步引導我租一台伺服器，把我的 FMZ 策略接到 OneBullEx 斯巴達機器人；如果我的策略是合約寫法，依 `references/07-convert-strategy.md` 幫我轉換。每一步確認成功再進下一步，需要我輸入密碼或金鑰時讓我自己在終端機輸入，不要叫我貼到對話裡。回答前先打開相關檔案，不要憑記憶回答。

如果你的 AI 助手只能開一個網址，改用這段：

> 讀 https://raw.githubusercontent.com/chenyoyoyoyo/onebullex-fmz-bridge/main/SKILL.md ，需要時再依它列出的路徑，打開 `https://raw.githubusercontent.com/chenyoyoyoyo/onebullex-fmz-bridge/main/<路徑>` 的檔案。

不能開網頁的 AI 助手，請下載本倉庫（綠色的 Code 按鈕 → Download ZIP），把資料夾放在它讀得到的位置。

**安裝成 Claude Code 技能**：

```bash
git clone https://github.com/chenyoyoyoyo/onebullex-fmz-bridge ~/.claude/skills/onebullex-fmz-bridge
```

之後提到 FMZ 和 OneBullEx 時會自動使用。要更新時在該資料夾執行 `git pull`。

**伺服器上取得程式**：

```bash
git clone https://github.com/chenyoyoyoyo/onebullex-fmz-bridge
cd onebullex-fmz-bridge/bridge
```

## 自己閱讀

依序閱讀 `references/01` 到 `06`：

| 檔案 | 內容 |
| --- | --- |
| `01-overview.md` | 架構、準備事項、已知限制 |
| `02-server-setup.md` | 租用伺服器 |
| `03-install-and-verify.md` | 安裝與測試網驗證 |
| `04-strategy-guide.md` | 策略撰寫與調整 |
| `05-go-live.md` | 上線檢查清單 |
| `06-troubleshooting.md` | 疑難排解 |
| `07-convert-strategy.md` | 把合約寫法的策略轉成可用寫法 |

## 資料夾內容

```
SKILL.md                 給 AI 助手的入口
README.md                本檔
llms.txt                 檔案索引
references/              操作指南
bridge/
  onebullex_fmz_plugin.py  轉接程式（只用 Python 標準函式庫）
  install_server.sh        伺服器一鍵安裝（bridge 與 FMZ 託管者）
  check_testnet.py         API key 連線檢查（只讀取）
  obx_tool.py              查餘額、資金帳戶與合約帳戶轉帳
  smoke_trade.py           測試網下單流程測試
  tests/test_plugin.py     離線測試（模擬交易所）
```

## 驗證狀態

- 離線測試 38 項通過
- OneBullEx 測試網實測通過：報價、帳戶、槓桿、限價掛單、查單、撤單、市價開平倉、安全限制
- 依據 OneBullEx Open API V2（文件版本 2.1.1）
- FMZ 實測通過（託管者 v3.9.2）：行情、帳戶、限價與市價下單、查單、撤單、以淨部位模式開平倉、`exchange.IO` 查持倉
- 策略需使用現貨寫法（`Buy`／`Sell`），見 `references/04-strategy-guide.md`

## 免責聲明

本工具包提供技術串接，不構成投資建議。策略的風險控管、資金配置與系統故障的處理由使用者自行負責。斯巴達的規則以 OneBullEx 官方公告為準。
