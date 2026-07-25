import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesPrimitive,
  type ISeriesPrimitivePaneRenderer,
  type ISeriesPrimitivePaneView,
  type ISeriesApi,
  type PrimitiveHoveredItem,
  type SeriesAttachedParameter,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type { Candle, Signal } from "./types";

interface Props {
  candles: Candle[];
  signals: Signal[];
  selectedId: number;
  onSelect: (signalId: number) => void;
}

const markerColor = (signal: Signal, selectedId: number) => {
  if (signal.id === selectedId) return "#2563eb";
  if (signal.label === "win") return "#137a68";
  if (signal.label === "loss") return "#c44737";
  if (signal.label === "invalid" || signal.label === "breakeven") return "#7b808a";
  return "#7b808a";
};

const toTime = (value: string) =>
  Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;

interface TriangleMarker {
  signalId: number;
  time: UTCTimestamp;
  anchorPrice: number;
  direction: "long" | "short";
  color: string;
  selected: boolean;
}

interface TrianglePoint extends Omit<TriangleMarker, "time" | "anchorPrice"> {
  x: number;
  y: number;
}

class TriangleRenderer implements ISeriesPrimitivePaneRenderer {
  constructor(private readonly points: () => readonly TrianglePoint[]) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useBitmapCoordinateSpace(
      ({ context, horizontalPixelRatio, verticalPixelRatio }) => {
        const tickWidth = Math.max(1, Math.floor(horizontalPixelRatio));
        const xCorrection = (tickWidth % 2) / 2;

        for (const point of this.points()) {
          const halfWidth = (point.selected ? 7 : 6) * horizontalPixelRatio;
          const height = (point.selected ? 11 : 9) * verticalPixelRatio;
          const gap = 3 * verticalPixelRatio;
          const x =
            Math.round(point.x * horizontalPixelRatio) + xCorrection;
          const anchorY = Math.round(point.y * verticalPixelRatio);

          context.beginPath();
          if (point.direction === "long") {
            const tipY = anchorY + gap;
            context.moveTo(x, tipY);
            context.lineTo(x - halfWidth, tipY + height);
            context.lineTo(x + halfWidth, tipY + height);
          } else {
            const tipY = anchorY - gap;
            context.moveTo(x, tipY);
            context.lineTo(x - halfWidth, tipY - height);
            context.lineTo(x + halfWidth, tipY - height);
          }
          context.closePath();
          context.fillStyle = point.color;
          context.fill();
        }
      },
    );
  }
}

class TrianglePaneView implements ISeriesPrimitivePaneView {
  private readonly paneRenderer: TriangleRenderer;

  constructor(points: () => readonly TrianglePoint[]) {
    this.paneRenderer = new TriangleRenderer(points);
  }

  zOrder() {
    return "top" as const;
  }

  renderer(): ISeriesPrimitivePaneRenderer {
    return this.paneRenderer;
  }
}

class SignalTrianglePrimitive implements ISeriesPrimitive<Time> {
  private attachedParam: SeriesAttachedParameter<Time> | null = null;
  private markers: TriangleMarker[] = [];
  private points: TrianglePoint[] = [];
  private readonly views = [new TrianglePaneView(() => this.points)];

  attached(param: SeriesAttachedParameter<Time>): void {
    this.attachedParam = param;
    this.updateAllViews();
  }

  detached(): void {
    this.attachedParam = null;
    this.points = [];
  }

  setMarkers(markers: TriangleMarker[]): void {
    this.markers = markers;
    this.updateAllViews();
    this.attachedParam?.requestUpdate();
  }

  updateAllViews(): void {
    if (!this.attachedParam) return;
    const { chart, series } = this.attachedParam;
    const timeScale = chart.timeScale();
    const visibleRange = timeScale.getVisibleRange();

    this.points = this.markers.flatMap((marker) => {
      if (
        visibleRange &&
        typeof visibleRange.from === "number" &&
        typeof visibleRange.to === "number" &&
        (marker.time < visibleRange.from || marker.time > visibleRange.to)
      ) {
        return [];
      }
      const x = timeScale.timeToCoordinate(marker.time);
      const y = series.priceToCoordinate(marker.anchorPrice);
      if (x === null || y === null) return [];
      return [{ ...marker, x: Number(x), y: Number(y) }];
    });
  }

  paneViews(): readonly ISeriesPrimitivePaneView[] {
    return this.views;
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    for (let index = this.points.length - 1; index >= 0; index -= 1) {
      const point = this.points[index];
      const centerY = point.y + (point.direction === "long" ? 9 : -9);
      if (Math.abs(x - point.x) <= 10 && Math.abs(y - centerY) <= 12) {
        return {
          externalId: `signal:${point.signalId}`,
          zOrder: "top",
          cursorStyle: "pointer",
        };
      }
    }
    return null;
  }
}

