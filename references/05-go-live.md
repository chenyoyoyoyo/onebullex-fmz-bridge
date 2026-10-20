# 05 上線檢查清單

全部打勾，且 **OneBullEx 確認後**，才切換正式環境。

## 測試網

- [ ] `check_testnet.py` 五項全部 OK
- [ ] `smoke_trade.py` 與 `smoke_trade.py --fill` 全部 OK
- [ ] FMZ 調試工具能查行情、帳戶、持倉，能下單與撤單
- [ ] 策略在測試網以實盤跑過一段時間，開倉、平倉、日誌、盈虧都正確
- [ ] 確認策略是單一方向（不同時持有多空），數量為整數張
- [ ] 伺服器重開機後，兩個服務都自動恢復（`sudo reboot` 後執行 `install_server.sh status`）

## 正式環境準備

- [ ] 已向 OneBullEx 申請**正式環境**機器人 API key，並綁定這台伺服器的固定 IP
- [ ] API key 只開交易權限，沒有提幣權限
- [ ] 與 OneBullEx 確認安全限制的數值（合約白名單、單筆張數、槓桿、下單頻率）
- [ ] 機器人帳戶已完成認購，資金帳戶保留應付贖回的餘額

## 切換步驟

1. 在伺服器修改設定檔：

   ```bash
   sudo nano /etc/onebullex-fmz.env
   # 把 OBX_ENV=test 改成 OBX_ENV=prod，並依 OneBullEx 確認的數值調整限制
   sudo systemctl restart onebullex-fmz
   sudo bash ~/onebullex_fmz/install_server.sh status
   ```

2. 在 FMZ 新增一個交易所設定，填入**正式環境**的 API key（保留測試網的那組，方便日後測試）
3. 用調試工具只查詢，確認是正式環境的帳戶餘額
4. 以小資金、小數量開始，觀察至少一天
5. 正式環境不要執行 `smoke_trade.py`（程式本身也會拒絕）

## 回到測試網

設定檔改回 `OBX_ENV=test` 並重啟 `onebullex-fmz` 即可。注意：同一時間只能連一個環境，切換時先停掉正式環境的實盤。
