# Indicator Lab

Indicator Lab 是一套在使用者自己電腦上執行的繁體中文指標研究工具。它透過本機 PineTS 把 TradingView Pine 指標套用到歷史 K 線，讓使用者逐筆標記訊號為「贏、輸或無效」，再用數值規則比較贏單與輸單特徵，分別改善做多與做空條件並產生下一版 Pine。

> [!IMPORTANT]
> 本專案是本機研究工具，不是雲端交易平台，也不會自動下單。GitHub 只保存程式碼；K 線、Pine 原碼、人工標記、模型和改善版本預設都不會上傳。

## 主要功能

- 建立 Binance U 本位永續或現貨研究市場。
- 選擇交易對、K 線週期與顯示時區。
- 自動同步 Binance 可取得的完整歷史 K 線。
- 上傳 `.pine`／`.txt`，或直接貼上 Pine Script。
- 逐筆查看訊號附近 K 線並標記「贏、輸、無效」。
- 隨時返回上一筆修改，不要求全部標記完才分析。
- 顯示做多、做空與綜合人工標記勝率。
- 比較贏單與輸單的數值特徵。
- 做多與做空分開尋找過濾條件。
- 沒有改善的方向完整沿用上一版。
- 每次改善另存 V2、V3……，不覆蓋 V1。
- 在版本頁直接複製完整 Pine 到 TradingView。
- 可刪除單一改善版本、整個策略或整份市場資料。

## 使用前準備

### 系統需求

- Windows 10 或 Windows 11
- Python 3.11 以上，建議 Python 3.12（64 位元）
- Node.js 20 以上（供 PineTS 執行 Pine 指標）
- 可連線至 Binance API 的網路
- 現代瀏覽器，例如 Chrome、Edge 或 Firefox

可在 PowerShell 輸入以下指令確認 Python：

```powershell
py --version
node --version
```

