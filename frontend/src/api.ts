// Production uses the current origin and lets the web server proxy /api.
// Set VITE_API_BASE_URL only when the API intentionally lives on another origin.
const API_BASE_URL = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

const RETRY_DELAYS_MS = [150, 300, 600, 1000, 1500];

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}

async function fetchWithReloadRetry(url: string, init?: RequestInit): Promise<Response> {
  const method = String(init?.method || "GET").toUpperCase();
  const retryable = method === "GET" || method === "HEAD";
  let lastError: unknown;

  for (let attempt = 0; attempt <= (retryable ? RETRY_DELAYS_MS.length : 0); attempt += 1) {
    try {
      const response = await fetch(url, init);
      const transientStatus = response.status === 500 || response.status === 502 || response.status === 503 || response.status === 504;
      if (!retryable || !transientStatus || attempt === RETRY_DELAYS_MS.length) {
        return response;
      }
    } catch (error) {
      lastError = error;
      if (!retryable || init?.signal?.aborted || attempt === RETRY_DELAYS_MS.length) {
        throw error;
      }
    }
    await wait(RETRY_DELAYS_MS[attempt]);
  }

  throw lastError instanceof Error ? lastError : new Error("API request failed during backend reload");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithReloadRetry(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    ...init
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload?.error?.message
      || (typeof payload?.error === "string" ? payload.error : "")
      || payload?.detail?.message
      || (typeof payload?.detail === "string" ? payload.detail : "")
      || payload?.message
      || response.statusText
      || `API 请求失败（HTTP ${response.status}）`;
    throw new Error(String(message));
  }
  return payload as T;
}

export function generateStrategy(sourceFilename: string) {
  return request<any>("/api/strategies/generate", {
    method: "POST",
    body: JSON.stringify({ source_filename: sourceFilename })
  });
}

export function repairStrategyCode(payload: {
  strategy_name: string;
  strategy_code: string;
  vt_symbol?: string;
  interval?: string;
}) {
  return request<any>("/api/strategies/repair", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createStrategyInitialReview(runId: string, forceRefresh = false) {
  return request<any>("/api/strategies/initial-review", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, force_refresh: forceRefresh })
  });
}

export type ResearchCreatePayload = {
  source_filename: string;
  symbol: string;
  exchange: string;
  interval: string;
  start_date?: string;
  end_date?: string;
  capital?: number;
  rate?: number;
  slippage?: number;
  size?: number;
  pricetick?: number;
  mode?: "real" | "mock";
};

export type DataDownloadPayload = {
  symbol: string;
  exchange: string;
  interval: string;
  start_date: string;
  end_date: string;
};