export function CandleChart({ candles, signals, selectedId, onSelect }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const trianglePrimitiveRef = useRef<SignalTrianglePrimitive | null>(null);
  const onSelectRef = useRef(onSelect);
  const signalsRef = useRef(signals);
  onSelectRef.current = onSelect;
  signalsRef.current = signals;

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = createChart(hostRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#706b6d",
        fontFamily: '"Segoe UI", "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif',
        fontSize: 12,
      },
      grid: {
        vertLines: { color: "#f1efed" },
        horzLines: { color: "#ece9e7" },
      },
      rightPriceScale: { borderColor: "#e3dfdc", minimumWidth: 72 },
      timeScale: {
        borderColor: "#e3dfdc",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 9,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#9a9497", width: 1, style: 2, labelBackgroundColor: "#272326" },
        horzLine: { color: "#9a9497", width: 1, style: 2, labelBackgroundColor: "#272326" },
      },
      handleScroll: true,
      handleScale: true,
    });
    const series = chart.addCandlestickSeries({
      upColor: "#138a72",
      downColor: "#d24b39",
      wickUpColor: "#138a72",
      wickDownColor: "#d24b39",
      borderVisible: false,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    const trianglePrimitive = new SignalTrianglePrimitive();
    series.attachPrimitive(trianglePrimitive);
    chartRef.current = chart;
    seriesRef.current = series;
    trianglePrimitiveRef.current = trianglePrimitive;
    const clickHandler = (param: { time?: unknown; hoveredObjectId?: unknown }) => {
      if (
        typeof param.hoveredObjectId === "string" &&
        param.hoveredObjectId.startsWith("signal:")
      ) {
        const signalId = Number(param.hoveredObjectId.slice("signal:".length));
        if (Number.isFinite(signalId)) onSelectRef.current(signalId);
        return;
      }
      if (typeof param.time !== "number") return;
      const clickedTime = param.time;
      const nearest = signalsRef.current.reduce<{ id: number; delta: number } | null>(
        (best, signal) => {
          const delta = Math.abs(Number(toTime(signal.timestamp)) - clickedTime);
          return best === null || delta < best.delta ? { id: signal.id, delta } : best;
        },
        null,
      );
      if (nearest && nearest.delta <= 60 * 60 * 24) {
        onSelectRef.current(nearest.id);
      }
    };
    chart.subscribeClick(clickHandler);
    return () => {
      chart.unsubscribeClick(clickHandler);
      series.detachPrimitive(trianglePrimitive);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      trianglePrimitiveRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    if (!candles.length) {
      series.setData([]);
      return;
    }
    series.setData(
      candles.map((candle) => ({
        time: toTime(candle.timestamp),
        open: Number(candle.open),
        high: Number(candle.high),
        low: Number(candle.low),
        close: Number(candle.close),
      })),
    );
    chart.timeScale().fitContent();
  }, [candles]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const candlesByTime = new Map(
      candles.map((candle) => [Number(toTime(candle.timestamp)), candle]),
    );
    trianglePrimitiveRef.current?.setMarkers(
      [...signals]
        .sort(
          (left, right) =>
            Number(toTime(left.timestamp)) - Number(toTime(right.timestamp)),
        )
        .flatMap((signal) => {
          const time = toTime(signal.timestamp);
          const candle = candlesByTime.get(Number(time));
          if (!candle) return [];
          return [
            {
              signalId: signal.id,
              time,
              anchorPrice:
                signal.direction === "long"
                  ? Number(candle.low)
                  : Number(candle.high),
              direction: signal.direction,
              color: markerColor(signal, selectedId),
              selected: signal.id === selectedId,
            },
          ];
        }),
    );
  }, [candles, signals, selectedId]);

  const selectedSignal = signals.find((signal) => signal.id === selectedId);
  return (
    <div className="chart-stage">
      <p className="sr-only" id="chart-summary">
        K 線圖共顯示 {candles.length} 根 K 線與 {signals.length} 個訊號。
        {selectedSignal
          ? `目前選取${selectedSignal.direction === "long" ? "做多" : "做空"}訊號，時間 ${new Date(selectedSignal.timestamp).toLocaleString("zh-TW", { hour12: false })}。`
          : "目前沒有選取訊號。"}
        可使用頁面上的上一筆、下一筆按鈕或方向鍵切換訊號。
      </p>
      <div
        ref={hostRef}
        className="chart-host"
        role="img"
        tabIndex={0}
        aria-label="K 線與訊號圖表"
        aria-describedby="chart-summary"
      />
    </div>
  );
}
