// Thin fetch wrappers around the SignalForge API (apps/api/routes/*).
//
// Server Components (running inside the `web` container) use `API_URL`
// (the Docker-network address, `http://api:8000`). Client Components
// (running in the user's browser) use `NEXT_PUBLIC_API_URL`
// (`http://localhost:8000`, published by docker-compose and already
// whitelisted by the API's CORS_ALLOW_ORIGINS). Never hardcode a URL
// outside this module.
import type {
  AnalystRatingResponse,
  ApiErrorBody,
  EvidenceListResponse,
  FundamentalsResponse,
  InstrumentSortKey,
  InstrumentSummary,
  MarketRegimeResponse,
  MomentumScanResponse,
  PriceResponse,
  RangeKey,
  RelativeStrengthResponse,
  ScoreDistributionResponse,
  ScoreResponse,
  SectorsResponse,
  SortOrder,
  StockDiagnosticResponse,
  TechnicalsResponse,
  AiChatRequest,
  AiChatResponse,
  AiStatusResponse,
  AiStockContextResponse,
  MlPerformanceResponse,
  ChecklistSummaryResponse,
  StockChecklistResult,
  AiAlphaPicksResponse,
} from "./types";

function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.API_URL ?? "http://localhost:8000";
  }
  // On the client, use relative paths so requests flow through Next.js rewrites.
  return process.env.NEXT_PUBLIC_API_URL ?? window.location.origin;
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

const MAX_CLIENT_CACHE_ENTRIES = 120;
const clientCache = new Map<string, { data: any; expiry: number }>();

function setClientCache(urlStr: string, data: any, ttlMs: number = 60_000) {
  if (clientCache.size >= MAX_CLIENT_CACHE_ENTRIES) {
    const oldestKey = clientCache.keys().next().value;
    if (oldestKey) clientCache.delete(oldestKey);
  }
  clientCache.set(urlStr, { data, expiry: Date.now() + ttlMs });
}

// Server-side in-memory cache to prevent redundant container-to-container HTTP roundtrips
// and 1.5MB JSON re-parsing on every page transition / RSC request.
const serverCache = new Map<string, { data: any; expiry: number }>();

function getServerCache<T>(urlStr: string): T | null {
  const hit = serverCache.get(urlStr);
  if (hit && hit.expiry > Date.now()) {
    return hit.data as T;
  }
  return null;
}

function setServerCache(urlStr: string, data: any, ttlMs: number = 60_000): void {
  if (serverCache.size >= 200) {
    const oldest = serverCache.keys().next().value;
    if (oldest) serverCache.delete(oldest);
  }
  serverCache.set(urlStr, { data, expiry: Date.now() + ttlMs });
}

