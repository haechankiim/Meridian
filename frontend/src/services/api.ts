import type {
  AssetCatalogResponse,
  AssetClass,
  BacktestRequest,
  BacktestResponse,
  CandleResponse,
  DeleteBacktestResponse,
  HealthResponse,
  RecentBacktestsResponse,
  RiskAnalyticsResponse,
} from "../types/api";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;

    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      const text = await response.text();
      if (text) {
        detail = text;
      }
    }

    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export async function fetchAssetCatalog(assetClass: AssetClass): Promise<AssetCatalogResponse> {
  const query = new URLSearchParams({
    asset_class: assetClass,
    limit: "8",
  });
  return requestJson<AssetCatalogResponse>(`/api/v1/data/assets?${query.toString()}`);
}

export async function fetchCandles(
  symbol: string,
  assetClass: AssetClass,
  startDate: string,
  endDate: string,
  includeFeatures = true,
  source = "auto",
): Promise<CandleResponse> {
  const query = new URLSearchParams({
    asset_class: assetClass,
    start_date: startDate,
    end_date: endDate,
    interval: "1d",
    include_features: String(includeFeatures),
    source,
  });
  return requestJson<CandleResponse>(`/api/v1/data/candles/${encodeURIComponent(symbol)}?${query.toString()}`);
}

export async function runBacktest(payload: BacktestRequest): Promise<BacktestResponse> {
  return requestJson<BacktestResponse>("/api/v1/backtest/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchBacktestResults(backtestId: number): Promise<BacktestResponse> {
  return requestJson<BacktestResponse>(`/api/v1/backtest/${backtestId}/results`);
}

export async function fetchRecentBacktests(limit = 8): Promise<RecentBacktestsResponse> {
  const query = new URLSearchParams({
    limit: String(limit),
  });
  return requestJson<RecentBacktestsResponse>(`/api/v1/backtest/recent?${query.toString()}`);
}

export async function fetchRiskAnalytics(backtestId: number): Promise<RiskAnalyticsResponse> {
  return requestJson<RiskAnalyticsResponse>(`/api/v1/analytics/risk/${backtestId}`);
}

export async function deleteBacktest(backtestId: number): Promise<DeleteBacktestResponse> {
  return requestJson<DeleteBacktestResponse>(`/api/v1/backtest/${backtestId}`, {
    method: "DELETE",
  });
}
