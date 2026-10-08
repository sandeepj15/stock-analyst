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
  TechnicalsResponse,
} from "./types";

function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.API_URL ?? "http://api:8000";
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

async function getJson<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const url = new URL(path, apiBaseUrl());
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, value);
    }
  }

  let res: Response;
  try {
    res = await fetch(url.toString(), { cache: "no-store" });
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

  return (await res.json()) as T;
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
}): Promise<InstrumentSummary[]> {
  return getJson<InstrumentSummary[]>("/api/v1/instruments", {
    sort: opts?.sort,
    order: opts?.order,
    momentum_pass: opts?.momentumPass === undefined ? undefined : String(opts.momentumPass),
  });
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
