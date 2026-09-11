import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { CandlestickChart, ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getLivePriceBars } from "../api";

echarts.use([CandlestickChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer]);

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
    // Only observed bar minutes occupy horizontal space, including across lunch.
    const minute = (value: any) => String(value).slice(11, 16);
    const buy = (trade: any) => ["多", "LONG", "long", "买", "买入"].includes(String(trade.direction));
    const points = (isBuy: boolean) => trades.filter(t => buy(t) === isBuy).map(t => ({ value: [minute(t.datetime), Number(t.price)], trade: t }));
    chart.setOption({
      tooltip: { trigger: "item", renderMode: "richText", formatter: (p: any) => {
        if (p.data?.trade) return `${p.seriesName}\n${p.data.trade.datetime}\n价格 ${p.data.trade.price} · 数量 ${p.data.trade.volume}\n${p.data.trade.offset || ""}`;
        const bar = bars[p.dataIndex];
        return `${minute(bar.datetime)}\n开盘 ${bar.open}  收盘 ${bar.close}\n最高 ${bar.high}  最低 ${bar.low}\n成交量 ${bar.volume}`;
      } },
      legend: { data: ["分钟K线", "回放买入", "回放卖出"] },
      grid: { left: 65, right: 25, top: 40, bottom: 65 },
      xAxis: { type: "category", data: bars.map(b => minute(b.datetime)), axisPointer: { show: true, type: "line", snap: true }, axisLabel: { hideOverlap: true } },
      yAxis: { type: "value", scale: true },
      dataZoom: [{ type: "inside" }, { type: "slider", bottom: 5 }],
      series: [
        { name: "分钟K线", type: "candlestick", data: bars.map(b => [Number(b.open), Number(b.close), Number(b.low), Number(b.high)]), itemStyle: { color: "#dc2626", color0: "#16a34a", borderColor: "#dc2626", borderColor0: "#16a34a" } },
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
