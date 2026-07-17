import React, { useMemo, useState } from "react";
import { Button, Drawer, message } from "antd";
import { archiveTerminalTasks, listTasks } from "../api";
import {
  PageKey,
  TaskView,
  WorkbenchTask,
  WorkflowUiState,
  elapsedLabel,
  formatDate,
  mergeRecentResearchTasks,
  statusClass,
  taskDateGroup,
  taskDisplayLabel,
  taskProgress,
  taskSourceIdentity,
  taskStatusLabel,
  taskSummary,
  zh
} from "../app/shared";

export function Sidebar({
  page,
  onPageChange,
  onTaskNavigate,
  tasks,
  onRefreshTasks,
  taskConnectionError,
  workflowUi,
  workflowProgress
}: {
  page: PageKey;
  onPageChange: (page: PageKey) => void;
  onTaskNavigate: (task: WorkbenchTask) => void;
  tasks: WorkbenchTask[];
  onRefreshTasks: () => Promise<void>;
  taskConnectionError: boolean;
  workflowUi: WorkflowUiState;
  workflowProgress: number;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTasks, setDrawerTasks] = useState<WorkbenchTask[]>([]);
  const [taskFilter, setTaskFilter] = useState<TaskView>("all");
  const [selectedTask, setSelectedTask] = useState<WorkbenchTask | null>(null);
  const [loadingDrawer, setLoadingDrawer] = useState(false);
  const mergedTasks = useMemo(() => mergeRecentResearchTasks(tasks), [tasks]);
  const liveWorkflowTask = useMemo<WorkbenchTask | null>(() => {
    if (!workflowUi.isRunning || !workflowUi.startedAt) return null;
    const sourceFilename = String(workflowUi.sourceFilename || "").trim();
    const matchingTask = tasks.find((task) => {
      if (task.task_type !== "strategy_generation") return false;
      if (sourceFilename && taskSourceIdentity(task) !== sourceFilename) return false;
      return new Date(task.created_at).getTime() >= new Date(workflowUi.startedAt).getTime() - 5000;
    });
    return {
      task_id: matchingTask?.task_id || `live-research-${workflowUi.startedAt}`,
      task_type: "research_workflow",
      status: "running",
      progress: workflowProgress,
      message: workflowUi.message,
      source_filename: sourceFilename,
      related_strategy_id: matchingTask?.related_strategy_id,
      created_at: workflowUi.startedAt,
      updated_at: matchingTask?.updated_at || workflowUi.startedAt
    };
  }, [tasks, workflowProgress, workflowUi.isRunning, workflowUi.message, workflowUi.sourceFilename, workflowUi.startedAt]);
  const displayTasks = useMemo(() => {
    if (!liveWorkflowTask) return mergedTasks;
    const liveSource = taskSourceIdentity(liveWorkflowTask);
    const liveStart = new Date(liveWorkflowTask.created_at).getTime();
    return [
      liveWorkflowTask,
      ...mergedTasks.filter((task) => {
        if (task.task_id === liveWorkflowTask.task_id) return false;
        if (!liveSource || taskSourceIdentity(task) !== liveSource) return true;
        const taskTime = new Date(task.created_at).getTime();
        return !Number.isFinite(taskTime) || taskTime < liveStart - 5000;
      })
    ];
  }, [liveWorkflowTask, mergedTasks]);
  const activeTasks = displayTasks.filter((task) => ["running", "queued"].includes(String(task.status).toLowerCase()));
  const activeTaskIds = new Set(activeTasks.map((task) => task.task_id));
  const visibleTasks = [
    ...activeTasks,
    ...displayTasks.filter((task) => !activeTaskIds.has(task.task_id))
  ].slice(0, 5);

  async function loadDrawerTasks(filter: TaskView = taskFilter) {
    setLoadingDrawer(true);
    try {
      const view = filter === "archived" ? "archived" : "all";
      const payload = await listTasks({ view, limit: 300 });
      const rows = (payload.tasks || []) as WorkbenchTask[];
      const filtered = filter === "active"
        ? rows.filter((task) => ["running", "queued"].includes(String(task.status)) && !task.archived_at)
        : filter === "failed"
          ? rows.filter((task) => task.status === "failed" && !task.archived_at)
          : filter === "completed"
            ? rows.filter((task) => ["completed", "cancelled"].includes(String(task.status)) && !task.archived_at)
            : filter === "archived"
              ? rows.filter((task) => Boolean(task.archived_at))
              : rows.filter((task) => !task.archived_at);
      setDrawerTasks(filtered);
      setSelectedTask((current) => filtered.find((task) => task.task_id === current?.task_id) || filtered[0] || null);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingDrawer(false);
    }
  }

  function openTaskDrawer(task?: WorkbenchTask) {
    setSelectedTask(task || null);
    setDrawerOpen(true);
    void loadDrawerTasks(taskFilter);
  }

  async function archiveEndedTasks() {
    try {
      const payload = await archiveTerminalTasks();
      await onRefreshTasks();
      await loadDrawerTasks(taskFilter);
      message.success(`已归档 ${Number(payload.archived_count || 0)} 条结束任务`);
    } catch (error) {
      message.error(String(error));
    }
  }

  function navigateFromTask(task: WorkbenchTask) {
    onTaskNavigate(task);
    setDrawerOpen(false);
  }

  const groupedTasks = ["今天", "昨天", "更早"].map((label) => ({
    label,
    tasks: drawerTasks.filter((task) => taskDateGroup(task) === label)
  })).filter((group) => group.tasks.length);

  return (
    <aside className="sidebar">
      <div className="brand-block">
        <p className="eyebrow">GYRO_NICERT</p>
        <h1>{zh.workbench}</h1>
        <p className="sidebar-copy">{zh.subtitle}</p>
      </div>

      <section className="sidebar-section nav-section">
        {[
          ["launch", zh.launchFlow],
          ["generate", zh.generate],
          ["optimize", zh.optimize],
          ["pool", zh.pool],
          ["research", zh.research]
        ].map(([key, label]) => (
          <button key={key} type="button" className={`nav-button ${page === key ? "is-active" : ""}`} onClick={() => onPageChange(key as PageKey)}>
            {label}
          </button>
        ))}
      </section>

      <section className="sidebar-section jobs-section">
        <div className="section-head">
          <h2>{zh.recentTasks}</h2>
          <div className="jobs-head-actions">
            <span>{visibleTasks.length}</span>
            <button className="mini-button" type="button" onClick={() => openTaskDrawer()}>查看全部</button>
          </div>
        </div>
        <div className="jobs-rail">
          {visibleTasks.length ? (
            visibleTasks.map((task) => (
              <button className="rail-job task-row-button" type="button" key={task.task_id} onClick={() => openTaskDrawer(task)}>
                <div className="rail-job-head">
                  <strong>{taskDisplayLabel(task)}</strong>
                  <span className={statusClass(task.status)}>{taskStatusLabel(task.status)}</span>
                </div>
                <div className="mini-progress">
                  <span style={{ width: `${taskProgress(task)}%` }} />
                </div>
                <span className="rail-job-meta">{taskSummary(task)}</span>
                <span className="rail-job-time">{formatDate(task.updated_at)}</span>
              </button>
            ))
          ) : (
            <div className="rail-job muted-card">
              <span className="rail-job-meta">当前没有可见任务。</span>
            </div>
          )}
        </div>
      </section>

      <Drawer
        title="任务中心"
        placement="right"
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={<Button size="small" onClick={archiveEndedTasks}>归档已结束</Button>}
      >
        <div className="task-drawer-layout" aria-busy={loadingDrawer}>
          <div className="task-filter-row">
            {([
              ["all", "全部"], ["active", "进行中"], ["failed", "失败"], ["completed", "已完成"], ["archived", "已归档"]
            ] as Array<[TaskView, string]>).map(([key, label]) => (
              <button
                type="button"
                key={key}
                className={`mini-button ${taskFilter === key ? "is-active" : ""}`}
                onClick={() => { setTaskFilter(key); void loadDrawerTasks(key); }}
              >{label}</button>
            ))}
          </div>
          <div className="task-drawer-body">
            <div className="task-history-list">
              {groupedTasks.length ? groupedTasks.map((group) => (
                <section className="task-history-group" key={group.label}>
                  <h3>{group.label}</h3>
                  {group.tasks.map((task) => (
                    <button type="button" className={`task-history-item ${selectedTask?.task_id === task.task_id ? "is-active" : ""}`} key={task.task_id} onClick={() => setSelectedTask(task)}>
                      <span><strong>{taskDisplayLabel(task)}</strong><small>{formatDate(task.created_at)}</small></span>
                      <span className={statusClass(task.status)}>{taskStatusLabel(task.status)}</span>
                    </button>
                  ))}
                </section>
              )) : <div className="empty-state">当前筛选下没有任务。</div>}
            </div>
            <div className="task-detail-panel">
              {selectedTask ? (
                <>
                  <div className="task-detail-head"><div><span className="summary-label">任务详情</span><h3>{taskDisplayLabel(selectedTask)}</h3></div><span className={statusClass(selectedTask.status)}>{taskStatusLabel(selectedTask.status)}</span></div>
                  <div className="mini-progress"><span style={{ width: `${taskProgress(selectedTask)}%` }} /></div>
                  <dl className="task-detail-grid">
                    <div><dt>进度</dt><dd>{Math.round(taskProgress(selectedTask))}%</dd></div>
                    <div><dt>耗时</dt><dd>{elapsedLabel(selectedTask)}</dd></div>
                    <div><dt>创建时间</dt><dd>{formatDate(selectedTask.created_at)}</dd></div>
                    <div><dt>更新时间</dt><dd>{formatDate(selectedTask.updated_at)}</dd></div>
                    {(["running", "queued", "failed"].includes(String(selectedTask.status)) || selectedTask.error) && <div className="span-2"><dt>{selectedTask.error ? "错误信息" : "当前阶段"}</dt><dd>{selectedTask.error || selectedTask.message || "-"}</dd></div>}
                    {selectedTask.related_run_id && <div className="span-2"><dt>关联运行版本</dt><dd>{selectedTask.related_run_id}</dd></div>}
                    {selectedTask.related_strategy_id && <div className="span-2"><dt>关联策略</dt><dd>{selectedTask.related_strategy_id}</dd></div>}
                    {selectedTask.related_pool_item_id && <div className="span-2"><dt>关联策略池</dt><dd>{selectedTask.related_pool_item_id}</dd></div>}
                  </dl>
                  {(selectedTask.status === "failed" || selectedTask.related_run_id || selectedTask.related_pool_item_id) && (
                    <Button type="primary" onClick={() => navigateFromTask(selectedTask)}>
                      {selectedTask.status === "failed" ? "返回对应页面重新配置" : "查看关联结果"}
                    </Button>
                  )}
                </>
              ) : <div className="empty-state">请选择一个任务查看详情。</div>}
            </div>
          </div>
        </div>
      </Drawer>
    </aside>
  );
}

export default Sidebar;
