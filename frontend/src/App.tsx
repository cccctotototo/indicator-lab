import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  BarChart3,
  Check,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  Database,
  FlaskConical,
  Import,
  Keyboard,
  Layers3,
  LoaderCircle,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { api } from "./api";
import { CandleChart } from "./CandleChart";
import type {
  AnalysisData,
  Dataset,
  Label,
  ReviewData,
  StrategySummary,
} from "./types";

type Page = "import" | "label" | "analysis" | "versions";

function readPageFromHash(): Page {
  const value = window.location.hash.replace("#", "") as Page;
  return ["import", "label", "analysis", "versions"].includes(value) ? value : "label";
}

/*
THESIS: Indicator Lab is a research ledger, not a generic AI dashboard.
OWN-WORLD: A dark evidence index frames a bright, precise research canvas.
STORY: Choose context, inspect the signal, record evidence, improve, compare.
FIRST VIEWPORT: Current workflow, market context, and the page's single primary action.
FORM: Restrained enterprise console—tight type hierarchy, mild radii, visible borders, brand red only for focus.
*/

const NAV: { id: Page; label: string; helper: string; icon: typeof Import }[] = [
  { id: "import", label: "匯入策略", helper: "建立 V1", icon: Import },
  { id: "label", label: "標記訊號", helper: "贏、輸、無效", icon: Check },
  { id: "analysis", label: "AI 改善", helper: "分析與產生新版", icon: Sparkles },
  { id: "versions", label: "策略版本", helper: "比較與複製 Pine", icon: Layers3 },
];

const labelName: Record<Exclude<Label, null>, string> = {
  win: "盈利",
  loss: "虧損",
  breakeven: "打平",
  invalid: "無效",
};

function formatRate(value: number | null | undefined) {
  return value == null ? "—" : `${value.toFixed(1)}%`;
}

function usePersistentNumber(key: string) {
  const [value, setValue] = useState<number | null>(() => {
    const stored = localStorage.getItem(key);
    return stored ? Number(stored) : null;
  });
  const save = (next: number | null) => {
    setValue(next);
    if (next == null) localStorage.removeItem(key);
    else localStorage.setItem(key, String(next));
  };
  return [value, save] as const;
}

function readCachedDatasets(): Dataset[] {
  try {
    const value = sessionStorage.getItem("indicator-lab.workspace");
    return value ? (JSON.parse(value) as Dataset[]) : [];
  } catch {
    return [];
  }
}