export function createResearch(payload: ResearchCreatePayload) {
  return request<any>("/api/research/create", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export type ResearchBaselinePayload = {
  strategy_id: string;
  symbol: string;
  exchange: string;
  interval: string;
  start_date?: string;
  end_date?: string;
  capital?: number;
  rate?: number;
  slippage?: number;
  size?: number;
  pricetick?: number;
  mode?: "real" | "mock";
};

export function createResearchBaseline(payload: ResearchBaselinePayload) {
  return request<any>("/api/research/baseline", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export type ResearchCodeBaselinePayload = {
  strategy_name: string;
  strategy_code: string;
  symbol: string;
  exchange: string;
  interval: string;
  start_date?: string;
  end_date?: string;
  capital?: number;
  rate?: number;
  slippage?: number;
  size?: number;
  pricetick?: number;
  mode?: "real" | "mock";
};

export function createResearchBaselineFromCode(payload: ResearchCodeBaselinePayload) {
  return request<any>("/api/research/baseline-from-code", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getDataCoverage(symbol: string, exchange: string, interval: string, startDate?: string, endDate?: string) {
  const params = new URLSearchParams({ symbol, exchange, interval });
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  return request<any>(`/api/data/coverage?${params.toString()}`);
}

export function downloadData(payload: DataDownloadPayload) {
  return request<any>("/api/data/download", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listDataSymbols() {
  return request<any>("/api/data/symbols");
}

export function listNaturalLanguageSources() {
  return request<any>("/api/natural-language/sources");
}

export function getNaturalLanguageSource(filename: string) {
  return request<any>(`/api/natural-language/sources/${encodeURIComponent(filename)}`);
}

export function createNaturalLanguageSource(filename: string, text: string) {
  return request<any>("/api/natural-language/sources", {
    method: "POST",
    body: JSON.stringify({ filename, text })
  });
}

export function updateNaturalLanguageSource(filename: string, text: string) {
  return request<any>(`/api/natural-language/sources/${encodeURIComponent(filename)}`, {
    method: "PUT",
    body: JSON.stringify({ text })
  });
}

export function getRun(runId: string) {
  return request<any>(`/api/runs/${encodeURIComponent(runId)}`);
}

export function listRuns(limit = 50) {
  return request<any>(`/api/runs?limit=${encodeURIComponent(String(limit))}`);
}

export function getVariantCurve(runId: string, variantName: string) {
  return request<any>(`/api/runs/${encodeURIComponent(runId)}/variants/${encodeURIComponent(variantName)}/curve`);
}

export function getGridCandidateCurve(runId: string, variantName: string, candidateLabel: string) {
  return request<any>(`/api/runs/${encodeURIComponent(runId)}/variants/${encodeURIComponent(variantName)}/candidates/${encodeURIComponent(candidateLabel)}/curve`);
}

export function addToPool(runId: string, variantName = "baseline", vtSymbol?: string, strategyName?: string, note?: string, candidateLabel?: string) {
  return request<any>("/api/pool/add", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, variant_name: variantName, candidate_label: candidateLabel, vt_symbol: vtSymbol, strategy_name: strategyName, note, tags: ["frontend"] })
  });
}

export function listPool() {
  return request<any>("/api/pool", { cache: "no-store" });
}

export function getPoolItem(poolItemId: string) {
  return request<any>(`/api/pool/${encodeURIComponent(poolItemId)}`);
}

export function continuePoolOptimization(poolItemId: string) {
  return request<any>(`/api/pool/${encodeURIComponent(poolItemId)}/continue-optimization`, {
    method: "POST"
  });
}

export function updatePoolNotes(poolItemId: string, note: string) {
  return request<any>(`/api/pool/${encodeURIComponent(poolItemId)}/notes`, {
    method: "PATCH",
    body: JSON.stringify({ note })
  });
}

export function getPoolCurve(poolItemId: string) {
  return request<any>(`/api/pool/${encodeURIComponent(poolItemId)}/curve`);
}

export function getPoolResearchContext(poolItemId: string) {
  return request<any>(`/api/strategy-research/pool/${encodeURIComponent(poolItemId)}/context`, { cache: "no-store" });
}

export function createPoolResearchAiOverview(poolItemId: string, forceRefresh = false) {
  return request<any>(
    `/api/strategy-research/pool/${encodeURIComponent(poolItemId)}/ai-overview?force_refresh=${forceRefresh ? "true" : "false"}`,
    { method: "POST" }
  );
}

export function runPoolResearchHeatmap(poolItemId: string, payload: {
  x_parameter: string;
  y_parameter: string;
  parameter_ranges: Record<string, { low: number; high: number; step: number }>;
  objective: "excess_return" | "sharpe";
  max_trials?: number;
}) {
  return request<any>(`/api/strategy-research/pool/${encodeURIComponent(poolItemId)}/heatmap`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function runPoolResearchWalkForward(poolItemId: string, payload: {
  training_start_date: string;
  training_months: number;
  test_months: 6;
  selected_parameters: string[];
  parameter_ranges: Record<string, { low: number; high: number; step: number }>;
  objective: "sharpe";
  max_trials?: number;
}) {
  return request<any>(`/api/strategy-research/pool/${encodeURIComponent(poolItemId)}/walk-forward`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function runPoolWalkForwardRankAnalysis(poolItemId: string, experimentId: string) {
  return request<any>(`/api/strategy-research/pool/${encodeURIComponent(poolItemId)}/walk-forward/${encodeURIComponent(experimentId)}/rank-analysis`, {
    method: "POST"
  });
}

export function comparePool(poolItemIds: string[]) {
  return request<any>("/api/pool/compare", {
    method: "POST",
    body: JSON.stringify({ pool_item_ids: poolItemIds })
  });
}

export function rerunPool(poolItemIds: string[], startDate: string, endDate?: string) {
  return request<any>("/api/pool/rerun", {
    method: "POST",
    body: JSON.stringify({ pool_item_ids: poolItemIds, start_date: startDate, end_date: endDate })
  });
}

export function removeFromPool(poolItemId: string) {
  return request<any>(`/api/pool/${encodeURIComponent(poolItemId)}`, {
    method: "DELETE"
  });
}

export type PortfolioSavePayload = {
  name: string;
  description?: string;
  virtual_capital: number;
  start_date?: string;
  end_date?: string;
  components: Array<{ pool_item_id: string; weight: number }>;
};

export function listPortfolios(includeArchived = false) {
  return request<any>(`/api/portfolios?include_archived=${includeArchived ? "true" : "false"}`, { cache: "no-store" });
}

export function getPortfolio(portfolioId: string) {
  return request<any>(`/api/portfolios/${encodeURIComponent(portfolioId)}`, { cache: "no-store" });
}

export function createPortfolio(payload: PortfolioSavePayload) {
  return request<any>("/api/portfolios", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updatePortfolio(portfolioId: string, payload: PortfolioSavePayload) {
  return request<any>(`/api/portfolios/${encodeURIComponent(portfolioId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function refreshPortfolio(portfolioId: string) {
  return request<any>(`/api/portfolios/${encodeURIComponent(portfolioId)}/refresh`, { method: "POST" });
}

export function archivePortfolio(portfolioId: string) {
  return request<any>(`/api/portfolios/${encodeURIComponent(portfolioId)}/archive`, { method: "POST" });
}

export function getLiveLocalStatus() {
  return request<any>("/api/live/local-status", { cache: "no-store" });
}

export function getLivePriceBars(symbol: string, day: string) {
  return request<any>(`/api/live/price-bars?vt_symbol=${encodeURIComponent(symbol)}&trade_date=${encodeURIComponent(day)}`);
}

export function getLiveAutomationStatus() {
  return request<any>("/api/live/automation-status", { cache: "no-store" });
}

export function listLiveSources() {
  return request<any>("/api/live/sources", { cache: "no-store" });
}

export function createLiveSource(payload: { trade_date: string; name?: string }) {
  return request<any>("/api/live/sources", { method: "POST", body: JSON.stringify(payload) });
}

export function getLiveSource(sourceId: string) {
  return request<any>(`/api/live/sources/${encodeURIComponent(sourceId)}`, { cache: "no-store" });
}

export function deleteLiveSource(sourceId: string) {
  return request<any>(`/api/live/sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" });
}

export function importLiveSnapshot(sourceId: string, tradeDate: string) {
  return request<any>(`/api/live/sources/${encodeURIComponent(sourceId)}/snapshots`, {
    method: "POST",
    body: JSON.stringify({ trade_date: tradeDate })
  });
}

export function trackLiveDay(sourceId: string, tradeDate: string, updateData = true) {
  return request<any>(`/api/live/sources/${encodeURIComponent(sourceId)}/track`, {
    method: "POST",
    body: JSON.stringify({ trade_date: tradeDate, update_data: updateData })
  });
}

export function getLiveRecord(sourceId: string, tradeDate: string) {
  return request<any>(
    `/api/live/sources/${encodeURIComponent(sourceId)}/records/${encodeURIComponent(tradeDate)}`,
    { cache: "no-store" }
  );
}

export async function downloadPortfolioCsv(portfolioId: string, filename: string) {
  const response = await fetchWithReloadRetry(`${API_BASE_URL}/api/portfolios/${encodeURIComponent(portfolioId)}/export`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(String(payload?.error?.message || payload?.detail || response.statusText));
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export function listTasks(options: { view?: "active" | "recent" | "archived" | "all"; status?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  params.set("view", options.view || "recent");
  params.set("limit", String(options.limit || 50));
  if (options.status) params.set("status", options.status);
  return request<any>(`/api/tasks?${params.toString()}`);
}

export function archiveTerminalTasks() {
  return request<any>("/api/tasks/archive", {
    method: "POST",
    body: JSON.stringify({ scope: "terminal" })
  });
}

export function getOptimizationMethods() {
  return request<any>("/api/optimization/methods");
}

export function getOptimizationSearchSpace(runId: string, variantName = "baseline") {
  return request<any>("/api/optimization/search-space", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, variant_name: variantName })
  });
}

export function suggestOptimizationSearchSpace(runId: string, variantName = "baseline", forceRefresh = false) {
  return request<any>("/api/optimization/suggest-space", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, variant_name: variantName, options: { force_refresh: forceRefresh } })
  });
}

export function runOptimization(payload: any) {
  return request<any>("/api/optimization/run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listOptimizationCurveSnapshots() {
  return request<any>("/api/optimization/curve-snapshots", { cache: "no-store" });
}

export function createOptimizationCurveSnapshot(runId: string, variantName: string, name: string) {
  return request<any>("/api/optimization/curve-snapshots", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, variant_name: variantName, name })
  });
}

export function renameOptimizationCurveSnapshot(snapshotId: string, name: string) {
  return request<any>(`/api/optimization/curve-snapshots/${encodeURIComponent(snapshotId)}`, {
    method: "PATCH",
    body: JSON.stringify({ name })
  });
}

export function deleteOptimizationCurveSnapshot(snapshotId: string) {
  return request<any>(`/api/optimization/curve-snapshots/${encodeURIComponent(snapshotId)}`, {
    method: "DELETE"
  });
}
