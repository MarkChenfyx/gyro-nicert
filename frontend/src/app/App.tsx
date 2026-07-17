import { useEffect, useRef, useState } from "react";
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

export default function App() {
  const [page, setPage] = useState<PageKey>(() => loadInitialPage());
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

  async function refreshTasks() {
    try {
      const payload = await listTasks({ view: "recent", limit: 50 });
      setTasks(payload.tasks || []);
      setTaskConnectionError(false);
    } catch (error) {
      setTaskConnectionError(true);
      throw error;
    }
  }

  async function refreshPool() {
    const payload = await listPool();
    setPoolItems(payload.items || []);
  }

  function navigateToOptimizationRun(runId: string) {
    const resolvedRunId = String(runId || "").trim();
    if (!resolvedRunId) return;
    taskNavigationSequenceRef.current += 1;
    setTaskRunNavigation({ runId: resolvedRunId, requestId: taskNavigationSequenceRef.current });
    setPage("optimize");
  }

  function navigateToPool(poolItemId: string, vtSymbol: string) {
    poolNavigationSequenceRef.current += 1;
    setPoolNavigation({
      poolItemId: String(poolItemId || "").trim(),
      vtSymbol: String(vtSymbol || "").trim(),
      requestId: poolNavigationSequenceRef.current,
    });
    setPage("pool");
  }

  function navigateFromTask(task: WorkbenchTask) {
    const targetPage = taskTargetPage(task);
    const relatedRunId = String(task.related_run_id || "").trim();
    const relatedPoolItemId = String(task.related_pool_item_id || "").trim();
    if (targetPage === "research" && relatedPoolItemId) {
      researchNavigationSequenceRef.current += 1;
      setResearchNavigation({ poolItemId: relatedPoolItemId, requestId: researchNavigationSequenceRef.current });
      setPage("research");
      return;
    }
    if (targetPage === "optimize" && relatedRunId) {
      navigateToOptimizationRun(relatedRunId);
      return;
    }
    setPage(targetPage);
  }

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
    <ConfigProvider
      theme={{
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
      }}
    >
      <div className="shell">
        <Sidebar
          page={page}
          onPageChange={setPage}
          onTaskNavigate={navigateFromTask}
          tasks={tasks}
          onRefreshTasks={refreshTasks}
          taskConnectionError={taskConnectionError}
          workflowUi={workflowUi}
          workflowProgress={displayWorkflowProgress}
        />
        <main className="workspace">
          {page === "launch" && (
            <LaunchFlowPage
              onResearchCreated={(payload) => {
                setLastResearch(payload);
                refreshPool().catch((error) => message.error(String(error)));
              }}
              onGenerated={(payload) => {
                setLastGenerated(payload);
                setLastResearch(null);
              }}
              onOpenGenerated={() => setPage("generate")}
              onWorkflowChange={(patch) => setWorkflowUi((current) => ({ ...current, ...patch }))}
              refreshTasks={refreshTasks}
            />
          )}
          {page === "generate" && (
            <StrategyGenerationPage
              lastGenerated={lastGenerated}
              lastResearch={lastResearch}
              workflowUi={workflowUi}
              workflowProgress={displayWorkflowProgress}
              onBackLaunch={() => setPage("launch")}
              onGoOptimize={() => setPage("optimize")}
            />
          )}
          {page === "optimize" && (
            <ParameterOptimizationPage
              lastResearch={lastResearch}
              taskRunNavigation={taskRunNavigation}
              onTaskRunApplied={(requestId) => setTaskRunNavigation((current) => current?.requestId === requestId ? null : current)}
              refreshPool={refreshPool}
              refreshTasks={refreshTasks}
              onOpenPool={navigateToPool}
            />
          )}
          {page === "pool" && <PoolPage poolItems={poolItems} poolNavigation={poolNavigation} onPoolNavigationApplied={(requestId) => setPoolNavigation((current) => current?.requestId === requestId ? null : current)} refreshPool={refreshPool} refreshTasks={refreshTasks} onContinueOptimization={navigateToOptimizationRun} />}
          {page === "research" && (
            <StrategyResearchPage
              poolItems={poolItems}
              navigation={researchNavigation}
              onNavigationApplied={(requestId) => setResearchNavigation((current) => current?.requestId === requestId ? null : current)}
              refreshTasks={refreshTasks}
            />
          )}
        </main>
      </div>
    </ConfigProvider>
  );
}
