import React, { useEffect, useMemo, useRef } from "react";
import { Button, Input } from "antd";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import {
  NormalizedCurveSeries,
  buildCumulativeChartOption,
  buildNormalizedCurveSeries,
  curveColorForKey,
  curveSeriesColor,
  formatReturnPct,
  rowDate
} from "../app/shared";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  CanvasRenderer
]);

export function CurveChart({ rows, height = 340, showLegend = true }: { rows: any[]; height?: number; showLegend?: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const series = useMemo(() => buildNormalizedCurveSeries(rows), [rows]);
  const dates = useMemo(() => rows.map(rowDate), [rows]);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(buildCumulativeChartOption(series, dates), true);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [dates, series]);
  return (
    <div className="curve-chart-shell">
      <div className="curve-chart-heading">
        <div><strong>单位仓位累计收益</strong><span>固定数量 · 非复利</span></div>
        <span>下方展示策略与 B&amp;H 回撤</span>
      </div>
      <div ref={ref} className="curve-canvas" style={{ height }} />
      {showLegend && series.length > 0 && (
        <div className="curve-legend">
          {series.map((item, index) => (
            <div className={`curve-series-card ${item.totalReturn >= 0 ? "positive" : "negative"}`} key={item.key}>
              <div className="curve-series-head">
                <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} style={item.type === "benchmark" ? { borderLeftColor: curveSeriesColor(item, index) } : { background: curveSeriesColor(item, index) }} />
                <strong>{item.label}</strong>
              </div>
              <div className="curve-series-metrics">
                <span>累计 {formatReturnPct(item.totalReturn, 2)}</span>
                <span>回撤 {formatReturnPct(item.maxDrawdown, 2)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function buildComparisonSeries(
  curves: Record<string, any[]>,
  visibleKeys: string[],
  labels: Record<string, string> = {},
  benchmark?: NormalizedCurveSeries | null
): NormalizedCurveSeries[] {
  const series: NormalizedCurveSeries[] = [];
  const variantKeys = visibleKeys.filter((key) => key !== "buy_hold");
  for (const variantName of variantKeys) {
    const strategySeries = buildNormalizedCurveSeries(curves[variantName] || []).find((item) => item.key === "strategy");
    if (strategySeries) {
      series.push({
        ...strategySeries,
        key: `variant:${variantName}`,
        label: labels[variantName] || variantName
      });
    }
  }

  if (visibleKeys.includes("buy_hold")) {
    if (benchmark) {
      series.push(benchmark);
    } else {
      const benchmarkSource = curves.baseline || curves[variantKeys[0]] || Object.values(curves)[0] || [];
      const generatedBenchmark = buildNormalizedCurveSeries(benchmarkSource).find((item) => item.key === "buy_hold");
      if (generatedBenchmark) series.push(generatedBenchmark);
    }
  }

  return series;
}

const EMPTY_CURVE_LABELS: Record<string, string> = {};
const EMPTY_ORDERED_CURVE_KEYS: string[] = [];

function MultiVariantCurveChartComponent({
  curves,
  visibleKeys,
  labels = EMPTY_CURVE_LABELS,
  benchmark = null,
  orderedKeys = EMPTY_ORDERED_CURVE_KEYS,
  height = 340,
  showLegend = true
}: {
  curves: Record<string, any[]>;
  visibleKeys: string[];
  labels?: Record<string, string>;
  benchmark?: NormalizedCurveSeries | null;
  orderedKeys?: string[];
  height?: number;
  showLegend?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const series = useMemo(() => buildComparisonSeries(curves, visibleKeys, labels, benchmark), [curves, visibleKeys, labels, benchmark]);
  const dates = useMemo(() => {
    const seen = new Set<string>();
    for (const item of series) {
      for (const point of item.points) {
        if (point.date) seen.add(point.date);
      }
    }
    return Array.from(seen).sort();
  }, [series]);
  const option = useMemo(() => buildCumulativeChartOption(series, dates, orderedKeys), [dates, orderedKeys, series]);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  return (
    <div className="curve-chart-shell">
      <div className="curve-chart-heading">
        <div><strong>单位仓位累计收益</strong><span>固定数量 · 非复利</span></div>
        <span>下方展示策略与 B&amp;H 回撤</span>
      </div>
      <div ref={ref} className="curve-canvas" style={{ height }} />
      {showLegend && series.length > 0 && (
        <div className="curve-legend">
          {series.map((item, index) => (
            <div className={`curve-series-card ${item.totalReturn >= 0 ? "positive" : "negative"}`} key={item.key}>
              <div className="curve-series-head">
                <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} style={item.type === "benchmark" ? { borderLeftColor: curveColorForKey(item.key, item.label, item.type, orderedKeys, index) } : { background: curveColorForKey(item.key, item.label, item.type, orderedKeys, index) }} />
                <strong>{item.label}</strong>
              </div>
              <div className="curve-series-metrics">
                <span>累计 {formatReturnPct(item.totalReturn, 2)}</span>
                <span>回撤 {formatReturnPct(item.maxDrawdown, 2)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export const MultiVariantCurveChart = React.memo(MultiVariantCurveChartComponent);
MultiVariantCurveChart.displayName = "MultiVariantCurveChart";

export type CurveControlItem = {
  key: string;
  label: string;
  type: "strategy" | "benchmark";
  value?: number | null;
  detail?: string;
};

export function CurveControls({
  items,
  visibleKeys,
  startDate,
  endDate,
  bounds,
  onToggle,
  onSelectAll,
  onClear,
  onStartDateChange,
  onEndDateChange,
  onShortcut
}: {
  items: CurveControlItem[];
  visibleKeys: string[];
  startDate: string;
  endDate: string;
  bounds: { min: string; max: string };
  onToggle: (key: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onShortcut: (range: "3m" | "6m" | "1y" | "all") => void;
}) {
  return (
    <div className="curve-toolbar">
      <div className="curve-toolbar-meta">
        <span>已显示 {visibleKeys.length} / {items.length} 条</span>
        <button type="button" className="curve-toolbar-button" onClick={onSelectAll}>全选</button>
        <button type="button" className="curve-toolbar-button" onClick={onClear}>清空</button>
      </div>
      <div className="curve-pill-row">
        {items.map((item, index) => {
          const active = visibleKeys.includes(item.key);
          const previewSeries: NormalizedCurveSeries = {
            key: item.key,
            label: item.label,
            type: item.type,
            points: [],
            drawdownPoints: [],
            totalReturn: item.value ?? 0,
            maxDrawdown: 0
          };
          const color = curveSeriesColor(previewSeries, index);
          const detail = item.detail || formatReturnPct(item.value, 2);
          return (
            <button
              type="button"
              key={item.key}
              className={`curve-pill ${active ? "is-active" : ""}`}
              onClick={() => onToggle(item.key)}
              aria-pressed={active}
              title={`${item.label}\n${detail}`}
            >
              <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} style={item.type === "benchmark" ? { borderLeftColor: color } : { background: color }} />
              <span className="curve-pill-copy">
                <strong>{item.label}</strong>
                <small>{detail}</small>
              </span>
              <span className="curve-pill-check" aria-hidden="true">✓</span>
            </button>
          );
        })}
      </div>
      <div className="curve-date-bar">
        <label className="curve-date-field">
          <span>开始</span>
          <Input type="date" value={startDate} min={bounds.min || undefined} max={endDate || bounds.max || undefined} onChange={(event) => onStartDateChange(event.target.value)} />
        </label>
        <label className="curve-date-field">
          <span>结束</span>
          <Input type="date" value={endDate} min={startDate || bounds.min || undefined} max={bounds.max || undefined} onChange={(event) => onEndDateChange(event.target.value)} />
        </label>
        <div className="curve-shortcuts">
          <button type="button" className="curve-shortcut-button" onClick={() => onShortcut("3m")}>近3月</button>
          <button type="button" className="curve-shortcut-button" onClick={() => onShortcut("6m")}>近6月</button>
          <button type="button" className="curve-shortcut-button" onClick={() => onShortcut("1y")}>近1年</button>
          <button type="button" className="curve-shortcut-button" onClick={() => onShortcut("all")}>全部</button>
        </div>
      </div>
    </div>
  );
}