async function getJson<T>(
  path: string,
  params?: Record<string, string | undefined>,
  fetchOptions?: RequestInit
): Promise<T> {
  const url = new URL(path, apiBaseUrl());
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, value);
    }
  }

  const urlStr = url.toString();
  if (typeof window !== "undefined") {
    const hit = clientCache.get(urlStr);
    if (hit && hit.expiry > Date.now()) {
      return hit.data as T;
    }
  } else {
    const hit = getServerCache<T>(urlStr);
    if (hit) {
      return hit;
    }
  }

  let res: Response;
  const nextFetchOptions = typeof window === "undefined"
    ? ({ next: { revalidate: 60 }, ...fetchOptions } as RequestInit)
    : fetchOptions;

  try {
    res = await fetch(urlStr, nextFetchOptions);
  } catch (err) {
    throw new ApiError(0, `Could not reach the API (${(err as Error).message}).`);
  }

  if (!res.ok) {
    let detail = `API returned ${res.status}`;
    try {
      const body = (await res.json()) as ApiErrorBody;
      if (body?.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON - fall back to the generic message above.
    }
    throw new ApiError(res.status, detail);
  }

  const data = (await res.json()) as T;
  if (typeof window !== "undefined") {
    // 5-minute client cache for market aggregates, 60-second for stock data
    const ttl = path.includes("/market/") ? 300_000 : 60_000;
    setClientCache(urlStr, data, ttl);
  } else {
    // 120-second server cache for full instrument listings, 60-second for individual stocks
    const ttl = path.includes("/instruments") ? 120_000 : 60_000;
    setServerCache(urlStr, data, ttl);
  }
  return data;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const url = new URL(path, apiBaseUrl());

  let res: Response;
  try {
    res = await fetch(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiError(0, `Could not reach the API (${(err as Error).message}).`);
  }

  if (!res.ok) {
    let detail = `API returned ${res.status}`;
    try {
      const parsed = await res.json();
      // FastAPI/pydantic 422s return `detail` as a list of {loc, msg, ...}
      // objects, not a plain string - flatten that into one readable line
      // so the UI never shows "[object Object]".
      if (Array.isArray(parsed?.detail)) {
        detail = parsed.detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg ?? ""}`).join("; ");
      } else if (typeof parsed?.detail === "string") {
        detail = parsed.detail;
      }
    } catch {
      // response body wasn't JSON - fall back to the generic message above.
    }
    throw new ApiError(res.status, detail);
  }

  return (await res.json()) as T;
}

export function listInstruments(opts?: {
  sort?: InstrumentSortKey;
  order?: SortOrder;
  momentumPass?: boolean;
  sector?: string;
  minScore?: number;
  maxScore?: number;
  breakoutOnly?: boolean;
}): Promise<InstrumentSummary[]> {
  return getJson<InstrumentSummary[]>(
    "/api/v1/instruments",
    {
      sort: opts?.sort,
      order: opts?.order,
      momentum_pass: opts?.momentumPass === undefined ? undefined : String(opts.momentumPass),
      sector: opts?.sector,
      min_score: opts?.minScore !== undefined ? String(opts.minScore) : undefined,
      max_score: opts?.maxScore !== undefined ? String(opts.maxScore) : undefined,
      breakout_only: opts?.breakoutOnly === undefined ? undefined : String(opts.breakoutOnly),
    },
    { next: { revalidate: 60 } }
  );
}

export function getAnalystRating(symbol: string): Promise<AnalystRatingResponse> {
  return getJson<AnalystRatingResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/analyst-rating`);
}

export function getScoreDistribution(): Promise<ScoreDistributionResponse> {
  return getJson<ScoreDistributionResponse>("/api/v1/market/score-distribution");
}

export function getSectorSummary(): Promise<SectorsResponse> {
  return getJson<SectorsResponse>("/api/v1/market/sectors");
}

export function searchInstruments(query: string): Promise<InstrumentSummary[]> {
  return getJson<InstrumentSummary[]>("/api/v1/instruments/search", { q: query });
}

export function getPrice(symbol: string, range: RangeKey): Promise<PriceResponse> {
  return getJson<PriceResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/price`, { range });
}

export function getTechnicals(symbol: string, range: RangeKey): Promise<TechnicalsResponse> {
  return getJson<TechnicalsResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/technicals`, { range });
}

export function getRelativeStrength(symbol: string): Promise<RelativeStrengthResponse> {
  return getJson<RelativeStrengthResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/relative-strength`);
}

export function getFundamentals(symbol: string): Promise<FundamentalsResponse> {
  return getJson<FundamentalsResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/fundamentals`);
}

export function getScore(symbol: string): Promise<ScoreResponse> {
  return getJson<ScoreResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/score`);
}

export function getMomentumScan(symbol: string): Promise<MomentumScanResponse> {
  return getJson<MomentumScanResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/momentum-scan`);
}

export function getEvidence(symbol: string, limit = 100): Promise<EvidenceListResponse> {
  return getJson<EvidenceListResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/evidence`, {
    limit: String(limit),
  });
}

export function getMarketRegime(): Promise<MarketRegimeResponse> {
  return getJson<MarketRegimeResponse>("/api/v1/market/regime");
}

export interface StructuredDataResponse {
  has_data: boolean;
  data: Record<string, Record<string, Record<string, string>>> | null;
}

export function getStructuredData(symbol: string): Promise<StructuredDataResponse> {
  return getJson<StructuredDataResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/structured`);
}