export default function App() {
  const [page, setPage] = useState<Page>(readPageFromHash);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [datasets, setDatasets] = useState<Dataset[]>(readCachedDatasets);
  const [datasetId, setDatasetId] = usePersistentNumber("indicator-lab.dataset");
  const [indicator, setIndicator] = useState(localStorage.getItem("indicator-lab.indicator") ?? "");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const shellRef = useRef<HTMLDivElement>(null);
  const topbarRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const sidebarOpenRef = useRef(sidebarOpen);
  const autoCollapsedRef = useRef(false);
  const reopenWidthRef = useRef(0);
  sidebarOpenRef.current = sidebarOpen;

  const refreshWorkspace = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const result = await api.workspace();
      setDatasets(result.datasets);
      sessionStorage.setItem("indicator-lab.workspace", JSON.stringify(result.datasets));
      const activeDataset =
        result.datasets.find((item) => item.id === datasetId) ?? result.datasets[0] ?? null;
      if (activeDataset && activeDataset.id !== datasetId) setDatasetId(activeDataset.id);
      if (activeDataset) {
        const available = activeDataset.strategies.some((item) => item.name === indicator);
        if (!available) {
          const next = activeDataset.strategies.at(-1)?.name ?? "";
          setIndicator(next);
          localStorage.setItem("indicator-lab.indicator", next);
        }
      }
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "無法讀取工作區。");
    } finally {
      setLoading(false);
    }
  }, [datasetId, indicator, setDatasetId]);

  useEffect(() => {
    void refreshWorkspace(datasets.length === 0);
    // Initial workspace hydration only. Later mutations call refresh explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    window.history.replaceState(null, "", `#${page}`);
  }, [page]);

  useEffect(() => {
    const shell = shellRef.current;
    const topbar = topbarRef.current;
    const main = mainRef.current;
    if (!shell || !topbar || !main) return;

    let frame = 0;
    const measureFit = () => {
      frame = 0;
      const shellWidth = Math.round(shell.getBoundingClientRect().width);
      if (sidebarOpenRef.current) {
        const layoutContainers = [
          topbar,
          ...main.querySelectorAll<HTMLElement>(
            [
              ".page-header",
              ".review-navigation",
              ".chart-toolbar",
              ".label-controls",
              ".label-details",
              ".import-workbench",
              ".metric-band",
              ".direction-summary",
              ".evidence-layout",
              ".version-hero",
              ".version-summary-band",
              ".direction-grid",
            ].join(","),
          ),
        ];
        const containerOverflow = layoutContainers.reduce(
          (largest, element) =>
            Math.max(largest, element.scrollWidth - element.clientWidth),
          0,
        );
        const overflow = Math.ceil(
          Math.max(
            0,
            containerOverflow,
            main.scrollWidth - main.clientWidth,
            document.documentElement.scrollWidth -
              document.documentElement.clientWidth,
          ),
        );
        if (overflow > 2) {
          autoCollapsedRef.current = true;
          reopenWidthRef.current = shellWidth + overflow + 24;
          sidebarOpenRef.current = false;
          setSidebarOpen(false);
        }
      } else if (
        autoCollapsedRef.current &&
        shellWidth >= reopenWidthRef.current
      ) {
        autoCollapsedRef.current = false;
        sidebarOpenRef.current = true;
        setSidebarOpen(true);
      }
    };
    const scheduleFitCheck = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(measureFit);
    };

    const sizeObserver = new ResizeObserver(scheduleFitCheck);
    sizeObserver.observe(shell);
    sizeObserver.observe(topbar);
    sizeObserver.observe(main);
    const contentObserver = new MutationObserver(scheduleFitCheck);
    contentObserver.observe(main, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    window.addEventListener("resize", scheduleFitCheck, { passive: true });
    scheduleFitCheck();

    return () => {
      window.cancelAnimationFrame(frame);
      sizeObserver.disconnect();
      contentObserver.disconnect();
      window.removeEventListener("resize", scheduleFitCheck);
    };
  }, []);

  const activeDataset = datasets.find((item) => item.id === datasetId) ?? null;
  const strategies = activeDataset?.strategies ?? [];
  const activeStrategy = strategies.find((item) => item.name === indicator) ?? null;

  const warmPage = useCallback((target: Page) => {
    if (!activeDataset || !activeStrategy) return;
    if (target === "analysis") {
      void api.analysis(activeDataset.id, activeStrategy.name).catch(() => undefined);
    }
    if (target === "versions") {
      void api.versions(activeDataset.id, activeStrategy.root).catch(() => undefined);
    }
  }, [activeDataset, activeStrategy]);

  useEffect(() => {
    if (!activeDataset || !activeStrategy) return;
    const timer = window.setTimeout(() => {
      warmPage("analysis");
      warmPage("versions");
    }, 900);
    return () => window.clearTimeout(timer);
  }, [activeDataset, activeStrategy, warmPage]);

  const selectDataset = (value: number) => {
    setDatasetId(value);
    const dataset = datasets.find((item) => item.id === value);
    const next = dataset?.strategies.at(-1)?.name ?? "";
    setIndicator(next);
    localStorage.setItem("indicator-lab.indicator", next);
  };
  const selectIndicator = (value: string) => {
    setIndicator(value);
    localStorage.setItem("indicator-lab.indicator", value);
  };
  const toggleSidebar = () => {
    autoCollapsedRef.current = false;
    reopenWidthRef.current = 0;
    setSidebarOpen((value) => {
      const next = !value;
      sidebarOpenRef.current = next;
      return next;
    });
  };

  return (
    <div
      ref={shellRef}
      className={`app-shell ${sidebarOpen ? "" : "sidebar-collapsed"}`}
    >
      <a className="skip-link" href="#main-content">跳到主要內容</a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">IL</span>
          <span className="brand-copy">
            <strong>Indicator Lab</strong>
            <small>匯入、標記、分析、改善</small>
          </span>
          <button
            className="icon-button sidebar-toggle"
            onClick={toggleSidebar}
            aria-label={sidebarOpen ? "收合側邊欄" : "展開側邊欄"}
            title={sidebarOpen ? "收合側邊欄" : "展開側邊欄"}
          >
            {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>
        </div>

        <nav className="workflow" aria-label="主要流程">
          <span className="eyebrow workflow-label">工作流程</span>
          {NAV.map((item, index) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={`nav-item ${page === item.id ? "active" : ""}`}
                onClick={() => setPage(item.id)}
                onPointerEnter={() => warmPage(item.id)}
                onFocus={() => warmPage(item.id)}
                aria-current={page === item.id ? "step" : undefined}
                title={!sidebarOpen ? `${item.label}：${item.helper}` : undefined}
              >
                <span className="step-number">{index + 1}</span>
                <Icon size={18} />
                <span className="nav-copy">
                  <strong>{item.label}</strong>
                  <small>{item.helper}</small>
                </span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-context">
          <span className="eyebrow">研究工作區</span>
          <label>
            市場資料
            <select
              value={activeDataset?.id ?? ""}
              onChange={(event) => selectDataset(Number(event.target.value))}
            >
              {!datasets.length && <option value="">尚未建立市場</option>}
              {datasets.map((dataset) => (
                <option value={dataset.id} key={dataset.id}>
                  {dataset.symbol} · {dataset.interval} ·{" "}
                  {dataset.market_type === "futures" ? "U 本位永續" : "現貨"}
                </option>
              ))}
            </select>
          </label>
          <label>
            策略版本
            <select
              value={indicator}
              onChange={(event) => selectIndicator(event.target.value)}
              disabled={!strategies.length}
            >
              {!strategies.length && <option value="">尚未匯入策略</option>}
              {strategies.map((strategy) => (
                <option value={strategy.name} key={strategy.name}>
                  V{strategy.version} · {strategy.name}
                </option>
              ))}
            </select>
          </label>
          {activeDataset && (
            <div className="dataset-note">
              <span>{activeDataset.row_count.toLocaleString()} 根 K 線</span>
              <span>
                {new Date(activeDataset.start_time).toLocaleDateString("zh-TW")} —{" "}
                {new Date(activeDataset.end_time).toLocaleDateString("zh-TW")}
              </span>
            </div>
          )}
        </div>
      </aside>

      <header ref={topbarRef} className="topbar">
        <div className="topbar-page">
          <span>步驟 {NAV.findIndex((item) => item.id === page) + 1}／4</span>
          <strong>{NAV.find((item) => item.id === page)?.label}</strong>
        </div>
        <span className="topbar-divider" aria-hidden="true" />
        <div className="context-title">
          <span>{activeDataset ? `${activeDataset.symbol} · ${activeDataset.interval}` : "尚未建立市場"}</span>
          <small>{indicator || "請先匯入策略"}</small>
        </div>
        <div className="topbar-status">
          <span className="status-dot" aria-hidden="true" />
          <span className="topbar-status-label">本機工作區</span>
        </div>
      </header>

      <main ref={mainRef} className="main-canvas" id="main-content" tabIndex={-1}>
        {loading && datasets.length === 0 ? (
          <LoadingState variant="workspace" />
        ) : error ? (
          <EmptyState title="工作區無法開啟" description={error} action={refreshWorkspace} />
        ) : page === "import" ? (
          <ImportPage datasets={datasets} selectedDatasetId={datasetId} onImported={async (name) => {
            await refreshWorkspace();
            setIndicator(name);
            localStorage.setItem("indicator-lab.indicator", name);
            setPage("label");
            setToast("策略已匯入，開始標記訊號。");
          }} />
        ) : !activeDataset || !activeStrategy ? (
          <EmptyState
            title="先建立第一個策略"
            description="匯入 Pine 指標後，系統會用 PineTS 產生可標記訊號。"
            action={() => setPage("import")}
            actionLabel="前往匯入策略"
          />
        ) : page === "label" ? (
          <LabelPage
            key={`${activeDataset.id}:${activeStrategy.name}`}
            dataset={activeDataset}
            strategy={activeStrategy}
            onSaved={(message) => {
              setToast(message);
              void refreshWorkspace();
            }}
          />
        ) : page === "analysis" ? (
          <AnalysisPage
            key={`${activeDataset.id}:${activeStrategy.name}`}
            dataset={activeDataset}
            strategy={activeStrategy}
            onImproved={async (name) => {
              await refreshWorkspace();
              setIndicator(name);
              localStorage.setItem("indicator-lab.indicator", name);
              setToast(`已建立 ${name}`);
              setPage("versions");
            }}
          />
        ) : (
          <VersionsPage
            key={`${activeDataset.id}:${activeStrategy.root}`}
            dataset={activeDataset}
            strategy={activeStrategy}
            onSelect={selectIndicator}
            onDeleted={async () => {
              await refreshWorkspace();
              setToast("版本已刪除。");
            }}
          />
        )}
      </main>
      {toast && <div className="toast"><Check size={17} />{toast}</div>}
    </div>
  );
}

function LoadingState({
  variant = "analysis",
}: {
  variant?: "workspace" | "import" | "label" | "analysis" | "versions";
}) {
  return (
    <div className={`page loading-buffer loading-${variant}`} aria-busy="true" aria-label="內容載入中">
      <div className="loading-progress" />
      <div className="loading-heading">
        <span className="skeleton-line short" />
        <span className="skeleton-line title" />
        <span className="skeleton-line copy" />
      </div>
      <div className="loading-metrics" aria-hidden="true">
        {[0, 1, 2, 3].map((item) => <span key={item} />)}
      </div>
      <div className="loading-content" aria-hidden="true">
        <span />
        <span />
      </div>
    </div>
  );
}

function OperationBuffer({
  title,
  detail,
  steps,
}: {
  title: string;
  detail: string;
  steps?: string[];
}) {
  return (
    <div className="operation-buffer" role="status" aria-live="polite">
      <LoaderCircle className="spin" size={17} />
      <span className="operation-copy">
        <strong>{title}</strong>
        <small>{detail}</small>
        {steps && (
          <span className="operation-steps">
            {steps.map((step, index) => (
              <span className={index === 0 ? "active" : ""} key={step}>
                <i>{index + 1}</i>{step}
              </span>
            ))}
          </span>
        )}
      </span>
    </div>
  );
}

function EmptyState({
  title,
  description,
  action,
  actionLabel = "重新載入",
}: {
  title: string;
  description: string;
  action: () => void | Promise<void>;
  actionLabel?: string;
}) {
  return (
    <section className="empty-state">
      <FlaskConical size={30} />
      <h1>{title}</h1>
      <p>{description}</p>
      <button className="button primary" onClick={() => void action()}>{actionLabel}</button>
    </section>
  );
}

function PageHeader({
  step,
  title,
  description,
  actions,
}: {
  step: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{step}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

function LabelPage({
  dataset,
  strategy,
  onSaved,
}: {
  dataset: Dataset;
  strategy: StrategySummary;
  onSaved: (message: string) => void;
}) {
  const initialReview = useRef(api.peekReview(dataset.id, strategy.name)).current;
  const [review, setReview] = useState<ReviewData | null>(initialReview);
  const [busy, setBusy] = useState(initialReview === null);
  const [message, setMessage] = useState("");
  const [notes, setNotes] = useState(initialReview?.selected.notes ?? "");
  const [barsHeld, setBarsHeld] = useState(initialReview?.selected.bars_held ?? 20);
  const prefetchedReviews = useRef(new Map<number, Promise<ReviewData>>());
  const readyReviews = useRef(new Map<number, ReviewData>());

  const queueNextReview = useCallback((result: ReviewData) => {
    const currentIndex = result.signals.findIndex(
      (signal) => signal.id === result.selected.id,
    );
    const next =
      result.signals.slice(currentIndex + 1).find((signal) => signal.label === null) ??
      result.signals[currentIndex + 1];
    if (next && !prefetchedReviews.current.has(next.id)) {
      const request = api.review(dataset.id, strategy.name, next.id).then((review) => {
        readyReviews.current.set(next.id, review);
        return review;
      });
      prefetchedReviews.current.set(next.id, request);
      void request.catch(() => {
        prefetchedReviews.current.delete(next.id);
        readyReviews.current.delete(next.id);
      });
    }
  }, [dataset.id, strategy.name]);

  const applyReview = useCallback((result: ReviewData) => {
    setReview(result);
    setNotes(result.selected.notes ?? "");
    setBarsHeld(result.selected.bars_held ?? 20);
    setMessage("");
    queueNextReview(result);
  }, [queueNextReview]);

  const load = useCallback(async (signalId?: number) => {
    if (!api.peekReview(dataset.id, strategy.name, signalId)) setBusy(true);
    try {
      const prefetched = signalId ? prefetchedReviews.current.get(signalId) : undefined;
      const result = await (
        prefetched ?? api.review(dataset.id, strategy.name, signalId)
      );
      if (signalId) {
        prefetchedReviews.current.delete(signalId);
        readyReviews.current.delete(signalId);
      }
      applyReview(result);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "無法載入訊號。");
    } finally {
      setBusy(false);
    }
  }, [applyReview, dataset.id, strategy.name]);

  useEffect(() => {
    prefetchedReviews.current.clear();
    readyReviews.current.clear();
    void load();
    return () => {
      prefetchedReviews.current.clear();
      readyReviews.current.clear();
    };
  }, [load]);

  const selectedIndex = review
    ? review.signals.findIndex((signal) => signal.id === review.selected.id)
    : -1;
  const go = (offset: number) => {
    if (!review) return;
    const next = review.signals[selectedIndex + offset];
    if (next) void load(next.id);
  };
  const save = async (label: Exclude<Label, null>) => {
    if (!review) return;
    const previousReview = review;
    let advancedOptimistically = false;
    let appliedReview: ReviewData | null = null;
    setBusy(true);
    try {
      const next =
        review.signals.slice(selectedIndex + 1).find((signal) => signal.label === null) ??
        review.signals[selectedIndex + 1] ??
        review.signals[selectedIndex];
      const nextReviewRequest =
        prefetchedReviews.current.get(next.id) ??
        api.review(dataset.id, strategy.name, next.id);
      const labelRequest = api.label(review.selected.id, label, {
        notes,
        bars_held: barsHeld,
        context_before: 60,
        context_after: 30,
      });
      const advance = (nextReview: ReviewData) => {
        const observedLabel =
          nextReview.signals.find((signal) => signal.id === review.selected.id)?.label ?? null;
        const signals = nextReview.signals.map((signal) =>
          signal.id === review.selected.id ? { ...signal, label } : signal,
        );
        const visibleSignals = nextReview.visible_signals.map((signal) =>
          signal.id === review.selected.id ? { ...signal, label } : signal,
        );
        const summary = { ...nextReview.summary };
        const countKey = (
          value: Label,
        ): "wins" | "losses" | "invalid" | null =>
          value === "win" ? "wins" : value === "loss" ? "losses" : value === "invalid" ? "invalid" : null;
        if (observedLabel !== label) {
          if (observedLabel === null) {
            summary.labeled += 1;
            summary.unlabeled = Math.max(0, summary.unlabeled - 1);
          } else {
            const priorKey = countKey(observedLabel);
            if (priorKey) summary[priorKey] = Math.max(0, summary[priorKey] - 1);
          }
          const nextKey = countKey(label);
          if (nextKey) summary[nextKey] += 1;
        }
        appliedReview = { ...nextReview, signals, visible_signals: visibleSignals, summary };
        applyReview(appliedReview);
      };
      const readyReview = readyReviews.current.get(next.id);
      if (readyReview) {
        advance(readyReview);
        advancedOptimistically = true;
        setBusy(false);
        await labelRequest;
      } else {
        const [, nextReview] = await Promise.all([labelRequest, nextReviewRequest]);
        advance(nextReview);
      }
      prefetchedReviews.current.delete(next.id);
      readyReviews.current.delete(next.id);
      if (appliedReview) api.primeReview(dataset.id, strategy.name, appliedReview);
      onSaved(`已標記為${labelName[label]}`);
      setBusy(false);
    } catch (reason) {
      if (advancedOptimistically) applyReview(previousReview);
      setMessage(reason instanceof Error ? reason.message : "標記儲存失敗。");
      setBusy(false);
    }
  };
  const undo = async () => {
    if (!review) return;
    setBusy(true);
    try {
      await api.undoLabel(review.selected.id);
      onSaved("已清除這筆標記");
      await load(review.selected.id);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "無法清除標記。");
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        busy ||
        event.repeat ||
        target?.matches("input, textarea, select, button, [contenteditable='true']")
      ) return;
      const key = event.key.toLowerCase();
      if (key === "w") void save("win");
      else if (key === "l") void save("loss");
      else if (key === "i") void save("invalid");
      else if (event.key === "ArrowLeft") go(-1);
      else if (event.key === "ArrowRight") go(1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // The handlers intentionally track the currently selected review and draft fields.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, review, selectedIndex, notes, barsHeld]);

  if (!review && busy) return <LoadingState variant="label" />;
  if (!review) {
    return <EmptyState title="沒有可標記訊號" description={message} action={() => load()} />;
  }

  const progress = review.summary.total
    ? (review.summary.labeled / review.summary.total) * 100
    : 0;

  return (
    <div className="page label-page">
      <PageHeader
        step="步驟 2／4 · 標記訊號"
        title={`標記 ${strategy.name}`}
        description="只判斷這次訊號結果；儲存後立即前往下一筆，所有標記都能返回修改。"
      />
      <section className={`review-strip ${busy ? "is-loading" : ""}`} aria-busy={busy}>
        {busy && <span className="panel-loading-bar" aria-hidden="true" />}
        <div className="progress-line">
          <span>
            已標記 {review.summary.labeled.toLocaleString()}／{review.summary.total.toLocaleString()}
          </span>
          <strong>{progress.toFixed(0)}%</strong>
          <i style={{ width: `${progress}%` }} />
        </div>
        <div className="review-navigation">
          <button className="button quiet" onClick={() => go(-1)} disabled={selectedIndex <= 0 || busy}>
            <ChevronLeft size={17} />上一筆
          </button>
          <div className="signal-identity" aria-label="目前選取的訊號">
            <span>
              #{review.selected.id} · {review.selected.direction === "long" ? "做多" : "做空"}
            </span>
            <small>
              {new Date(review.selected.timestamp).toLocaleString("zh-TW", { hour12: false })}
              {" · "}第 {selectedIndex + 1}／{review.summary.total} 筆
            </small>
          </div>
          <button
            className="button quiet"
            onClick={() => go(1)}
            disabled={selectedIndex >= review.signals.length - 1 || busy}
          >
            下一筆<ChevronRight size={17} />
          </button>
        </div>
      </section>

      <section className="chart-panel">
        <div className="chart-toolbar">
          <div className="legend">
            <span><i className="marker gray" />未標記</span>
            <span><i className="marker green" />盈利</span>
            <span><i className="marker red" />虧損</span>
            <span><i className="marker blue" />目前選取</span>
          </div>
          <span className="chart-help">拖曳平移 · 滾輪縮放 · 點擊訊號切換</span>
        </div>
        <CandleChart
          candles={review.candles}
          signals={review.visible_signals}
          selectedId={review.selected.id}
          onSelect={(id) => void load(id)}
        />
      </section>

      <section className="label-dock">
        <div className="label-controls">
          <button className="label-button win" onClick={() => void save("win")} disabled={busy}>
            <Check size={20} /><span><strong>盈利</strong><small>這筆訊號有效獲利</small></span><kbd>W</kbd>
          </button>
          <button className="label-button loss" onClick={() => void save("loss")} disabled={busy}>
            <X size={20} /><span><strong>虧損</strong><small>這筆訊號造成虧損</small></span><kbd>L</kbd>
          </button>
          <button className="label-button invalid" onClick={() => void save("invalid")} disabled={busy}>
            <Menu size={19} /><span><strong>無效</strong><small>不納入 AI 贏輸分析</small></span><kbd>I</kbd>
          </button>
        </div>
        <details className="advanced-settings">
          <summary><span><SlidersHorizontal size={16} />進階標記設定</span><small>持有 K 棒、備註與清除標記</small></summary>
          <div className="label-details">
            <label>持有 K 棒<input type="number" min={1} value={barsHeld} onChange={(e) => setBarsHeld(Number(e.target.value))} /></label>
            <label className="notes-field">備註<input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="選填：記下你的判斷" /></label>
            <button className="button quiet" onClick={() => void undo()} disabled={busy || !review.selected.label}>
              <RotateCcw size={16} />清除標記
            </button>
          </div>
        </details>
        <div className="keyboard-hint"><Keyboard size={14} />可使用 W、L、I 標記；方向鍵切換訊號</div>
        {message && <p className="inline-error">{message}</p>}
      </section>
    </div>
  );
}

function ImportPage({
  datasets,
  selectedDatasetId,
  onImported,
}: {
  datasets: Dataset[];
  selectedDatasetId: number | null;
  onImported: (name: string) => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [pine, setPine] = useState("");
  const [datasetId, setDatasetId] = useState<number | "new">(selectedDatasetId ?? "new");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("15m");
  const [marketType, setMarketType] = useState("futures");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const result = await api.importIndicator({
        strategy_name: name,
        pine_source: pine,
        dataset_id: datasetId === "new" ? null : datasetId,
        symbol,
        interval,
        market_type: marketType,
        timezone: "Asia/Taipei",
      });
      await onImported(String(result.indicator_name));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "匯入失敗。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page import-page">
      <PageHeader
        step="步驟 1／4 · 匯入策略"
        title="建立可標記的 V1"
        description="貼上可在 TradingView 執行的 Pine 指標。PineTS 會依原始訊號建立 V1，不改寫你的多空條件。"
      />
      {busy && (
        <OperationBuffer
          title="正在建立策略與訊號"
          detail="已保留你填寫的內容；完成後會直接前往標記頁。"
        />
      )}
      <form className="import-workbench" onSubmit={submit}>
        <section className="form-column">
          <h2>策略資料</h2>
          <label>策略名稱<input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 wickless_candle" required /></label>
          <label>
            使用市場
            <select value={datasetId} onChange={(e) => setDatasetId(e.target.value === "new" ? "new" : Number(e.target.value))}>
              <option value="new">建立新的 Binance 完整行情</option>
              {datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.symbol} · {dataset.interval} · {dataset.market_type}</option>)}
            </select>
          </label>
          {datasetId === "new" && (
            <div className="market-grid">
              <label>交易對<input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></label>
              <label>週期<select value={interval} onChange={(e) => setInterval(e.target.value)}>{["1m","3m","5m","15m","30m","1h","2h","4h","1d"].map((item) => <option key={item}>{item}</option>)}</select></label>
              <label>市場<select value={marketType} onChange={(e) => setMarketType(e.target.value)}><option value="futures">U 本位永續</option><option value="spot">現貨</option></select></label>
            </div>
          )}
          <div className="import-note"><ArrowDownToLine size={18} /><span><strong>新市場會同步完整歷史 K 線</strong><small>第一次建立可能需要較長時間；已有行情會直接重用。</small></span></div>
        </section>
        <section className="code-column">
          <div className="section-heading"><h2>Pine 原始碼</h2><span>{pine.length.toLocaleString()} 字</span></div>
          <textarea value={pine} onChange={(e) => setPine(e.target.value)} placeholder={"//@version=6\nindicator(\"我的指標\", overlay=true)\n\n// 貼上完整 Pine 原始碼"} required spellCheck={false} />
          {message && <p className="inline-error">{message}</p>}
          <button className="button primary import-submit" disabled={busy || !name.trim() || !pine.trim()}>
            {busy ? <LoaderCircle className="spin" size={18} /> : <Import size={18} />}
            {busy ? "正在執行 PineTS…" : "匯入並建立 V1"}
          </button>
        </section>
      </form>
    </div>
  );
}

function AnalysisPage({
  dataset,
  strategy,
  onImproved,
}: {
  dataset: Dataset;
  strategy: StrategySummary;
  onImproved: (name: string) => void | Promise<void>;
}) {
  const [analysis, setAnalysis] = useState<AnalysisData | null>(
    () => api.peekAnalysis(dataset.id, strategy.name),
  );
  const [busy, setBusy] = useState(() => analysis === null);
  const [improving, setImproving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!api.peekAnalysis(dataset.id, strategy.name)) setBusy(true);
    api.analysis(dataset.id, strategy.name)
      .then(setAnalysis)
      .catch((reason) => setMessage(reason.message))
      .finally(() => setBusy(false));
  }, [dataset.id, strategy.name]);

  const improve = async () => {
    setImproving(true);
    setMessage("");
    try {
      const result = await api.improve(dataset.id, strategy.name);
      await onImproved(String(result.child));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "目前無法產生新版。");
    } finally {
      setImproving(false);
    }
  };

  if (busy) return <LoadingState variant="analysis" />;
  if (!analysis) return <EmptyState title="無法分析這個版本" description={message} action={() => location.reload()} />;
  return (
    <div className="page analysis-page">
      <PageHeader
        step="步驟 3／4 · AI 改善"
        title={`分析 ${strategy.name}`}
        description="比較盈利與虧損特徵；做多、做空分開搜尋，沒有改善的方向沿用上一版。"
        actions={<button className="button primary" onClick={() => void improve()} disabled={improving || analysis.decisive < 1}>{improving ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{improving ? "正在搜尋規則…" : "產生改善版本"}</button>}
      />
      {improving && (
        <OperationBuffer
          title="正在比對盈利與虧損特徵"
          detail="目前分析內容會保留在畫面上，完成後自動建立下一版。"
          steps={["整理人工標記", "分方向搜尋數值規則", "驗證並建立版本"]}
        />
      )}
      <section className="metric-band">
        <Metric label="實際勝率" value={formatRate(analysis.overall.win_rate)} note={`${analysis.overall.wins} 勝／${analysis.overall.losses} 輸`} />
        <Metric label="有效標記" value={analysis.decisive.toLocaleString()} note={`未標記 ${analysis.remaining.toLocaleString()} 筆`} />
        <Metric label="做多" value={formatRate(analysis.directions.long.win_rate)} note={`${analysis.directions.long.samples} 筆`} />
        <Metric label="做空" value={formatRate(analysis.directions.short.win_rate)} note={`${analysis.directions.short.samples} 筆`} />
      </section>
      <section className="direction-summary-grid" aria-label="做多與做空分析摘要">
        {([
          ["long", "做多", TrendingUp, analysis.directions.long],
          ["short", "做空", TrendingDown, analysis.directions.short],
        ] as const).map(([key, label, Icon, stat]) => (
          <article className={`direction-summary ${key}`} key={key}>
            <div className="direction-icon"><Icon size={19} /></div>
            <div>
              <span>{label}證據</span>
              <strong>{formatRate(stat.win_rate)}</strong>
            </div>
            <dl>
              <div><dt>有效標記</dt><dd>{stat.samples.toLocaleString()}</dd></div>
              <div><dt>盈利</dt><dd>{stat.wins.toLocaleString()}</dd></div>
              <div><dt>虧損</dt><dd>{stat.losses.toLocaleString()}</dd></div>
            </dl>
          </article>
        ))}
      </section>
      {message && <p className="inline-error">{message}</p>}
      <div className="evidence-layout">
        <section className="evidence-table">
          <div className="section-heading"><div><span className="eyebrow">人工證據</span><h2>盈利與虧損的特徵差異</h2></div><span>{analysis.feature_comparison.length} 個可比較特徵</span></div>
          {analysis.feature_comparison.length ? (
            <table><thead><tr><th>特徵</th><th>盈利中位數</th><th>虧損中位數</th><th>差異強度</th></tr></thead>
            <tbody>{analysis.feature_comparison.map((row) => <tr key={row.feature}><td><strong>{row.name}</strong><small>{row.feature}</small></td><td>{row.win_median.toFixed(6)}</td><td>{row.loss_median.toFixed(6)}</td><td><span className="strength"><i style={{ width: `${Math.min(100, row.importance * 35)}%` }} /></span></td></tr>)}</tbody></table>
          ) : <div className="table-empty">只要有一筆人工結果就可以執行改善；同時有盈利與虧損時，特徵比較會更完整。</div>}
        </section>
        <aside className="evidence-inspector">
          <span className="eyebrow">規則原則</span><h2>版本只做一件事</h2>
          <p>盡量排除歷史虧損，同時保留盈利訊號。新條件不會取代你原始 Pine 的多空條件，只會加在後方當過濾器。</p>
          <dl><div><dt>訓練方法</dt><dd>數值規則搜尋</dd></div><div><dt>方向處理</dt><dd>做多、做空分開</dd></div><div><dt>資料門檻</dt><dd>1 筆即可執行</dd></div></dl>
        </aside>
      </div>
    </div>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

function VersionsPage({
  dataset,
  strategy,
  onSelect,
  onDeleted,
}: {
  dataset: Dataset;
  strategy: StrategySummary;
  onSelect: (name: string) => void;
  onDeleted: () => void | Promise<void>;
}) {
  const [versions, setVersions] = useState<StrategySummary[]>(
    () => api.peekVersions(dataset.id, strategy.root)?.versions ?? [],
  );
  const [selected, setSelected] = useState(strategy.name);
  const [busy, setBusy] = useState(() => versions.length === 0);
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState("");
  const current = versions.find((item) => item.name === selected) ?? versions.at(-1);

  const load = useCallback(async () => {
    if (!api.peekVersions(dataset.id, strategy.root)) setBusy(true);
    try {
      const result = await api.versions(dataset.id, strategy.root);
      setVersions(result.versions);
      if (!result.versions.some((item) => item.name === selected)) setSelected(result.versions.at(-1)?.name ?? "");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "版本載入失敗。");
    } finally {
      setBusy(false);
    }
  }, [dataset.id, strategy.root, selected]);
  useEffect(() => { void load(); }, [dataset.id, strategy.root]); // eslint-disable-line react-hooks/exhaustive-deps

  const copyPine = async () => {
    if (!current) return;
    try {
      await navigator.clipboard.writeText(await api.pine(current.name));
      setMessage("Pine 原始碼已複製，可直接貼到 TradingView。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "複製失敗。");
    }
  };
  const remove = async () => {
    if (!current || current.version === 1) return;
    if (!confirm(`確定刪除 ${current.name} 與所有後續版本？`)) return;
    setDeleting(true);
    try {
      await api.removeVersion(dataset.id, current.name);
      await load();
      await onDeleted();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "刪除失敗。");
    } finally {
      setDeleting(false);
    }
  };

  if (busy && !versions.length) return <LoadingState variant="versions" />;
  if (!current) return <EmptyState title="沒有策略版本" description={message} action={load} />;
  const metadata = current.metadata as {
    rule_text?: string;
    improved_directions?: string[];
    removed_losses?: number;
    removed_wins?: number;
    direction_results?: Record<string, { rule_text?: string; rules?: unknown[] }>;
  } | null;
  return (
    <div className="page versions-page">
      <PageHeader
        step="步驟 4／4 · 策略版本"
        title="比較與管理版本"
        description="每一版保留自己的 Pine 與人工結果；依版本順序查看，不覆蓋上一版。"
        actions={<><button className="button quiet" onClick={() => void copyPine()} disabled={deleting}><Clipboard size={17} />複製到 TradingView</button>{current.version > 1 && <button className="button danger-quiet" onClick={() => void remove()} disabled={deleting}><Trash2 size={17} />刪除這版</button>}</>}
      />
      {deleting && (
        <OperationBuffer
          title="正在整理策略版本"
          detail="完成前保留目前內容，避免畫面突然變空。"
        />
      )}
      <div className="version-tabs" role="tablist">
        {versions.map((version) => <button key={version.name} role="tab" aria-selected={version.name === current.name} className={version.name === current.name ? "active" : ""} onClick={() => setSelected(version.name)}><strong>V{version.version}</strong><span>{formatRate(version.win_rate)}</span><small>{version.labeled.toLocaleString()} 筆標記</small></button>)}
      </div>
      {message && <p className={message.includes("已複製") ? "inline-success" : "inline-error"}>{message}</p>}
      <section className="version-hero">
        <div><span className="eyebrow">V{current.version} · {current.version === 1 ? "原始策略" : "AI 改善版本"}</span><h1>{current.name}</h1><p>{metadata?.rule_text ?? "你的原始多空條件，沒有套用 AI 過濾。"}</p></div>
        <div className="hero-rate"><span>綜合實際</span><strong>{formatRate(current.win_rate)}</strong><small>{current.wins} 勝／{current.losses} 輸</small></div>
      </section>
      <section className="version-summary-band" aria-label="版本標記摘要">
        <div className="version-stat primary-stat"><Database size={18} /><span><small>總共已標記</small><strong>{current.labeled.toLocaleString()} 筆</strong></span></div>
        <div className="version-stat"><Check size={18} /><span><small>盈利</small><strong>{current.wins.toLocaleString()}</strong></span></div>
        <div className="version-stat"><X size={18} /><span><small>虧損</small><strong>{current.losses.toLocaleString()}</strong></span></div>
        <div className="version-stat"><Activity size={18} /><span><small>無效</small><strong>{current.invalid.toLocaleString()}</strong></span></div>
      </section>
      <div className="direction-grid">
        {(["long", "short"] as const).map((direction) => {
          const count = direction === "long" ? current.long : current.short;
          const rules = metadata?.direction_results?.[direction]?.rules ?? [];
          return <section className="direction-panel" key={direction}><div className="section-heading"><div><span className="eyebrow">{direction === "long" ? "↑ 做多" : "↓ 做空"}</span><h2>{rules.length ? "本版 AI 改善" : current.version === 1 ? "原始訊號" : "完整沿用上一版"}</h2></div><strong>{count} 筆訊號</strong></div><div className="rule-copy">{metadata?.direction_results?.[direction]?.rule_text ?? "沒有新增過濾條件。"}</div></section>;
        })}
      </div>
      <button className="button primary use-version" onClick={() => onSelect(current.name)}><BarChart3 size={18} />使用 V{current.version} 前往標記</button>
    </div>
  );
}
