import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export default function BrokerAssetCurve({ rows }: { rows: any[] }) {
  const element = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current);
    chart.setOption({
      animation: false,
      color: ["#0f766e", "#2563eb", "#94a3b8"],
      tooltip: { trigger: "axis", valueFormatter: (value: unknown) => Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 }) },
      legend: { top: 0, data: ["总资产", "总市值", "可用资金"] },
      grid: { left: 64, right: 20, top: 38, bottom: 34 },
      xAxis: { type: "category", boundaryGap: false, data: rows.map(row => row.trade_date) },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (value: number) => `${Math.round(value / 10000)}万` } },
      series: [
        { name: "总资产", type: "line", showSymbol: rows.length < 20, data: rows.map(row => row.total_assets) },
        { name: "总市值", type: "line", showSymbol: rows.length < 20, data: rows.map(row => row.total_market_value) },
        { name: "可用资金", type: "line", showSymbol: rows.length < 20, data: rows.map(row => row.available_cash) }
      ]
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [rows]);

  return <div className="broker-asset-curve" ref={element} />;
}
