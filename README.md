# Indicator Lab

Indicator Lab 是一套本機量化研究工具，讓你把 TradingView Pine 指標匯入後，逐筆標記盈利、虧損或無效訊號，再用數值規則搜尋替做多與做空分別找出可用的過濾條件。

新版介面採用 React，後端採用 FastAPI；原本的 PineTS 執行、人工標記、AI 改善與版本資料都保留在 Python 核心。

## 主要流程

1. 匯入 Pine 指標，建立不可覆蓋的 V1。
2. 在 K 線圖上逐筆標記盈利、虧損或無效。
3. 查看做多、做空勝率與盈利／虧損特徵差異。
4. 按下「產生改善版本」，建立 V2、V3 等子版本。
5. 比較版本，直接複製完整 Pine 原始碼到 TradingView。

AI 不會取代你的原始做多、做空條件。改善版本只會在原始訊號後加入數值過濾；做多與做空分開搜尋，沒有改善的方向沿用上一版。

## Windows 一鍵啟動

直接雙擊：

```text
start_indicator_lab.bat
```

啟動器會：

- 確認 Python 與 Node.js。
- 首次使用時安裝 PineTS 與 React 套件。
- 建置 React 正式版介面。
- 啟動本機 FastAPI 服務。
- 開啟 `http://localhost:8503`。

所有行情、標記與策略版本都只保存在這台電腦，不會自動上傳。

## 第一次手動安裝

需要 Python 3.11 以上與 Node.js 20 以上。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

npm.cmd install --ignore-scripts --no-audit --no-fund

Set-Location frontend
npm.cmd install --ignore-scripts --no-audit --no-fund
npm.cmd run build
Set-Location ..

.\.venv\Scripts\python.exe -m uvicorn quant_labeler.api:app --host 127.0.0.1 --port 8503
```

瀏覽器開啟 `http://localhost:8503`。

## 開發前端

先啟動 Python API：

```powershell
.\.venv\Scripts\python.exe -m uvicorn quant_labeler.api:app --host 127.0.0.1 --port 8503
```

再開另一個終端：

```powershell
Set-Location frontend
npm.cmd run dev
```

開發介面位於 `http://localhost:5173`，API 會自動轉送到 8503。

## 資料位置

- `data/app.db`：市場、訊號與標記索引。
- `data/market/`：下載或匯入的 K 線。
- `data/samples/`：每筆人工標記的完整快照。
- `data/strategy_versions/`：AI 改善版本的規則與統計。
- `indicators/`：V1 與所有生成版本的 Pine 原始碼。
- `frontend/`：React 專業前端。
- `src/quant_labeler/api.py`：FastAPI 後端入口。

刪除市場、策略或版本時，系統會同時清理屬於該項目的本機訊號與檔案；V1 不會被版本刪除功能覆蓋。

## Pine 匯入說明

Indicator Lab 使用 PineTS 在本機執行 Pine 指標，再從原始碼中的做多、做空輸出辨識訊號。一般會依下列線索自動辨識：

- `longSignal`、`shortSignal`、`buySignal`、`sellSignal` 等布林變數。
- `plotshape()`、`plotchar()` 或 `alertcondition()` 使用的條件。
- 可直接指定做多與做空運算式的進階匯入欄位。

PineTS 與 TradingView 官方執行環境不是同一套引擎。若腳本使用尚未被 PineTS 支援的 TradingView 專屬功能，系統會顯示具體原因，不會偽造訊號。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pytest
Set-Location frontend
npm.cmd run build
```

## 技術架構

- React 18 + TypeScript + Vite
- Lightweight Charts
- FastAPI + Uvicorn
- Pandas + SQLite
- PineTS
- Scikit-learn 與數值規則搜尋

Indicator Lab 的正式介面與啟動流程統一採用 React＋FastAPI。
