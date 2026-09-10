import React, { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { UI_TEXT } from "../app/terminology";

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

function sameValue(left: unknown, right: unknown) {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return Math.abs(leftNumber - rightNumber) < 1e-10;
  }
  return String(left) === String(right);
}

export default function ParameterMetricCurve({
  rows,
  parameter,
  parameterValues,
  metric,
  currentParameters,
  onSelectRow
}: {
  rows: any[];
  parameter: string;
  parameterValues: Array<string | number>;
  metric: "excess_return" | "sharpe";
  currentParameters: Record<string, unknown>;
  onSelectRow?: (row: any) => void;
}) {
  const chartElementRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const option = useMemo(() => {
    const successfulRows = rows.filter((row) => row?.success && Number.isFinite(Number(row?.[metric])));
    const metricValues = successfulRows.map((row) => Number(row[metric]));
    const bestValue = metricValues.length ? Math.max(...metricValues) : null;
    const rowByParameter = new Map<string, any>();
    successfulRows.forEach((row) => rowByParameter.set(String(row?.parameters?.[parameter]), row));
    const data = parameterValues.map((parameterValue) => {
      const row = rowByParameter.get(String(parameterValue));
      if (!row) return null;
      const isCurrent = sameValue(row?.parameters?.[parameter], currentParameters[parameter]);
      const isBest = bestValue !== null && sameValue(row[metric], bestValue);
      return {
        value: Number(row[metric]),
        raw: row,
        symbolSize: isCurrent ? 13 : isBest ? 11 : 7,
        itemStyle: {
          color: isCurrent ? "#0f172a" : isBest ? "#159f9a" : "#6bb8b3",
          borderColor: "#ffffff",
          borderWidth: 2
        },
        label: {
          show: isCurrent || isBest,
          position: "top",
          color: isCurrent ? "#0f172a" : "#0f766e",
          fontSize: 11,
          fontWeight: 700,
          formatter: isCurrent && isBest ? "当前 · 最优" : isCurrent ? "当前" : "最优"
        }
      };
    });
    const metricLabel = metric === "excess_return" ? UI_TEXT.metric.excessReturn : UI_TEXT.metric.sharpe;
    return {
      animationDuration: 240,
      grid: { left: 72, right: 28, top: 42, bottom: 58 },
      tooltip: {
        trigger: "item",
        formatter: (params: any) => {
          const row = params?.data?.raw || {};
          const excess = Number(row.excess_return);
          const sharpe = Number(row.sharpe);
          return [
            `${parameter}: ${row?.parameters?.[parameter] ?? "-"}`,
            `${UI_TEXT.metric.excessReturn}: ${Number.isFinite(excess) ? `${excess.toFixed(2)}%` : "-"}`,
            `${UI_TEXT.metric.sharpe}: ${Number.isFinite(sharpe) ? sharpe.toFixed(2) : "-"}`
          ].join("<br/>");
        }
      },
      xAxis: {
        type: "category",
        name: parameter,
        nameLocation: "middle",
        nameGap: 36,
        boundaryGap: true,
        data: parameterValues.map(String),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { color: "#64748b" }
      },
      yAxis: {
        type: "value",
        name: metricLabel,
        nameTextStyle: { color: "#64748b", padding: [0, 0, 0, 6] },
        axisLabel: {
          color: "#64748b",
          formatter: (value: number) => metric === "excess_return" ? `${value.toFixed(1)}%` : value.toFixed(2)
        },
        splitLine: { lineStyle: { color: "rgba(148,163,184,.18)" } }
      },
      series: [{
        type: "line",
        data,
        connectNulls: false,
        symbol: "circle",
        showSymbol: true,
        lineStyle: { color: "#319d99", width: 2.5 },
        areaStyle: { color: "rgba(49,157,153,.08)" },
        emphasis: { focus: "series", scale: 1.2 }
      }]
    };
  }, [currentParameters, metric, parameter, parameterValues, rows]);

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

  return <div ref={chartElementRef} className="parameter-metric-curve-canvas" />;
}
