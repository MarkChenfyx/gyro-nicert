import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart, ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getLivePriceBars } from "../api";

echarts.use([LineChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer]);

export default function LivePriceChart({ symbol, day, trades }: { symbol: string; day: string; trades: Record<string, any>[] }) {
  const element = useRef<HTMLDivElement>(null);
  const [bars, setBars] = useState<any[]>([]);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let cancelled = false;
    setBars([]);
    setNotice("正在读取价格…");
    getLivePriceBars(symbol, day).then(result => {
      if (cancelled) return;
      setBars(result.items || []);
      setNotice(result.items?.length ? "" : "当天暂无本地行情，查看图表不会自动下载或回放。");
    }).catch(error => { if (!cancelled) setNotice(String(error)); });
    return () => { cancelled = true; };
  }, [symbol, day]);
  useEffect(() => {
    if (!element.current || !bars.length) return;
    const chart = echarts.init(element.current);
    // Use a numeric local minute axis so browser time zones cannot shift trade markers.
    const minute = (value: any) => { const t = String(value).slice(11, 19); return Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5)) + Number(t.slice(6, 8) || 0) / 60; };
    const buy = (trade: any) => ["多", "LONG", "long", "买", "买入"].includes(String(trade.direction));
    const points = (isBuy: boolean) => trades.filter(t => buy(t) === isBuy).map(t => ({ value: [minute(t.datetime), Number(t.price)], trade: t }));
    chart.setOption({
      tooltip: { trigger: "item", renderMode: "richText", formatter: (p: any) => p.data?.trade ? `${p.seriesName}\n${p.data.trade.datetime}\n价格 ${p.data.trade.price} · 数量 ${p.data.trade.volume}\n${p.data.trade.offset || ""}` : `价格 ${p.value[1]}` },
      legend: { data: ["分钟收盘价", "回放买入", "回放卖出"] },
      grid: { left: 65, right: 25, top: 40, bottom: 65 },
      xAxis: { type: "value", min: "dataMin", max: "dataMax", axisLabel: { formatter: (v: number) => `${String(Math.floor(v / 60)).padStart(2, "0")}:${String(Math.floor(v % 60)).padStart(2, "0")}` } },
      yAxis: { type: "value", scale: true },
      dataZoom: [{ type: "inside" }, { type: "slider", bottom: 5 }],
      series: [
        { name: "分钟收盘价", type: "line", showSymbol: false, data: bars.map(b => [minute(b.datetime), Number(b.close)]), lineStyle: { color: "#64748b", width: 1.5 } },
        { name: "回放买入", type: "scatter", symbol: "triangle", symbolSize: 14, itemStyle: { color: "#dc2626" }, data: points(true), z: 5 },
        { name: "回放卖出", type: "scatter", symbol: "triangle", symbolRotate: 180, symbolSize: 14, itemStyle: { color: "#16a34a" }, data: points(false), z: 5 },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [bars, trades]);
  return <div><h4>{symbol} · {day} 价格与回放成交</h4>{notice && <p>{notice}</p>}<div ref={element} style={{ height: bars.length ? 340 : 0 }} /><p>三角标记为回放成交价；悬停查看价格、数量与开平，滚轮可缩放。</p></div>;
}
