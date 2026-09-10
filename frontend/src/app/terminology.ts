export const UI_TEXT = {
  page: {
    launch: "新建运行",
    generate: "运行结果",
    optimize: "参数优化",
    pool: "策略池",
    research: "策略研究",
    portfolio: "组合管理",
    live: "实盘跟踪"
  },
  term: {
    strategySeries: "策略系列",
    run: "回测运行",
    runId: "运行编号",
    resultVersion: "结果版本",
    baselineResult: "基线结果",
    latestGridResult: "最新网格结果",
    poolSnapshot: "策略快照",
    poolSnapshotId: "策略快照编号",
    poolVersion: "入池版本",
    curveSnapshot: "曲线快照",
    portfolioSnapshot: "组合快照",
    componentStrategy: "组成策略",
    strategySource: "策略来源",
    strategyDescriptionFile: "策略描述文件",
    strategyDescription: "策略描述",
    tradingSymbol: "交易标的",
    barInterval: "K 线周期"
  },
  metric: {
    totalReturn: "累计收益",
    benchmarkReturn: "买入持有收益",
    excessReturn: "超额收益",
    annualReturn: "年化收益",
    sharpe: "夏普比率",
    maxDrawdown: "最大回撤",
    calmar: "卡玛比率",
    tradeCount: "交易次数",
    tradingCosts: "交易成本",
    convertedPnl: "折算盈亏",
    convertedCapital: "折算本金"
  },
  action: {
    refresh: "刷新",
    rerunBacktest: "重跑回测",
    updateSnapshot: "更新快照",
    saveCurveSnapshot: "保存曲线快照",
    removeFromPool: "移出策略池",
    continueOptimization: "继续优化",
    viewDetails: "查看详情"
  },
  status: {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    archived: "已归档",
    ready: "已就绪",
    pending: "等待中",
    pendingSelection: "待选择",
    pendingUpdate: "待更新"
  },
  research: {
    parameterStability: "参数稳定性",
    parameterStabilityAnalysis: "参数稳定性分析",
    parameterStabilityHeatmap: "参数稳定性热力图",
    walkForward: "滚动优化",
    walkForwardDescription: "滚动样本外检验",
    trainingPeriod: "训练期",
    outOfSamplePeriod: "样本外期",
    optimizationObjective: "优化目标",
    displayMetric: "展示指标"
  }
} as const;

export function resultVersionLabel(value: string) {
  if (value === "baseline") return UI_TEXT.term.baselineResult;
  if (value === "manual_grid") return UI_TEXT.term.latestGridResult;
  if (value === "buy_hold") return "买入持有";
  return value;
}
