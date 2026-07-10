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

export function listRuns(limit = 100) {
  return request<any>(`/api/runs?limit=${encodeURIComponent(String(limit))}`);
}

export function getVariantCurve(runId: string, variantName: string) {
  return request<any>(`/api/runs/${encodeURIComponent(runId)}/variants/${encodeURIComponent(variantName)}/curve`);
}

export function addToPool(runId: string, variantName = "baseline", vtSymbol?: string) {
  return request<any>("/api/pool/add", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, variant_name: variantName, vt_symbol: vtSymbol, tags: ["frontend"] })
  });
}

export function listPool() {
  return request<any>("/api/pool");
}

export function getPoolItem(poolItemId: string) {
  return request<any>(`/api/pool/${encodeURIComponent(poolItemId)}`);
}

export function getPoolCurve(poolItemId: string) {
  return request<any>(`/api/pool/${encodeURIComponent(poolItemId)}/curve`);
}

export function comparePool(poolItemIds: string[]) {
  return request<any>("/api/pool/compare", {
    method: "POST",
    body: JSON.stringify({ pool_item_ids: poolItemIds })
  });
}

export function rerunPool(poolItemIds: string[], endDate?: string) {
  return request<any>("/api/pool/rerun", {
    method: "POST",
    body: JSON.stringify({ pool_item_ids: poolItemIds, end_date: endDate })
  });
}

export function listTasks() {
  return request<any>("/api/tasks");
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

export function runOptimization(payload: any) {
  return request<any>("/api/optimization/run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
