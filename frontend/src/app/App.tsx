import { memo, useCallback, useEffect, useRef, useState } from "react";
import { ConfigProvider, message } from "antd";
import { listPool, listTasks } from "../api";
import Sidebar from "../components/Sidebar";
import LaunchFlowPage from "../pages/LaunchFlowPage";
import StrategyGenerationPage from "../pages/StrategyGenerationPage";
import ParameterOptimizationPage from "../pages/ParameterOptimizationPage";
import PoolPage from "../pages/PoolPage";
import StrategyResearchPage from "../pages/StrategyResearchPage";
import {
  PAGE_STORAGE_KEY,
  PageKey,
  PoolNavigation,
  ResearchNavigation,
  TaskRunNavigation,
  WorkbenchTask,
  WorkflowUiState,
  loadInitialPage,
  taskTargetPage
} from "./shared";

const CachedLaunchFlowPage = memo(LaunchFlowPage);
const CachedStrategyGenerationPage = memo(StrategyGenerationPage);
const CachedParameterOptimizationPage = memo(ParameterOptimizationPage);
const CachedPoolPage = memo(PoolPage);
const CachedStrategyResearchPage = memo(StrategyResearchPage);

const APP_THEME = {
  token: {
    colorPrimary: "#17b8b1",
    colorText: "#202938",
    colorTextSecondary: "#667085",
    borderRadius: 8,
    controlHeight: 34,
    controlHeightSM: 30,
    fontSize: 14,
    lineHeight: 1.5,
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif'
  }
};