若沒有顯示 Python 版本，請先從 [Python 官方網站](https://www.python.org/downloads/windows/) 安裝 Python。安裝時請勾選 **Add Python to PATH**。若沒有 Node.js，請先安裝 Node.js 20 以上版本。

## 下載專案

可以選擇以下任一方式。

### 方法一：下載 ZIP

1. 進入本專案的 GitHub 頁面。
2. 按 **Code**。
3. 按 **Download ZIP**。
4. 將 ZIP 解壓縮到一般資料夾。
5. 不要直接在 ZIP 壓縮檔內執行程式。

### 方法二：使用 Git

```powershell
git clone https://github.com/cccctotototo/indicator-lab.git
cd indicator-lab
```

## 第一次安裝

在專案資料夾空白處按住 `Shift` 並按滑鼠右鍵，選擇「在終端機中開啟」，依序執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
npm.cmd install --ignore-scripts --no-audit --no-fund
```

安裝完成後，專案內會出現 `.venv`。它只屬於目前這台電腦，不需要也不應上傳 GitHub。

## 啟動網站

最簡單的方法是雙擊：

```text
start_indicator_lab.bat
```

啟動器會開啟 Indicator Lab。若瀏覽器沒有自動開啟，請手動進入：

```text
http://localhost:8503
```

`localhost` 代表網站只在自己的電腦執行，不是別人的網站。使用期間請保留啟動視窗；關閉啟動視窗後，本機網站會停止。

也可以使用 PowerShell 手動啟動：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8503
```

## 完整操作流程

### 1. 匯入策略並建立 V1

進入左側「匯入策略」：

1. 輸入策略名稱，建議只使用英文字母、數字和底線。
2. 上傳 Pine 檔，或貼上完整 Pine 程式碼。
3. 選擇市場、交易對、K 線週期和顯示時區。
4. 按「驗證策略並建立 V1」。

建立新的 Binance 研究市場時，系統會同步該交易對可取得的歷史行情並更新到現在。下載時間取決於週期、上市時間、網路速度與 Binance API 限制。

#### PineTS 指標執行方式

系統不再使用自製 Python Pine 判斷器，也不需要 TradingView 訊號 CSV。Pine `indicator()` 會直接交給本機 PineTS 執行，再從下列位置辨識做多與做空：

1. 常見變數名稱，例如 `longSignal`／`shortSignal`、`buySignal`／`sellSignal`。
2. `plotshape`、`plotchar` 或 `alertcondition` 的標題、文字與條件。
3. 若指標使用特殊命名，可展開匯入頁的進階欄位，直接指定做多與做空變數或布林運算式。

匯入器會先實際執行指標並確認訊號，成功後才保存 V1，不會留下半成品。目前只接受 `indicator()`；`strategy()` 的部位與券商模擬不屬於這個指標標記流程。同商品高週期 `request.security()` 可由本機 K 線聚合，跨商品呼叫則需要額外行情資料。

### 2. 標記訊號

進入「標記訊號」，逐筆查看訊號附近的 K 線：

- **贏**：符合自己事先固定的獲利判定。
- **輸**：符合自己事先固定的虧損判定。
- **無效**：資料異常、訊號不應納入，或無法客觀判斷。

標記後會前往下一筆，也能使用「上一筆」返回修改。未標記及無效資料不會被當成贏或輸。

開始前應先固定自己的判定規則，例如：

- 進場價格
- 停利與停損
- 最長持有 K 棒數
- 同一根 K 同時碰到停利與停損時的處理方式
- 手續費與滑價

判定規則若中途改變，前後標記就無法公平比較。

### 3. 執行 AI 改善

進入「AI 改善」後，可以查看：

- 做多人工標記勝率
- 做空人工標記勝率
- 綜合人工標記勝率
- 贏單與輸單的主要數值特徵
- 目前有效標記與未標記數量

只要已有至少一筆贏或輸，系統就能顯示現有樣本分析，不必把全部訊號標完。若要真正比較贏輸差異並建立較有意義的過濾條件，建議做多、做空各自都累積贏與輸兩類樣本。

按「執行 AI 改善」後，系統會：

1. 分開分析做多與做空。
2. 搜尋可降低歷史輸單比例的數值門檻。
3. 依時間先後切分前段與後段資料驗證。
4. 只採用通過驗證的方向。
5. 沒有進步的方向完整沿用上一版。
6. 產生下一版 Pine，並由 PineTS 重新計算新訊號。

AI 改善只會替原始做多、做空訊號增加過濾條件，不會憑空創造原本不存在的多空訊號。

### 4. 檢查策略版本

在「策略版本」可以：

- 按 V1、V2、V3……順序切換。
- 查看實際人工標記勝率或 AI 歷史估計。
- 查看做多與做空各自沿用／新增的條件。
- 查看被排除的贏單與輸單數量。
- 複製完整 Pine 到 TradingView。
- 返回指定版本繼續標記。
- 刪除指定版本及其後續分支。

「實際」代表該版本已有人工作出贏／輸標記；「AI 回測估計」是根據舊資料推算，不能當成未來真實勝率。

### 5. 複製到 TradingView

1. 在「策略版本」選擇要使用的版本。
2. 展開「複製 Vn Pine 到 TradingView」。
3. 按程式碼框右上角的複製圖示。
4. 開啟 TradingView 的 Pine Editor。
5. 建立空白指標並貼上完整程式碼。
6. 儲存後按「新增至圖表」。

請確認 TradingView 的市場、交易對、週期及參數與 Indicator Lab 的研究設定一致。

## 刪除與重新開始

左側「刪除資料」提供三個層級：

- **刪除版本**：刪除選取版本及其後續版本，保留較早版本。
- **刪除策略**：刪除該策略所有版本、訊號與標記，保留市場 K 線。
- **刪除市場**：刪除該市場 K 線、策略、版本、訊號與人工標記。

刪除前必須勾選確認。重要資料請先自行備份。

## 本機資料位置

| 資料 | 位置 | 是否預設上傳 GitHub |
|---|---|---|
| SQLite 索引與標記 | `data/app.db` | 否 |
| Binance K 線 | `data/market/` | 否 |
| 人工標記快照 | `data/samples/` | 否 |
| AI 模型與評估 | `data/models/` | 否 |
| 改善版本資料 | `data/strategy_versions/` | 否 |
| 使用者 Pine | `indicators/` | 否 |
| 匯出檔 | `exports/` | 否 |

上述規則由 `.gitignore` 保護。每次推送 GitHub 前仍應檢查變更清單，確認沒有私人 Pine、K 線、標記或帳號憑證。

## 常見問題

### 雙擊啟動後沒有反應

先確認已完成「第一次安裝」。再查看專案根目錄的 `launcher.log`。也可以在 PowerShell 手動啟動，以便看到完整錯誤。

### 顯示找不到 `.venv`

代表尚未建立虛擬環境，重新執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### `http://localhost:8503` 打不開

確認啟動視窗仍開著。若 8503 已被其他程式使用，可改用其他連接埠：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8504
```

再開啟 `http://localhost:8504`。

### Pine 可以在 TradingView 執行，但 PineTS 執行失敗

PineTS 比原本的自製判斷器支援更多 Pine 語法，但不是 TradingView 私有引擎的完整複製。請先確認腳本使用 `indicator()`，並檢查是否依賴第三方函式庫、跨商品 `request.security()` 或 PineTS 尚未實作的功能。

### 建立 V1 後沒有訊號

請檢查：

- Pine 是否真的在相同交易對與週期產生訊號。
- PineTS 是否辨識到真正的做多與做空條件；特殊命名可在匯入頁手動指定。
- 指標參數是否與 TradingView 一致。

### PineTS 授權

PineTS 以 GNU AGPL v3 授權。固定版本與完整授權文字會在 `npm install` 後位於 `node_modules/pinets/`。公開或部署修改後的工具時，請一併遵守 PineTS 的 AGPL 授權條款。

### Binance 顯示 429 或下載變慢

代表短時間請求過多。先停止重複操作，稍後再試。不要同時開啟多個下載完整歷史行情的程序。

## 開發與測試

執行測試：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

檢查程式風格：

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

## 研究風險

Indicator Lab 的目標是找出歷史資料中常出現在輸單的特徵，並降低這類訊號比例。它不會保證：

- 未來勝率等於歷史勝率
- 策略一定獲利
- 不會發生過度擬合
- 不受市場結構改變影響
- 已包含手續費、滑價與成交問題

提高歷史勝率通常也會減少交易次數。正式使用前，應固定交易規則、保留完全未參與訓練的時間區段，並在模擬環境進行樣本外驗證。

