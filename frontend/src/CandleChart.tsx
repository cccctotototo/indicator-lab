import { useEffect, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, Signal } from "./types";

interface Props {
  candles: Candle[];
  signals: Signal[];
  selectedId: number;
  onSelect: (signalId: number) => void;
}

interface MarkerPosition {
  signal: Signal;
  x: number;
  y: number;
  color: string;
  selected: boolean;
}

const markerColor = (signal: Signal, selectedId: number) => {
  if (signal.id === selectedId) return "#2563eb";
  if (signal.label === "win") return "#138a72";
  if (signal.label === "loss") return "#d24b39";
  if (signal.label === "invalid" || signal.label === "breakeven") return "#8b8688";
  return "#777174";
};

const toTime = (value: string) =>
  Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;

export function CandleChart({ candles, signals, selectedId, onSelect }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [markerPositions, setMarkerPositions] = useState<MarkerPosition[]>([]);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = createChart(hostRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#706b6d",
        fontFamily: '"Inter", "Noto Sans TC", system-ui, sans-serif',
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
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series || !candles.length) return;
    series.setData(
      candles.map((candle) => ({
        time: toTime(candle.timestamp),
        open: Number(candle.open),
        high: Number(candle.high),
        low: Number(candle.low),
        close: Number(candle.close),
      })),
    );
    series.setMarkers([]);
    chart.timeScale().fitContent();

    const candlesByTime = new Map(
      candles.map((candle) => [Number(toTime(candle.timestamp)), candle]),
    );
    let animationFrame = 0;
    const updateMarkerPositions = () => {
      const positions = signals.flatMap<MarkerPosition>((signal) => {
        const time = toTime(signal.timestamp);
        const candle = candlesByTime.get(Number(time));
        if (!candle) return [];
        const x = chart.timeScale().timeToCoordinate(time);
        const price = signal.direction === "long" ? Number(candle.low) : Number(candle.high);
        const y = series.priceToCoordinate(price);
        if (x === null || y === null) return [];
        return [{
          signal,
          x,
          y,
          color: markerColor(signal, selectedId),
          selected: signal.id === selectedId,
        }];
      });
      setMarkerPositions(positions);
    };
    const scheduleMarkerUpdate = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(updateMarkerPositions);
    };
    const resizeObserver = new ResizeObserver(scheduleMarkerUpdate);
    if (hostRef.current) resizeObserver.observe(hostRef.current);
    chart.timeScale().subscribeVisibleLogicalRangeChange(scheduleMarkerUpdate);
    scheduleMarkerUpdate();

    const handler = (param: { time?: unknown }) => {
      if (typeof param.time !== "number") return;
      const clickedTime = param.time;
      const nearest = signals.reduce<{ id: number; delta: number } | null>((best, signal) => {
        const delta = Math.abs(Number(toTime(signal.timestamp)) - clickedTime);
        return best === null || delta < best.delta ? { id: signal.id, delta } : best;
      }, null);
      if (nearest && nearest.delta <= 60 * 60 * 24) onSelectRef.current(nearest.id);
    };
    chart.subscribeClick(handler);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(scheduleMarkerUpdate);
      chart.unsubscribeClick(handler);
    };
  }, [candles, signals, selectedId]);

  return (
    <div className="chart-stage">
      <div ref={hostRef} className="chart-host" aria-label="K 線與訊號圖表" />
      <div className="chart-signal-layer" aria-label="圖表訊號">
        {markerPositions.map(({ signal, x, y, color, selected }) => (
          <button
            key={signal.id}
            type="button"
            className={[
              "chart-signal-triangle",
              signal.direction === "long" ? "up" : "down",
              selected ? "selected" : "",
            ].join(" ")}
            style={{ left: x, top: y, color }}
            aria-label={`${signal.direction === "long" ? "做多" : "做空"}訊號 ${
              signal.label ? `，${signal.label}` : "，未標記"
            }`}
            title={`${signal.direction === "long" ? "做多" : "做空"} · ${
              signal.label ?? "未標記"
            }`}
            onClick={(event) => {
              event.stopPropagation();
              onSelectRef.current(signal.id);
            }}
          />
        ))}
      </div>
    </div>
  );
}
