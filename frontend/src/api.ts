import type { AnalysisData, Dataset, ReviewData, StrategySummary } from "./types";

const API = "/api";
const responseCache = new Map<string, { expiresAt: number; value: unknown }>();
const pendingRequests = new Map<string, Promise<unknown>>();
let cacheGeneration = 0;

function readCache<T>(key: string): T | null {
  const cached = responseCache.get(key);
  if (!cached) return null;
  if (cached.expiresAt <= Date.now()) {
    responseCache.delete(key);
    return null;
  }
  return cached.value as T;
}

async function cachedRequest<T>(path: string, ttlMs: number): Promise<T> {
  const cached = readCache<T>(path);
  if (cached !== null) return cached;

  const pending = pendingRequests.get(path);
  if (pending) return pending as Promise<T>;

  const generation = cacheGeneration;
  const task = request<T>(path)
    .then((value) => {
      if (generation === cacheGeneration) {
        responseCache.set(path, { expiresAt: Date.now() + ttlMs, value });
      }
      return value;
    })
    .finally(() => {
      if (pendingRequests.get(path) === task) pendingRequests.delete(path);
    });
  pendingRequests.set(path, task);
  return task;
}

function clearResearchCache() {
  cacheGeneration += 1;
  for (const key of responseCache.keys()) {
    if (
      key === "/workspace" ||
      key.includes("/review?") ||
      key.includes("/analysis?") ||
      key.includes("/versions?")
    ) {
      responseCache.delete(key);
    }
  }
  for (const key of pendingRequests.keys()) {
    if (
      key === "/workspace" ||
      key.includes("/review?") ||
      key.includes("/analysis?") ||
      key.includes("/versions?")
    ) {
      pendingRequests.delete(key);
    }
  }
}

function reviewPath(datasetId: number, indicator: string, signalId?: number) {
  return `/datasets/${datasetId}/review?indicator=${encodeURIComponent(indicator)}${
    signalId ? `&signal_id=${signalId}` : ""
  }`;
}

function analysisPath(datasetId: number, indicator: string) {
  return `/datasets/${datasetId}/analysis?indicator=${encodeURIComponent(indicator)}`;
}

function versionsPath(datasetId: number, root: string) {
  return `/datasets/${datasetId}/versions?root=${encodeURIComponent(root)}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || "操作失敗，請稍後再試。");
  }
  return response.json() as Promise<T>;
}

export const api = {
  workspace: () => cachedRequest<{ datasets: Dataset[] }>("/workspace", 10_000),
  review: (datasetId: number, indicator: string, signalId?: number) =>
    cachedRequest<ReviewData>(reviewPath(datasetId, indicator, signalId), 30_000),
  peekReview: (datasetId: number, indicator: string, signalId?: number) =>
    readCache<ReviewData>(reviewPath(datasetId, indicator, signalId)),
  primeReview: (datasetId: number, indicator: string, value: ReviewData) => {
    const expiresAt = Date.now() + 30_000;
    responseCache.set(reviewPath(datasetId, indicator), { expiresAt, value });
    responseCache.set(reviewPath(datasetId, indicator, value.selected.id), { expiresAt, value });
  },
  label: async (
    signalId: number,
    label: string,
    settings: { notes: string; bars_held: number; context_before: number; context_after: number },
  ) => {
    const result = await request(`/signals/${signalId}/label`, {
      method: "PUT",
      body: JSON.stringify({ label, ...settings }),
    });
    clearResearchCache();
    return result;
  },
  undoLabel: async (signalId: number) => {
    const result = await request(`/signals/${signalId}/label`, { method: "DELETE" });
    clearResearchCache();
    return result;
  },
  analysis: (datasetId: number, indicator: string) =>
    cachedRequest<AnalysisData>(analysisPath(datasetId, indicator), 60_000),
  peekAnalysis: (datasetId: number, indicator: string) =>
    readCache<AnalysisData>(analysisPath(datasetId, indicator)),
  improve: async (datasetId: number, indicator: string, forceNew = false) => {
    const result = await request<Record<string, unknown>>(`/datasets/${datasetId}/improve`, {
      method: "POST",
      body: JSON.stringify({ indicator_name: indicator, force_new: forceNew }),
    });
    clearResearchCache();
    return result;
  },
  versions: (datasetId: number, root: string) =>
    cachedRequest<{ versions: StrategySummary[] }>(versionsPath(datasetId, root), 60_000),
  peekVersions: (datasetId: number, root: string) =>
    readCache<{ versions: StrategySummary[] }>(versionsPath(datasetId, root)),
  pine: async (indicator: string) => {
    const response = await fetch(`${API}/strategies/${encodeURIComponent(indicator)}/pine`);
    if (!response.ok) throw new Error("找不到 Pine 原始碼。");
    return response.text();
  },
  importIndicator: async (payload: Record<string, unknown>) => {
    const result = await request<Record<string, unknown>>("/import", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    clearResearchCache();
    return result;
  },
  removeVersion: async (datasetId: number, indicator: string) => {
    const result = await request(`/datasets/${datasetId}/versions/${encodeURIComponent(indicator)}`, {
      method: "DELETE",
    });
    clearResearchCache();
    return result;
  },
  removeStrategy: async (datasetId: number, root: string) => {
    const result = await request(`/datasets/${datasetId}/strategies/${encodeURIComponent(root)}`, {
      method: "DELETE",
    });
    clearResearchCache();
    return result;
  },
  removeDataset: async (datasetId: number) => {
    const result = await request(`/datasets/${datasetId}`, { method: "DELETE" });
    clearResearchCache();
    return result;
  },
};
