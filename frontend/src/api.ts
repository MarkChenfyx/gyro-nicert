const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    ...init
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload?.error?.message || payload?.detail || response.statusText;
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

export function addToPool(runId: string, variantName = "baseline", vtSymbol?: string, strategyName?: string, note?: string) {
  return request<any>("/api/pool/add", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, variant_name: variantName, vt_symbol: vtSymbol, strategy_name: strategyName, note, tags: ["frontend"] })
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
