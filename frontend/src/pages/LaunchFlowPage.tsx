import React, { useEffect, useMemo, useRef, useState } from "react";
import { AutoComplete, Button, Checkbox, Drawer, Input, InputNumber, Modal, Progress, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  addToPool,
  archiveTerminalTasks,
  comparePool,
  createNaturalLanguageSource,
  createResearchBaseline,
  createResearchBaselineFromCode,
  downloadData,
  generateStrategy,
  getDataCoverage,
  getNaturalLanguageSource,
  getOptimizationMethods,
  getOptimizationSearchSpace,
  suggestOptimizationSearchSpace,
  getPoolItem,
  getVariantCurve,
  getRun,
  listRuns,
  listNaturalLanguageSources,
  listPool,
  listTasks,
  removeFromPool,
  repairStrategyCode,
  rerunPool,
  runOptimization,
  updateNaturalLanguageSource
} from "../api";
import {
  BENCHMARK_CURVE_COLOR,
  LAUNCH_DRAFT_STORAGE_KEY,
  LAUNCH_SYMBOL_OPTIONS,
  LaunchDraft,
  LocalStrategyFile,
  SOURCE_FILES,
  SOURCE_SORT_STORAGE_KEY,
  SourceFile,
  SourceSortMode,
  StrategyRepairUiStatus,
  WorkflowUiState,
  extractMissingRanges,
  formatDate,
  formatNumber,
  formatPercent,
  formatReturnPct,
  loadLaunchDraft,
  loadSourceSortMode,
  missingRangeLabel,
  normalizeStrategyRepairResponse,
  parseLaunchVtSymbol,
  saveLaunchDraft,
  sourceSearchCorpus,
  statusClass,
  zh
} from "../app/ui";