export interface ForecastPoint {
    date: string;
    close: number;
    volume: number;
}
export interface ForecastResponse {
    symbol: string;
    model_name: string;
    as_of_date: string;
    horizon_days: number;
    trajectory: ForecastPoint[];
    mape: number | null;
    directional_accuracy: boolean | null;
}
export function getForecast(symbol: string): Promise<ForecastResponse> {
    return getJson<ForecastResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/forecast`);
}

export function getStockDiagnostic(symbol: string): Promise<StockDiagnosticResponse> {
  return getJson<StockDiagnosticResponse>(`/api/v1/stocks/${encodeURIComponent(symbol)}/diagnostic`);
}

export function getAiStatus(): Promise<AiStatusResponse> {
  return getJson<AiStatusResponse>("/api/v1/ai/status");
}

export function getAiStockContext(symbol: string): Promise<AiStockContextResponse> {
  return getJson<AiStockContextResponse>(`/api/v1/ai/stocks/${encodeURIComponent(symbol)}/context`);
}

export async function postAiChat(req: AiChatRequest): Promise<AiChatResponse> {
  const url = new URL("/api/v1/ai/chat", apiBaseUrl());
  const res = await fetch(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({ detail: "Chat request failed" }));
    throw new ApiError(res.status, errBody.detail || "Chat request failed");
  }
  return res.json();
}

export async function streamAiChat(
  req: AiChatRequest,
  onToken: (token: string) => void,
  onMeta?: (meta: any) => void,
  onStatus?: (status: string) => void
): Promise<string> {
  const url = new URL("/api/v1/ai/chat/stream", apiBaseUrl());
  const res = await fetch(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const errorText = await res.text();
    throw new ApiError(res.status, errorText || "Stream request failed");
  }
  const reader = res.body?.getReader();
  if (!reader) throw new ApiError(0, "ReadableStream not supported");
  const decoder = new TextDecoder("utf-8");
  let fullText = "";
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || !line.startsWith("data:")) continue;
      const jsonStr = line.replace(/^data:\s*/, "").trim();
      if (!jsonStr) continue;
      let payload: any = null;
      try {
        payload = JSON.parse(jsonStr);
      } catch {
        continue;
      }
      if (payload.type === "meta" && onMeta) {
        onMeta(payload);
      } else if (payload.type === "status" && onStatus) {
        onStatus(payload.status);
      } else if (payload.type === "token") {
        fullText += payload.content;
        onToken(payload.content);
      } else if (payload.type === "error") {
        throw new ApiError(500, payload.error);
      }
    }
  }

  // Flush remaining buffer if present
  if (buffer.trim().startsWith("data:")) {
    const jsonStr = buffer.trim().replace(/^data:\s*/, "").trim();
    try {
      const payload = JSON.parse(jsonStr);
      if (payload.type === "token") {
        fullText += payload.content;
        onToken(payload.content);
      }
    } catch {
      // ignore trailing chunk parse errors
    }
  }

  return fullText;
}

export async function getMlPerformance(asOf?: string): Promise<MlPerformanceResponse> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  const res = await fetch(`${apiBaseUrl()}/api/v1/market/ml-performance${query}`, {
    next: { revalidate: 60 },
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch ML performance: ${res.statusText}`);
  }
  return res.json();
}

export async function getFundamentalChecklist(
  minScore: number = 6,
  sector?: string
): Promise<ChecklistSummaryResponse> {
  const params = new URLSearchParams();
  params.set("min_score", String(minScore));
  if (sector && sector !== "all") {
    params.set("sector", sector);
  }
  const res = await fetch(`${apiBaseUrl()}/api/v1/market/fundamental-checklist?${params.toString()}`, {
    next: { revalidate: 60 },
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch fundamental checklist: ${res.statusText}`);
  }
  return res.json();
}

export async function getStockChecklist(
  symbol: string,
  exchange: string = "NSE"
): Promise<StockChecklistResult> {
  const res = await fetch(`${apiBaseUrl()}/api/v1/stocks/${encodeURIComponent(symbol)}/checklist?exchange=${encodeURIComponent(exchange)}`, {
    next: { revalidate: 60 },
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch checklist for ${symbol}: ${res.statusText}`);
  }
  return res.json();
}

export async function getAiAlphaPicks(forceRefresh = false): Promise<AiAlphaPicksResponse> {
  const query = forceRefresh ? "?force_refresh=true" : "";
  const res = await fetch(`${apiBaseUrl()}/api/v1/ai/alpha-picks${query}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch AI alpha picks: ${res.statusText}`);
  }
  return res.json();
}

export async function generateAiAlphaPicks(): Promise<AiAlphaPicksResponse> {
  const res = await fetch(`${apiBaseUrl()}/api/v1/ai/alpha-picks/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to generate AI alpha picks: ${res.statusText}`);
  }
  return res.json();
}

/**
 * Pre-warms the client-side cache for a stock symbol during idle time or hover.
 * This ensures that when the user clicks the stock, its price and technical charts
 * resolve with 0ms delay directly from memory.
 */
export function prefetchStock(symbol: string, range: RangeKey = "6M"): void {
  if (typeof window === "undefined" || !symbol) return;
  const sym = symbol.toUpperCase();
  getPrice(sym, range).catch(() => {});
  getTechnicals(sym, range).catch(() => {});
  getScore(sym).catch(() => {});
}