export default function App() {
  const [page, setPage] = useState<PageKey>(() => loadInitialPage());
  const [visitedPages, setVisitedPages] = useState<Set<PageKey>>(() => new Set([page]));
  const [taskRunNavigation, setTaskRunNavigation] = useState<TaskRunNavigation | null>(null);
  const taskNavigationSequenceRef = useRef(0);
  const [poolNavigation, setPoolNavigation] = useState<PoolNavigation | null>(null);
  const poolNavigationSequenceRef = useRef(0);
  const [researchNavigation, setResearchNavigation] = useState<ResearchNavigation | null>(null);
  const researchNavigationSequenceRef = useRef(0);
  const [tasks, setTasks] = useState<WorkbenchTask[]>([]);
  const [taskConnectionError, setTaskConnectionError] = useState(false);
  const [poolItems, setPoolItems] = useState<any[]>([]);
  const [lastResearch, setLastResearch] = useState<any>(null);
  const [lastGenerated, setLastGenerated] = useState<any>(null);
  const [workflowUi, setWorkflowUi] = useState<WorkflowUiState>({
    stageKey: "idle",
    message: "当前没有活动任务。",
    startedAt: "",
    isRunning: false,
    progress: 0,
    sourceFilename: "",
    downloadDiagnostics: null,
    error: null
  });
  const [displayWorkflowProgress, setDisplayWorkflowProgress] = useState(0);
  const displayWorkflowStartedAtRef = useRef("");

  const openPage = useCallback((nextPage: PageKey) => {
    setVisitedPages((current) => {
      if (current.has(nextPage)) return current;
      const next = new Set(current);
      next.add(nextPage);
      return next;
    });
    setPage(nextPage);
    if (nextPage === "generate") {
      window.requestAnimationFrame(() => {
        window.scrollTo({ top: 0, left: 0, behavior: "auto" });
      });
    }
  }, []);
  const openLaunchPage = useCallback(() => openPage("launch"), [openPage]);
  const openGenerationPage = useCallback(() => openPage("generate"), [openPage]);
  const openOptimizationPage = useCallback(() => openPage("optimize"), [openPage]);

  useEffect(() => {
    if (!workflowUi.startedAt) {
      displayWorkflowStartedAtRef.current = "";
      setDisplayWorkflowProgress(0);
      return;
    }
    const target = Math.max(0, Math.min(1, Number(workflowUi.progress || 0)));
    if (displayWorkflowStartedAtRef.current !== workflowUi.startedAt) {
      displayWorkflowStartedAtRef.current = workflowUi.startedAt;
      setDisplayWorkflowProgress(Math.min(0.05, target));
    }
    if (workflowUi.stageKey === "backtest" && target >= 0.65) {
      setDisplayWorkflowProgress((current) => Math.max(0.65, current));
    }
    if (!workflowUi.isRunning || target >= 1) {
      setDisplayWorkflowProgress(target);
      return;
    }
    const isWaitingForGenerationApi = workflowUi.stageKey === "generation" && target === 0.25;
    const timer = window.setInterval(() => {
      setDisplayWorkflowProgress((current) => {
        if (isWaitingForGenerationApi && current >= target) {
          return Math.min(0.45, current + 0.0025);
        }
        const distance = target - current;
        if (Math.abs(distance) < 0.003) return target;
        const step = Math.max(0.0025, Math.min(0.018, Math.abs(distance) * 0.1));
        return Math.max(0, Math.min(1, current + Math.sign(distance) * step));
      });
    }, isWaitingForGenerationApi ? 250 : 60);
    return () => window.clearInterval(timer);
  }, [workflowUi.isRunning, workflowUi.progress, workflowUi.stageKey, workflowUi.startedAt]);

  const refreshTasks = useCallback(async () => {
    try {
      const payload = await listTasks({ view: "recent", limit: 50 });
      setTasks(payload.tasks || []);
      setTaskConnectionError(false);
    } catch (error) {
      setTaskConnectionError(true);
      throw error;
    }
  }, []);

  const refreshPool = useCallback(async () => {
    const payload = await listPool();
    setPoolItems(payload.items || []);
  }, []);

  const navigateToOptimizationRun = useCallback((runId: string) => {
    const resolvedRunId = String(runId || "").trim();
    if (!resolvedRunId) return;
    taskNavigationSequenceRef.current += 1;
    setTaskRunNavigation({ runId: resolvedRunId, requestId: taskNavigationSequenceRef.current });
    openPage("optimize");
  }, [openPage]);

  const navigateToPool = useCallback((poolItemId: string, vtSymbol: string) => {
    poolNavigationSequenceRef.current += 1;
    setPoolNavigation({
      poolItemId: String(poolItemId || "").trim(),
      vtSymbol: String(vtSymbol || "").trim(),
      requestId: poolNavigationSequenceRef.current,
    });
    openPage("pool");
  }, [openPage]);

  const navigateToResearch = useCallback((poolItemId: string) => {
    const resolvedPoolItemId = String(poolItemId || "").trim();
    if (!resolvedPoolItemId) return;
    researchNavigationSequenceRef.current += 1;
    setResearchNavigation({ poolItemId: resolvedPoolItemId, requestId: researchNavigationSequenceRef.current });
    openPage("research");
  }, [openPage]);

  const navigateFromTask = useCallback((task: WorkbenchTask) => {
    const targetPage = taskTargetPage(task);
    const relatedRunId = String(task.related_run_id || "").trim();
    const relatedPoolItemId = String(task.related_pool_item_id || "").trim();
    if (targetPage === "research" && relatedPoolItemId) {
      navigateToResearch(relatedPoolItemId);
      return;
    }
    if (targetPage === "optimize" && relatedRunId) {
      navigateToOptimizationRun(relatedRunId);
      return;
    }
    openPage(targetPage);
  }, [navigateToOptimizationRun, navigateToResearch, openPage]);

  const handleTaskRunApplied = useCallback((requestId: number) => {
    setTaskRunNavigation((current) => current?.requestId === requestId ? null : current);
  }, []);

  const handlePoolNavigationApplied = useCallback((requestId: number) => {
    setPoolNavigation((current) => current?.requestId === requestId ? null : current);
  }, []);

  const handleResearchNavigationApplied = useCallback((requestId: number) => {
    setResearchNavigation((current) => current?.requestId === requestId ? null : current);
  }, []);

  const handleResearchCreated = useCallback((payload: any) => {
    setLastResearch(payload);
    refreshPool().catch((error) => message.error(String(error)));
  }, [refreshPool]);

  const handleGenerated = useCallback((payload: any) => {
    setLastGenerated(payload);
    setLastResearch(null);
  }, []);

  const handleWorkflowChange = useCallback((patch: Partial<WorkflowUiState>) => {
    setWorkflowUi((current) => ({ ...current, ...patch }));
  }, []);

  useEffect(() => {
    refreshTasks().catch((error) => message.error(String(error)));
    refreshPool().catch((error) => message.error(String(error)));
  }, []);

  const hasActiveTasks = tasks.some((task) => ["running", "queued"].includes(String(task.status).toLowerCase()));

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    const delay = hasActiveTasks ? 1000 : 10000;

    const schedule = () => {
      if (disposed || document.hidden) return;
      timer = window.setTimeout(async () => {
        try {
          await refreshTasks();
        } catch {
          // The status card exposes connection failures without repeated toast noise.
        }
        schedule();
      }, delay);
    };

    const handleVisibility = () => {
      if (timer) window.clearTimeout(timer);
      if (!document.hidden) {
        void refreshTasks().catch(() => undefined);
        schedule();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    schedule();
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [hasActiveTasks]);

  useEffect(() => {
    window.localStorage.setItem(PAGE_STORAGE_KEY, page);
  }, [page]);

  return (
    <ConfigProvider theme={APP_THEME}>
      <div className="shell">
        <Sidebar
          page={page}
          onPageChange={openPage}
          onTaskNavigate={navigateFromTask}
          tasks={tasks}
          onRefreshTasks={refreshTasks}
          taskConnectionError={taskConnectionError}
          workflowUi={workflowUi}
          workflowProgress={displayWorkflowProgress}
        />
        <main className="workspace">
          {visitedPages.has("launch") && (
            <div hidden={page !== "launch"}>
              <CachedLaunchFlowPage
                onResearchCreated={handleResearchCreated}
                onGenerated={handleGenerated}
                onOpenGenerated={openGenerationPage}
                onWorkflowChange={handleWorkflowChange}
                refreshTasks={refreshTasks}
              />
            </div>
          )}
          {visitedPages.has("generate") && (
            <div hidden={page !== "generate"}>
              <CachedStrategyGenerationPage
                lastGenerated={lastGenerated}
                lastResearch={lastResearch}
                workflowUi={workflowUi}
                workflowProgress={displayWorkflowProgress}
                onBackLaunch={openLaunchPage}
                onGoOptimize={openOptimizationPage}
              />
            </div>
          )}
          {visitedPages.has("optimize") && (
            <div hidden={page !== "optimize"}>
              <CachedParameterOptimizationPage
                lastResearch={lastResearch}
                taskRunNavigation={taskRunNavigation}
                onTaskRunApplied={handleTaskRunApplied}
                refreshPool={refreshPool}
                refreshTasks={refreshTasks}
                onOpenPool={navigateToPool}
              />
            </div>
          )}
          {visitedPages.has("pool") && (
            <div hidden={page !== "pool"}>
              <CachedPoolPage poolItems={poolItems} poolNavigation={poolNavigation} onPoolNavigationApplied={handlePoolNavigationApplied} refreshPool={refreshPool} refreshTasks={refreshTasks} onContinueOptimization={navigateToOptimizationRun} onOpenResearch={navigateToResearch} />
            </div>
          )}
          {visitedPages.has("research") && (
            <div hidden={page !== "research"}>
              <CachedStrategyResearchPage
                poolItems={poolItems}
                navigation={researchNavigation}
                onNavigationApplied={handleResearchNavigationApplied}
                refreshTasks={refreshTasks}
              />
            </div>
          )}
        </main>
      </div>
    </ConfigProvider>
  );
}