export function LaunchFlowPage({
  onResearchCreated,
  onGenerated,
  onOpenGenerated,
  onWorkflowChange,
  refreshTasks
}: {
  onResearchCreated: (payload: any) => void;
  onGenerated: (payload: any) => void;
  onOpenGenerated: () => void;
  onWorkflowChange: (patch: Partial<WorkflowUiState>) => void;
  refreshTasks: () => Promise<void>;
}) {
  const restoredLaunchDraft = useMemo(loadLaunchDraft, []);
  const fallbackSourceFiles = SOURCE_FILES.map((name) => ({ name }));
  const [sourceFiles, setSourceFiles] = useState<SourceFile[]>(fallbackSourceFiles);
  const [sourceSortMode, setSourceSortMode] = useState<SourceSortMode>(loadSourceSortMode);
  const [sourceSearch, setSourceSearch] = useState("");
  const [inputMode, setInputMode] = useState<"natural_language" | "manual_code" | "local_code">(() =>
    ["natural_language", "manual_code", "local_code"].includes(String(restoredLaunchDraft.inputMode))
      ? restoredLaunchDraft.inputMode as "natural_language" | "manual_code" | "local_code"
      : "natural_language"
  );
  const [selectedFile, setSelectedFile] = useState(() => String(restoredLaunchDraft.selectedFile || SOURCE_FILES[0] || ""));
  const [sourceText, setSourceText] = useState("");
  const [savedSourceText, setSavedSourceText] = useState("");
  const [isCreatingSource, setIsCreatingSource] = useState(false);
  const [newSourceFilename, setNewSourceFilename] = useState("");
  const [manualStrategyName, setManualStrategyName] = useState(() => String(restoredLaunchDraft.manualStrategyName || ""));
  const [manualStrategyCode, setManualStrategyCode] = useState(() => String(restoredLaunchDraft.manualStrategyCode || ""));
  const [localStrategyFiles, setLocalStrategyFiles] = useState<LocalStrategyFile[]>(() => restoredLaunchDraft.localStrategyFiles || []);
  const [selectedLocalPath, setSelectedLocalPath] = useState(() => String(restoredLaunchDraft.selectedLocalPath || restoredLaunchDraft.localStrategyFiles?.[0]?.relativePath || ""));
  const localFolderInputRef = useRef<HTMLInputElement>(null);
  const [vtSymbolInput, setVtSymbolInput] = useState(() => String(restoredLaunchDraft.vtSymbolInput || "511380.SSE"));
  const [interval, setInterval] = useState(() => String(restoredLaunchDraft.interval || "1m"));
  const [startDate, setStartDate] = useState(() => String(restoredLaunchDraft.startDate || "2025-01-02"));
  const [endDate, setEndDate] = useState(() => String(restoredLaunchDraft.endDate || "2026-06-25"));
  const [rate, setRate] = useState<number | null>(() => typeof restoredLaunchDraft.rate === "number" ? restoredLaunchDraft.rate : 0.000045);
  const [slippage, setSlippage] = useState<number | null>(() => typeof restoredLaunchDraft.slippage === "number" ? restoredLaunchDraft.slippage : 0.002);
  const [loadingResearch, setLoadingResearch] = useState(false);
  const [loadingSources, setLoadingSources] = useState(false);
  const [savingSource, setSavingSource] = useState(false);
  const [repairingLocalCode, setRepairingLocalCode] = useState(false);
  const [localRepairProgress, setLocalRepairProgress] = useState(0);
  const [localRepairFeedback, setLocalRepairFeedback] = useState<{
    status: StrategyRepairUiStatus;
    detail: string;
  } | null>(null);
  const [repairingManualCode, setRepairingManualCode] = useState(false);
  const [manualRepairProgress, setManualRepairProgress] = useState(0);
  const [manualRepairFeedback, setManualRepairFeedback] = useState<{
    status: StrategyRepairUiStatus;
    detail: string;
  } | null>(null);
  const [launchError, setLaunchError] = useState<any>(null);
  const isSourceDirty = !isCreatingSource && Boolean(selectedFile) && sourceText !== savedSourceText;
  const canRunNaturalLanguage = Boolean(selectedFile && sourceText.trim()) && !isCreatingSource && !isSourceDirty;
  const canRunManualCode = Boolean(manualStrategyName.trim() && manualStrategyCode.trim());
  const selectedLocalFile = localStrategyFiles.find((file) => file.relativePath === selectedLocalPath);
  const canRunLocalCode = Boolean(manualStrategyName.trim() && selectedLocalFile?.code.trim());
  const canRunSource = inputMode === "natural_language"
    ? canRunNaturalLanguage
    : inputMode === "local_code" ? canRunLocalCode : canRunManualCode;
  const sortedSourceFiles = useMemo(() => [...sourceFiles].sort((left, right) => {
    if (sourceSortMode === "modified") {
      const modifiedDifference = Date.parse(right.modified_at || "") - Date.parse(left.modified_at || "");
      if (Number.isFinite(modifiedDifference) && modifiedDifference !== 0) return modifiedDifference;
    }
    return left.name.localeCompare(right.name, "zh-CN", { numeric: true, sensitivity: "base" });
  }), [sourceFiles, sourceSortMode]);
  const visibleSourceFiles = useMemo(() => {
    const keywords = sourceSearch.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    if (keywords.length === 0) return sortedSourceFiles;
    return sortedSourceFiles.filter((file) => {
      const searchCorpus = sourceSearchCorpus(file.name);
      return keywords.every((keyword) => searchCorpus.includes(keyword));
    });
  }, [sortedSourceFiles, sourceSearch]);
  const mountedRef = useRef(true);
  const latestLaunchDraftRef = useRef<LaunchDraft>({
    inputMode,
    selectedFile,
    manualStrategyName,
    manualStrategyCode,
    localStrategyFiles,
    selectedLocalPath,
    vtSymbolInput,
    interval,
    startDate,
    endDate,
    rate,
    slippage
  });
  latestLaunchDraftRef.current = {
    inputMode,
    selectedFile,
    manualStrategyName,
    manualStrategyCode,
    localStrategyFiles,
    selectedLocalPath,
    vtSymbolInput,
    interval,
    startDate,
    endDate,
    rate,
    slippage
  };

  useEffect(() => {
    try {
      window.localStorage.setItem(SOURCE_SORT_STORAGE_KEY, sourceSortMode);
    } catch {
      // Sorting remains usable when local storage is unavailable.
    }
  }, [sourceSortMode]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => saveLaunchDraft(latestLaunchDraftRef.current), 500);
    return () => window.clearTimeout(timer);
  }, [inputMode, selectedFile, manualStrategyName, manualStrategyCode, localStrategyFiles, selectedLocalPath, vtSymbolInput, interval, startDate, endDate, rate, slippage]);

  useEffect(() => {
    const saveLatestDraft = () => saveLaunchDraft(latestLaunchDraftRef.current);
    window.addEventListener("beforeunload", saveLatestDraft);
    return () => window.removeEventListener("beforeunload", saveLatestDraft);
  }, []);

  useEffect(() => {
    if (!repairingLocalCode) return;
    const timer = window.setInterval(() => {
      setLocalRepairProgress((current) => current >= 100
        ? 100
        : Math.min(92, current + Math.max(1, Math.ceil((92 - current) * 0.12))));
    }, 500);
    return () => window.clearInterval(timer);
  }, [repairingLocalCode]);

  useEffect(() => {
    if (!repairingManualCode) return;
    const timer = window.setInterval(() => {
      setManualRepairProgress((current) => current >= 100
        ? 100
        : Math.min(92, current + Math.max(1, Math.ceil((92 - current) * 0.12))));
    }, 500);
    return () => window.clearInterval(timer);
  }, [repairingManualCode]);

  async function refreshSourceFiles(preferredSelection?: string) {
    setLoadingSources(true);
    try {
      const payload = await listNaturalLanguageSources();
      const files = Array.isArray(payload.files) ? payload.files : [];
      if (files.length > 0) {
        setSourceFiles(files);
        const desiredSelection = [preferredSelection || selectedFile].find((name) =>
          name && files.some((file: SourceFile) => file.name === name)
        );
        setSelectedFile(desiredSelection || files[0]?.name || "");
      } else {
        setSourceFiles([]);
        setSelectedFile("");
      }
      return files;
    } catch (error) {
      message.warning("自然语言文本列表暂时不可用");
      return [];
    } finally {
      setLoadingSources(false);
    }
  }

  useEffect(() => {
    let active = true;
    refreshSourceFiles()
      .then((files) => {
        if (!active || files.length === 0) return;
        const nextName = files.some((file: SourceFile) => file.name === selectedFile) ? selectedFile : files[0]?.name || "";
        if (nextName) {
          void loadSourceText(nextName, true);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  async function loadSourceText(filename?: string, silent = false) {
    const selectedName = filename || selectedFile;
    if (!selectedName) {
      message.warning("请先选择一个文本文件");
      return;
    }
    setLoadingSources(true);
    try {
      const payload = await getNaturalLanguageSource(selectedName);
      const text = String(payload.text || "");
      setSourceText(text);
      setSavedSourceText(text);
      setIsCreatingSource(false);
      setNewSourceFilename("");
      setSelectedFile(selectedName);
      if (!silent) message.success(`已加载 ${selectedName}`);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingSources(false);
    }
  }

  function selectSourceFile(filename: string) {
    if (isCreatingSource) {
      setIsCreatingSource(false);
      setNewSourceFilename("");
      void loadSourceText(filename);
      return;
    }
    if (isSourceDirty) {
      message.warning("切换前请先保存当前文本");
      return;
    }
    if (!filename || filename === selectedFile) return;
    void loadSourceText(filename);
  }

  function startCreateSource() {
    if (isSourceDirty) {
      message.warning("新建前请先保存当前文本");
      return;
    }
    setIsCreatingSource(true);
    setNewSourceFilename("");
    setSourceText("");
    setSavedSourceText("");
  }

  function cancelCreateSource() {
    setIsCreatingSource(false);
    setNewSourceFilename("");
    if (selectedFile) {
      void loadSourceText(selectedFile, true);
      return;
    }
    setSourceText(savedSourceText);
  }

  async function saveSourceFile() {
    const filename = (isCreatingSource ? newSourceFilename : selectedFile).trim();
    const text = sourceText.trim();
    if (!filename) {
      message.warning("请先输入文件名");
      return;
    }
    if (!text) {
      message.warning("请先输入文本内容");
      return;
    }
    setSavingSource(true);
    try {
      const payload = isCreatingSource
        ? await createNaturalLanguageSource(filename, sourceText)
        : await updateNaturalLanguageSource(filename, sourceText);
      const savedName = String(payload.name || "");
      await refreshSourceFiles(savedName);
      setSelectedFile(savedName);
      setIsCreatingSource(false);
      setNewSourceFilename("");
      setSavedSourceText(String(payload.text || ""));
      message.success(`已保存 ${payload.name}`);
    } catch (error) {
      message.error(String(error));
    } finally {
      setSavingSource(false);
    }
  }

  async function loadLocalStrategyFile(event: React.ChangeEvent<HTMLInputElement>) {
    const inputFiles = Array.from(event.target.files || []);
    const file = inputFiles[0];
    if (!file || !file.name.toLowerCase().endsWith(".py")) {
      setLocalStrategyFiles([]);
      setSelectedLocalPath("");
      message.warning("请选择 .py 策略文件");
      event.target.value = "";
      return;
    }
    try {
      const loaded: LocalStrategyFile[] = [{
        name: file.name,
        relativePath: file.name,
        code: await file.text()
      }];
      setLocalStrategyFiles(loaded);
      setSelectedLocalPath(loaded[0].relativePath);
      setManualStrategyName(loaded[0].name.replace(/\.py$/i, ""));
      setLocalRepairProgress(0);
      setLocalRepairFeedback(null);
      message.success(`已读取策略文件：${file.name}`);
    } catch (error) {
      message.error(`读取本地策略失败：${String(error)}`);
    } finally {
      event.target.value = "";
    }
  }

  async function repairLocalStrategyCode() {
    if (!selectedLocalFile?.code.trim()) {
      message.warning("请先选择需要修正的 .py 策略文件");
      return;
    }
    const targetPath = selectedLocalFile.relativePath;
    setLocalRepairProgress(6);
    setLocalRepairFeedback(null);
    setRepairingLocalCode(true);
    try {
      const payload = await repairStrategyCode({
        strategy_name: manualStrategyName.trim() || selectedLocalFile.name.replace(/\.py$/i, ""),
        strategy_code: selectedLocalFile.code,
        vt_symbol: vtSymbolInput.trim(),
        interval
      });
      const feedback = normalizeStrategyRepairResponse(payload);
      setLocalRepairProgress(100);
      setLocalRepairFeedback({ status: feedback.status, detail: feedback.detail });
      if (feedback.status === "warning") {
        message.warning("AI 判断代码仍需人工处理，已保留原回测代码");
        return;
      }
      if (feedback.status === "failed") {
        message.error(`AI 修正失败：${feedback.detail}`);
        return;
      }
      setLocalStrategyFiles((files) => files.map((file) => file.relativePath === targetPath
        ? {
            ...file,
            code: feedback.strategyCode,
            aiRepaired: true,
            repairWarnings: []
          }
        : file));
      message.success("AI 修正完成，启动回测时将使用修正后的代码");
    } catch (error) {
      const detail = "AI 修正请求失败，请检查接口配置或网络后重试";
      setLocalRepairProgress(100);
      setLocalRepairFeedback({ status: "failed", detail });
      message.error(detail);
    } finally {
      setRepairingLocalCode(false);
    }
  }

  async function repairManualStrategyCode() {
    if (!manualStrategyCode.trim()) {
      message.warning("请先粘贴需要修正的策略代码");
      return;
    }
    setManualRepairProgress(6);
    setManualRepairFeedback(null);
    setRepairingManualCode(true);
    try {
      const payload = await repairStrategyCode({
        strategy_name: manualStrategyName.trim() || "粘贴策略",
        strategy_code: manualStrategyCode,
        vt_symbol: vtSymbolInput.trim(),
        interval
      });
      const feedback = normalizeStrategyRepairResponse(payload);
      setManualRepairProgress(100);
      setManualRepairFeedback({ status: feedback.status, detail: feedback.detail });
      if (feedback.status === "warning") {
        message.warning("AI 判断代码仍需人工处理，已保留原回测代码");
        return;
      }
      if (feedback.status === "failed") {
        message.error(`AI 修正失败：${feedback.detail}`);
        return;
      }
      setManualStrategyCode(feedback.strategyCode);
      message.success("AI 修正完成，启动回测时将使用修正后的代码");
    } catch (error) {
      const detail = "AI 修正请求失败，请检查接口配置或网络后重试";
      setManualRepairProgress(100);
      setManualRepairFeedback({ status: "failed", detail });
      message.error(detail);
    } finally {
      setRepairingManualCode(false);
    }
  }

  async function runResearch() {
    const parsedVtSymbol = parseLaunchVtSymbol(vtSymbolInput);
    if (!parsedVtSymbol) {
      message.warning("请输入 SYMBOL.EXCHANGE 格式，例如 510300.SSE");
      return;
    }
    const { symbol, exchange } = parsedVtSymbol;
    const isCodeMode = inputMode === "manual_code" || inputMode === "local_code";
    const strategyCode = inputMode === "local_code" ? selectedLocalFile?.code || "" : manualStrategyCode;
    if (isCodeMode && !manualStrategyName.trim()) {
      message.warning("请先填写策略名称");
      return;
    }
    if (isCodeMode && !strategyCode.trim()) {
      message.warning(inputMode === "local_code" ? "请先选择一个 .py 策略文件" : "请先粘贴完整 strategy.py 代码");
      return;
    }
    if (!isCodeMode && !canRunNaturalLanguage) {
      message.warning("启动前请先保存当前文本");
      return;
    }

    setLaunchError(null);
    setLoadingResearch(true);
    const startedAt = new Date().toISOString();
    onWorkflowChange({
      stageKey: "generation",
      message: isCodeMode ? "正在登记策略代码并创建 strategy.py。" : "正在根据自然语言生成 strategy.py。",
      startedAt,
      isRunning: true,
      progress: 0.05,
      sourceFilename: isCodeMode ? manualStrategyName.trim() : selectedFile,
      error: null,
      downloadDiagnostics: null
    });
    onOpenGenerated();

    try {
      let autoDownloaded = false;
      let generationPayload: any = null;
      let strategyId = "";

      if (!isCodeMode) {
        onWorkflowChange({
          progress: 0.25,
          message: "生成请求已提交，正在等待 API 返回。"
        });
        generationPayload = await generateStrategy(selectedFile);
        onWorkflowChange({
          progress: 0.55,
          message: "生成 API 已返回，正在校验并登记策略代码。"
        });
        onGenerated(generationPayload);
        await refreshTasks();
        strategyId = String(generationPayload?.strategy?.strategy_id || "");
        if (!strategyId) {
          throw new Error(generationPayload?.error || "策略生成失败");
        }
      } else {
        onWorkflowChange({
          progress: 0.55,
          message: "策略代码已读取，正在登记并检查回测条件。"
        });
      }

      onWorkflowChange({ progress: 0.6, message: "策略代码已就绪，正在检查行情覆盖。" });
      const coverage = await getDataCoverage(symbol, exchange, interval, startDate || undefined, endDate || undefined);
      const coverageStatus = String(coverage?.status || "").toLowerCase();
      if (["missing", "partial", "failed"].includes(coverageStatus)) {
        onWorkflowChange({
          stageKey: "download",
          message: "检测到缺失行情，系统正在自动下载。",
          progress: 0.62,
          downloadDiagnostics: coverage
        });
        const downloadPayload = await downloadData({
          symbol,
          exchange,
          interval,
          start_date: startDate,
          end_date: endDate
        });
        if (!downloadPayload?.success) {
          throw new Error(String(downloadPayload?.error || "行情下载失败"));
        }
        onWorkflowChange({ downloadDiagnostics: downloadPayload?.coverage || downloadPayload });
        const refreshedCoverage = await getDataCoverage(symbol, exchange, interval, startDate || undefined, endDate || undefined);
        const refreshedStatus = String(refreshedCoverage?.status || "").toLowerCase();
        if (!["covered", "available"].includes(refreshedStatus)) {
          throw new Error("下载后行情仍然不完整");
        }
        autoDownloaded = true;
      }

      onWorkflowChange({
        stageKey: "backtest",
        message: isCodeMode ? "策略代码已登记，正在运行基线回测。" : "策略已生成，正在运行基线回测。",
        progress: 0.65
      });

      const payload = isCodeMode
        ? await createResearchBaselineFromCode({
            strategy_name: manualStrategyName.trim(),
            strategy_code: strategyCode,
            symbol,
            exchange,
            interval,
            start_date: startDate || undefined,
            end_date: endDate || undefined,
            rate: rate ?? 0.000045,
            slippage: slippage ?? 0.001,
            mode: "real"
          })
        : {
            generation: generationPayload,
            ...(await createResearchBaseline({
              strategy_id: strategyId,
              symbol,
              exchange,
              interval,
              start_date: startDate || undefined,
              end_date: endDate || undefined,
              rate: rate ?? 0.000045,
              slippage: slippage ?? 0.001,
              mode: "real"
            }))
          };

      if (payload?.generation) onGenerated(payload.generation);
      if (isCodeMode && payload?.generation?.strategy?.fixed_size_normalized) {
        message.info("检测到策略仓位不是单位仓位，平台已自动统一为 fixed_size = 1。");
      }
      onResearchCreated(payload);
      await refreshTasks();

      if (payload?.error || payload?.backtest?.success === false) {
        setLaunchError(payload);
        onWorkflowChange({
          stageKey: "idle",
          message: String(payload.error || "回测失败"),
          isRunning: false,
          error: payload
        });
        message.warning(String(payload.error || "回测失败"));
        return;
      }

      onWorkflowChange({
        stageKey: "idle",
        message: autoDownloaded ? "研究流程已完成，缺失行情已自动补齐。" : "研究流程已创建。",
        isRunning: false,
        progress: 1,
        error: null
      });
      message.success(autoDownloaded ? "缺失行情已下载，研究流程已创建" : "研究流程已创建");
    } catch (error) {
      setLaunchError({ error: String(error) });
      onWorkflowChange({
        stageKey: "idle",
        message: String(error),
        isRunning: false,
        error
      });
      message.error(String(error));
    } finally {
      if (mountedRef.current) setLoadingResearch(false);
    }
  }

  return (
    <section className="view is-active">
      <div className="hero-band">
        <div>
          <p className="eyebrow">研究启动</p>
          <h2>{zh.launchFlow}</h2>
          <p className="hero-copy">在这里配置回测参数，并通过自然语言、粘贴代码或本地文件启动完整研究流程。</p>
        </div>
      </div>

      <div className="pipeline-grid launch-config-grid">
        <section className="band setup-band">
          <div className="band-head">
            <div>
              <h3>{zh.startConfig}</h3>
              <p className="band-note">三种输入方式共用同一套回测配置，成功后都会进入同一条基线回测与参数优化链路。</p>
            </div>
          </div>
          <div className="form-grid">
            <section className="field span-2">
              <div className="field-head">
                <span>{zh.inputMode}</span>
              </div>
              <div className="field-actions">
                <button className={`mini-button ${inputMode === "natural_language" ? "is-active" : ""}`} type="button" onClick={() => setInputMode("natural_language")}>{zh.naturalLanguageMode}</button>
                <button className={`mini-button ${inputMode === "manual_code" ? "is-active" : ""}`} type="button" onClick={() => setInputMode("manual_code")}>{zh.manualCodeMode}</button>
                <button className={`mini-button ${inputMode === "local_code" ? "is-active" : ""}`} type="button" onClick={() => setInputMode("local_code")}>{zh.localCodeMode}</button>
              </div>
            </section>

            {inputMode === "natural_language" && (
              <>
                <section className="field span-2">
                  <div className="field-head source-file-head">
                    <span>{zh.sourceFiles}</span>
                    <div className="field-actions source-file-actions">
                      <Input
                        allowClear
                        className="source-search-input"
                        size="small"
                        value={sourceSearch}
                        onChange={(event) => setSourceSearch(event.target.value)}
                        placeholder="搜索文件名 / 拼音 / 英文"
                      />
                      <Select<SourceSortMode>
                        aria-label="自然语言文本排序"
                        className="source-sort-select"
                        size="small"
                        value={sourceSortMode}
                        onChange={setSourceSortMode}
                        options={[
                          { value: "name", label: "按名称" },
                          { value: "modified", label: "最近编辑" }
                        ]}
                      />
                      <button className="mini-button source-new-button" type="button" onClick={startCreateSource}>{zh.newSource}</button>
                    </div>
                  </div>
                  <div className="source-checklist" aria-busy={loadingSources}>
                    {visibleSourceFiles.map((file) => (
                      <button
                        type="button"
                        key={file.name}
                        className={`source-strip ${selectedFile === file.name ? "is-active" : ""}`}
                        onClick={() => selectSourceFile(file.name)}
                        disabled={loadingSources}
                      >
                        <strong>{file.name}</strong>
                        <small>{file.size ? `${file.size} 字节` : "本地 txt"}</small>
                      </button>
                    ))}
                    {visibleSourceFiles.length === 0 && <div className="source-search-empty">没有匹配的文本</div>}
                  </div>
                </section>

                <section className="field span-2">
                  <div className="field-head">
                    <span>{zh.sourceText}</span>
                    {(isCreatingSource || isSourceDirty) && <span className="meta-inline">继续前请先保存为本地 txt</span>}
                  </div>
                  {(isCreatingSource || isSourceDirty) && (
                    <div className="inline-input-row">
                      <Input
                        value={newSourceFilename}
                        disabled={!isCreatingSource}
                        onChange={(event) => setNewSourceFilename(event.target.value)}
                        placeholder={`${zh.sourceFilename}，例如 example_strategy.txt`}
                      />
                      <Button type="primary" loading={savingSource} onClick={saveSourceFile}>{zh.save}</Button>
                      <Button onClick={cancelCreateSource}>{zh.cancel}</Button>
                    </div>
                  )}
                  <Input.TextArea rows={7} value={sourceText} onChange={(event) => setSourceText(event.target.value)} />
                </section>
              </>
            )}

            {inputMode === "manual_code" && (
              <>
                <label className="field span-2">
                  <span>{zh.strategyNameInput}</span>
                  <Input value={manualStrategyName} onChange={(event) => setManualStrategyName(event.target.value)} placeholder="例如：线性回归斜率量化策略" />
                </label>
                <section className="field span-2">
                  <div className="field-head">
                    <span>{zh.strategyCodeInput}</span>
                    <div className="inline-input-row">
                      <span className="meta-inline">直接粘贴完整 strategy.py</span>
                      <Button size="small" disabled={!manualStrategyCode.trim()} loading={repairingManualCode} onClick={repairManualStrategyCode}>AI 修正代码</Button>
                    </div>
                  </div>
                  <Input.TextArea rows={12} value={manualStrategyCode} onChange={(event) => { setManualStrategyCode(event.target.value); setManualRepairProgress(0); setManualRepairFeedback(null); }} placeholder="from vnpy_ctastrategy import CtaTemplate ..." />
                  {(repairingManualCode || manualRepairFeedback) && (
                    <div className={`ai-repair-mini ${manualRepairFeedback ? `is-${manualRepairFeedback.status}` : ""}`}>
                      <span className="ai-repair-mini-label">
                        {repairingManualCode
                          ? "AI 正在修正"
                          : manualRepairFeedback?.status === "runnable"
                            ? "修正成功"
                            : manualRepairFeedback?.status === "warning"
                              ? "需要人工处理"
                              : "修正失败"}
                      </span>
                      <Progress
                        percent={manualRepairProgress}
                        status={manualRepairFeedback?.status === "failed" ? "exception" : manualRepairFeedback?.status === "runnable" ? "success" : "active"}
                        strokeColor={manualRepairFeedback?.status === "warning" ? "#d97706" : undefined}
                        showInfo={false}
                        strokeWidth={3}
                      />
                      <span className="ai-repair-mini-result">
                        {repairingManualCode ? `${manualRepairProgress}%` : manualRepairFeedback?.detail}
                      </span>
                    </div>
                  )}
                </section>
              </>
            )}

            {inputMode === "local_code" && (
              <>
                <section className="field span-2">
                  <div className="field-head">
                    <span>本地策略文件</span>
                    <span className="meta-inline">直接选择一个 .py 策略文件</span>
                  </div>
                  <input
                    ref={localFolderInputRef}
                    type="file"
                    accept=".py,text/x-python"
                    onChange={loadLocalStrategyFile}
                    style={{ display: "none" }}
                  />
                  <div className="inline-input-row">
                    <Button onClick={() => localFolderInputRef.current?.click()}>选择 .py 文件</Button>
                    <Button disabled={!selectedLocalFile} loading={repairingLocalCode} onClick={repairLocalStrategyCode}>AI 修正代码</Button>
                    <span className="meta-inline">
                      {selectedLocalFile ? `已选择：${selectedLocalFile.name}` : "尚未选择策略文件"}
                    </span>
                  </div>
                  {(repairingLocalCode || localRepairFeedback) && (
                    <div className={`ai-repair-mini ${localRepairFeedback ? `is-${localRepairFeedback.status}` : ""}`}>
                      <span className="ai-repair-mini-label">
                        {repairingLocalCode
                          ? "AI 正在修正"
                          : localRepairFeedback?.status === "runnable"
                            ? "修正成功"
                            : localRepairFeedback?.status === "warning"
                              ? "需要人工处理"
                              : "修正失败"}
                      </span>
                      <Progress
                        percent={localRepairProgress}
                        status={localRepairFeedback?.status === "failed" ? "exception" : localRepairFeedback?.status === "runnable" ? "success" : "active"}
                        strokeColor={localRepairFeedback?.status === "warning" ? "#d97706" : undefined}
                        showInfo={false}
                        strokeWidth={3}
                      />
                      <span className="ai-repair-mini-result">
                        {repairingLocalCode ? `${localRepairProgress}%` : localRepairFeedback?.detail}
                      </span>
                    </div>
                  )}
                </section>
                <label className="field span-2">
                  <span>{zh.strategyNameInput}</span>
                  <Input value={manualStrategyName} onChange={(event) => setManualStrategyName(event.target.value)} placeholder="选择文件后自动使用文件名" />
                </label>
                {selectedLocalFile && (
                  <section className="field span-2">
                    <div className="field-head">
                      <span>代码预览</span>
                      <span className="meta-inline">{selectedLocalFile.aiRepaired ? "AI 修正版 · 本地原文件未修改" : selectedLocalFile.relativePath}</span>
                    </div>
                    <Input.TextArea rows={12} value={selectedLocalFile.code} readOnly />
                    {selectedLocalFile.aiRepaired && selectedLocalFile.repairWarnings?.length ? (
                      <span className="meta-inline">{selectedLocalFile.repairWarnings.join("；")}</span>
                    ) : null}
                  </section>
                )}
              </>
            )}

            <section className="pipeline-config-strip span-2">
              <div className="field-head pipeline-config-head">
                <span>{zh.backtestConfig}</span>
                <span className="meta-inline">仅支持单一标的</span>
              </div>
              <div className="pipeline-config-grid">
                <label className="field"><span>{zh.symbol}</span><AutoComplete value={vtSymbolInput} options={LAUNCH_SYMBOL_OPTIONS.map(({ value }) => ({ value }))} onChange={(value) => { setVtSymbolInput(value); const matched = LAUNCH_SYMBOL_OPTIONS.find((item) => item.value === value.trim().toUpperCase()); if (matched) setSlippage(matched.slippage); }} placeholder="SYMBOL.EXCHANGE" /></label>
                <label className="field"><span>{zh.interval}</span><Input value={interval} onChange={(event) => setInterval(event.target.value)} /></label>
                <label className="field"><span>{zh.rate}</span><InputNumber min={0} step={0.000001} value={rate} onChange={(value) => setRate(typeof value === "number" ? value : null)} /></label>
                <label className="field"><span>{zh.startDate}</span><Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
                <label className="field"><span>{zh.endDate}</span><Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
                <label className="field"><span>{zh.slippage}</span><InputNumber min={0} step={0.001} value={slippage} onChange={(value) => setSlippage(typeof value === "number" ? value : null)} /></label>
              </div>
            </section>

            {launchError && (
              <section className="band error-band span-2">
                <div className="band-head compact">
                  <div>
                    <h3>{zh.launchErrorTitle}</h3>
                    <p className="band-note">{launchError?.error || launchError?.generation?.error || launchError?.backtest?.error || "启动失败"}</p>
                  </div>
                  <span className="status-pill status-failed">失败</span>
                </div>
              </section>
            )}

            <div className="action-row span-2 launch-submit-row">
              <Button className="primary-button launch-submit-button" loading={loadingResearch} disabled={!canRunSource} onClick={runResearch}>{zh.startResearch}</Button>
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}

export default LaunchFlowPage;
