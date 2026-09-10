import React, { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { UI_TEXT } from "../app/terminology";

echarts.use([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer]);

const HEATMAP_COLORS = ["#ef9a9a", "#fff7ed", "#b7e4dd", "#159f9a"];
const MINIMUM_VISUAL_SPAN = {
  excess_return: 1,
  sharpe: 0.1
} as const;

function sameValue(left: unknown, right: unknown) {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return Math.abs(leftNumber - rightNumber) < 1e-10;
  return String(left) === String(right);
}

export default function ResearchHeatmap({
  rows,
  xParameter,
  yParameter,
  xValues,
  yValues,
  metric,
  currentParameters,
  visualRange,
  onSelectRow
}: {
  rows: any[];
  xParameter: string;
  yParameter: string;
  xValues: Array<string | number>;
  yValues: Array<string | number>;
  metric: "excess_return" | "sharpe";
  currentParameters: Record<string, unknown>;
  visualRange?: { min: number; max: number };
  onSelectRow?: (row: any) => void;
}) {
  const chartElementRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const option = useMemo(() => {
    const successfulRows = rows.filter((row) => row?.success && Number.isFinite(Number(row?.[metric])));
    const metricValues = successfulRows.map((row) => Number(row[metric]));
    const rawMin = metricValues.length ? Math.min(...metricValues) : 0;
    const rawMax = metricValues.length ? Math.max(...metricValues) : 1;
    const requestedMin = Number(visualRange?.min);
    const requestedMax = Number(visualRange?.max);
    const rangeMin = Number.isFinite(requestedMin) ? requestedMin : rawMin;
    const rangeMax = Number.isFinite(requestedMax) ? requestedMax : rawMax;
    const rangeCenter = (rangeMin + rangeMax) / 2;
    const visualSpan = Math.max(rangeMax - rangeMin, MINIMUM_VISUAL_SPAN[metric]);
    const visualMin = rangeCenter - visualSpan / 2;
    const visualMax = rangeCenter + visualSpan / 2;
    const bestValue = metricValues.length ? rawMax : null;
    const data = successfulRows.map((row) => {
      const parameters = row?.parameters || {};
      const xIndex = xValues.findIndex((value) => sameValue(value, parameters[xParameter]));
      const yIndex = yValues.findIndex((value) => sameValue(value, parameters[yParameter]));
      const isCurrent = sameValue(parameters[xParameter], currentParameters[xParameter])
        && sameValue(parameters[yParameter], currentParameters[yParameter]);
      const isBest = bestValue !== null && sameValue(row[metric], bestValue);
      return {
        value: [xIndex, yIndex, Number(row[metric])],
        raw: row,
        marker: isCurrent && isBest ? "●★" : isCurrent ? "●" : isBest ? "★" : ""
      };
    }).filter((item) => item.value[0] >= 0 && item.value[1] >= 0);
    const metricLabel = metric === "excess_return" ? UI_TEXT.metric.excessReturn : UI_TEXT.metric.sharpe;
    const formatScaleValue = (value: number) => metric === "excess_return" ? `${value.toFixed(2)}%` : value.toFixed(2);
    return {
      animationDuration: 240,
      grid: { left: 76, right: 96, top: 28, bottom: 58 },
      tooltip: {
        trigger: "item",
        formatter: (params: any) => {
          const row = params?.data?.raw || {};
          const parameterText = Object.entries(row.parameters || {}).map(([name, value]) => `${name}: ${value}`).join("<br/>");
          const excess = Number(row.excess_return);
          const sharpe = Number(row.sharpe);
          return [
            parameterText,
            `超额收益: ${Number.isFinite(excess) ? `${excess.toFixed(2)}%` : "-"}`,
            `${UI_TEXT.metric.sharpe}: ${Number.isFinite(sharpe) ? sharpe.toFixed(2) : "-"}`
          ].filter(Boolean).join("<br/>");
        }
      },
      xAxis: {
        type: "category",
        name: xParameter,
        nameLocation: "middle",
        nameGap: 36,
        data: xValues.map(String),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { color: "#64748b" }
      },
      yAxis: {
        type: "category",
        name: yParameter,
        nameLocation: "middle",
        nameGap: 52,
        data: yValues.map(String),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { color: "#64748b" }
      },
      visualMap: {
        min: visualMin,
        max: visualMax,
        calculable: false,
        orient: "vertical",
        right: 4,
        top: "middle",
        text: [`${metricLabel}\n${formatScaleValue(visualMax)}`, formatScaleValue(visualMin)],
        textStyle: { color: "#64748b", fontSize: 11 },
        inRange: { color: HEATMAP_COLORS }
      },
      series: [{
        type: "heatmap",
        data,
        label: {
          show: true,
          color: "#0f172a",
          fontSize: 12,
          fontWeight: 700,
          formatter: (params: any) => params?.data?.marker || ""
        },
        itemStyle: { borderColor: "rgba(255,255,255,.82)", borderWidth: 2, borderRadius: 4 },
        emphasis: { itemStyle: { borderColor: "#0f766e", borderWidth: 2 } }
      }]
    };
  }, [currentParameters, metric, rows, visualRange, xParameter, xValues, yParameter, yValues]);

  useEffect(() => {
    if (!chartElementRef.current) return;
    const chart = echarts.init(chartElementRef.current);
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

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !onSelectRow) return;
    const handleClick = (params: any) => {
      if (params?.data?.raw) onSelectRow(params.data.raw);
    };
    chart.on("click", handleClick);
    return () => {
      chart.off("click", handleClick);
    };
  }, [onSelectRow]);

  return <div ref={chartElementRef} className="research-heatmap-canvas" />;
}
