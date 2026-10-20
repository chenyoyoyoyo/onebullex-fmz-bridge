# 02 租用伺服器

註冊雲端帳號、付款、建立主機由使用者本人操作；AI 助手負責一步步引導並解釋選項。

## 規格

- 作業系統：**Ubuntu 24.04 LTS**（22.04 亦可）
- 架構：x86_64（amd64）或 ARM64
- 規格：最低方案即可（512 MB 至 1 GB 記憶體）。只跑一兩個策略不需要更多
- 區域：建議**新加坡**
- 必須有**固定公網 IP**（要綁定 API key 白名單）
- 防火牆：只開 SSH（22）

## 方案 A：AWS Lightsail（建議，操作最簡單，每月約 5 美元起）

1. 註冊 AWS 帳號並登入 https://lightsail.aws.amazon.com
2. **Create instance**
   - Region：Singapore（ap-southeast-1）
   - Platform：Linux/Unix
   - Blueprint：**OS Only → Ubuntu 24.04 LTS**
   - SSH key：使用預設金鑰，並下載（`LightsailDefaultKey-ap-southeast-1.pem`）
   - Plan：最低方案
   - Name：例如 `fmz-onebullex`
3. 建立完成後，到該主機的 **Networking** 分頁：
   - **Attach static IP**：建立並綁定固定 IP，記下這個 IP
   - **IPv4 Firewall**：只保留 SSH（22），刪除 HTTP（80）等其他規則
4. 在自己的電腦測試 SSH：

   ```bash
   chmod 400 ~/Downloads/LightsailDefaultKey-ap-southeast-1.pem
   ssh -i ~/Downloads/LightsailDefaultKey-ap-southeast-1.pem ubuntu@<固定IP>
   ```

   Windows 可用內建的 PowerShell 執行同樣的 `ssh` 指令。

## 方案 B：其他雲端（AWS EC2、Google Cloud、Vultr、DigitalOcean、阿里雲國際等）

要點相同：Ubuntu 24.04、最低規格、新加坡區域、綁定固定 IP（EC2 叫 Elastic IP）、安全群組或防火牆只開 SSH。登入使用者名稱依平台而異（Ubuntu 映像常見為 `ubuntu` 或 `root`）。

## 完成條件

- [ ] 能用 SSH 登入伺服器
- [ ] 已綁定固定 IP，並記下 IP
- [ ] 防火牆只開放 SSH

## 注意

- 這台伺服器建議只用來跑 bridge 和 FMZ 託管者，不要放其他交易所的金鑰。
- SSH 私鑰（`.pem`）不要傳給任何人，也不要貼進對話。
