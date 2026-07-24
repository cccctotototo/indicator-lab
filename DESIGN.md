---
name: Indicator Lab
description: 可追溯的指標訊號標註、贏輸分析與半監督式學習工作台
colors:
  signal-red: "oklch(0.57 0.18 14)"
  signal-red-deep: "oklch(0.43 0.14 14)"
  canvas: "oklch(1 0 0)"
  work-surface: "oklch(0.975 0.004 14)"
  ink: "oklch(0.20 0.012 14)"
  muted-ink: "oklch(0.47 0.018 14)"
  rule: "oklch(0.89 0.008 14)"
  profit: "oklch(0.55 0.14 165)"
  profit-soft: "oklch(0.97 0.02 165)"
  profit-border: "oklch(0.84 0.04 165)"
  profit-ink: "oklch(0.35 0.09 165)"
  loss: "oklch(0.58 0.19 25)"
  loss-soft: "oklch(0.97 0.025 25)"
  loss-border: "oklch(0.84 0.07 25)"
  loss-ink: "oklch(0.42 0.14 25)"
  info: "oklch(0.52 0.12 245)"
  info-soft: "oklch(0.97 0.018 245)"
  info-border: "oklch(0.88 0.035 245)"
  info-ink: "oklch(0.34 0.08 245)"
typography:
  headline:
    fontFamily: "Inter, Noto Sans TC, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Inter, Noto Sans TC, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Inter, Noto Sans TC, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.35
rounded:
  sm: "6px"
  md: "10px"
  lg: "14px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.signal-red}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.sm}"
    padding: "10px 16px"
  panel:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "16px"
---

# Design System: Indicator Lab

## Overview

**Creative North Star: "The Annotated Research Desk"**

這是一張白天使用的研究桌：乾淨白底讓 K 線與資料保有最高辨識度，深墨文字提供長時間閱讀的穩定感，帶酒紅的品牌色只標示目前焦點與主要動作。介面密度接近專業分析工具，但每個區塊都有清楚任務，不以裝飾製造專業感。

**Key Characteristics:**

- 研究優先、證據可追溯、結論克制。
- 大型圖表居中，控制項沿任務順序排列。
- 語意色固定：青綠為獲利、橙紅為虧損、藍為資訊。
- 狀態變化快速且安靜，不使用進場動畫。

## Colors

採 restrained 策略：純白畫布、略帶品牌色相的中性色，以及少量高辨識語意色。

### Primary

- **Signal Red**：只用於品牌焦點、目前訊號與主要提交動作；不可用於大面積背景。

### Secondary

- **Profit Teal**：僅表示獲利或正向結果，必須搭配文字。
- **Loss Vermilion**：僅表示虧損、錯誤與破壞性動作，必須搭配文字。
- **Evidence Blue**：資訊提示、模型證據與連結。

### Neutral

- **Canvas White**：主畫布。
- **Work Surface**：側欄、工具列與分組背景。
- **Research Ink**：主要文字。
- **Rule**：細邊界與分隔。

**The Semantic Color Rule.** 紅綠不得單獨承擔意義；每個狀態都必須有文字或符號。

## Typography

**Display Font:** Inter（Noto Sans TC 與 system-ui 後備）  
**Body Font:** Inter（Noto Sans TC 與 system-ui 後備）

**Character:** 單一無襯線字族維持分析工具的一致性；數字啟用等寬數字特性，繁體中文保持正常字距。

### Hierarchy

- **Headline**（700、24px、1.25）：頁面任務名稱。
- **Title**（650、17px、1.35）：區段與圖表標題。
- **Body**（400、15px、1.55）：說明、表格與操作內容。
- **Label**（600、13px、1.35）：欄位、狀態與輔助資訊，不強制大寫。

**The Numbers Stay Still Rule.** 所有價格、百分比與時間欄位使用 tabular-nums，更新時不造成水平跳動。

## Elevation

系統預設扁平，以色調層次與 1px 邊界區分結構。陰影只用於浮動提示與需要脫離頁面的選單，不把每個內容區塊做成漂浮卡片。

**The Flat-by-Default Rule.** 靜止內容沒有陰影；如果所有區塊都浮起來，就沒有任何區塊真正重要。

## Components

### Buttons

- **Shape:** 緊湊圓角（6px），高度至少 40px。
- **Primary:** Signal Red 白字，專用於載入、保存與訓練等主要動作。
- **Hover / Focus:** 明度降低；焦點使用 2px Evidence Blue 外框。
- **Secondary:** 白底 Research Ink，1px Rule 邊界。

### Chips

- **Style:** 輕色語意背景、深色文字、完整狀態名稱。
- **State:** 目前篩選器使用細品牌色外框，不使用大面積填色。

### Cards / Containers

- **Corner Style:** 10px。
- **Background:** Canvas White 或 Work Surface。
- **Shadow Strategy:** 無陰影；以邊界與間距建立層次。
- **Border:** 1px Rule。
- **Internal Padding:** 16px 或 24px。

### Inputs / Fields

- **Style:** 白底、1px Rule、6px 圓角，高度至少 40px。
- **Focus:** Evidence Blue 2px 外框。
- **Error / Disabled:** 清楚文字說明，禁用狀態仍維持可讀對比。

### Navigation

側欄依工作流排序，使用 Streamlit 原生圓形單選元件；啟用項目只使用品牌色圓點與較粗文字，不增加白底方框。主內容上方保留四步工作流，協助辨識目前進度。窄螢幕時使用 Streamlit 原生收合，不建立自訂抽屜。

### Signal Review Stage

K 線圖是最大視覺物件；上方依序顯示上一筆、目前訊號摘要、下一筆。方向、時間、序號與目前標記必須同時可讀；下方保留「贏」、「輸」、「無效」三個清楚決策。

### Strategy Versions

版本頁採 master-detail：上方選擇 V1、V2…，下方一次只顯示一個版本。選中版本仍須完整列出做多與做空的實際結果、全部有效過濾值、規則來源與後段驗證；Pine 與刪除操作使用漸進揭露，避免所有版本同時展開造成資訊噪音。

## Do's and Don'ts

### Do:

- **Do** 先顯示樣本數、資料範圍與來源，再顯示模型結論。
- **Do** 讓每個標註能回到訊號周邊 K 線與完整特徵快照。
- **Do** 將贏與輸同時用文字和顏色表示。
- **Do** 在桌面與 768px 寬度檢查圖表、表格及按鈕。

### Don't:

- **Don't** 做成「充滿霓虹、閃爍報價與過度密集資訊的賭場式交易終端」。
- **Don't** 做成「只有漂亮卡片卻沒有資料可追溯性的泛用 AI 儀表板」。
- **Don't** 使用玻璃擬態、紫色漸層、漸層文字或裝飾性動畫。
- **Don't** 把預測機率包裝成保證獲利。
- **Don't** 使用超過 1px 的側邊彩色條作為卡片裝飾。
