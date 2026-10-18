import {
  PrivilegeStatus,
  RamInfo,
  PagesMapResponse,
  PageDetail,
  ProcessInfo,
  ProcessPagesResponse,
} from "@/types/ram";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export type ApiErrorType =
  | "BACKEND_UNAVAILABLE"
  | "NETWORK_CONNECTION_FAILED"
  | "CORS_OR_POLICY_ERROR"
  | "HTTP_4XX"
  | "HTTP_5XX"
  | "INVALID_API_RESPONSE";

export class ApiDiagnosticError extends Error {
  public readonly errorType: ApiErrorType;
  public readonly status?: number;
  public readonly url: string;
  public readonly diagnosticMessage: string;
  public readonly rawDetails?: string;

  constructor(params: {
    errorType: ApiErrorType;
    status?: number;
    url: string;
    diagnosticMessage: string;
    rawDetails?: string;
  }) {
    super(params.diagnosticMessage);
    this.name = "ApiDiagnosticError";
    this.errorType = params.errorType;
    this.status = params.status;
    this.url = params.url;
    this.diagnosticMessage = params.diagnosticMessage;
    this.rawDetails = params.rawDetails;
  }
}

/**
 * Robust JSON fetch wrapper that categorizes failures into distinct error types:
 * - Backend unavailable (server down / connection refused)
 * - Network connection failed (offline / host unreachable)
 * - CORS / security policy errors
 * - HTTP 4xx (client errors with backend detail messages)
 * - HTTP 5xx (server internal errors)
 * - Invalid API response (malformed / non-JSON)
 */
async function apiFetch<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE}${endpoint}`;
  let res: Response;

  try {
    res = await fetch(url, options);
  } catch (err: unknown) {
    const isOffline = typeof navigator !== "undefined" && navigator.onLine === false;
    const errorObj = err instanceof Error ? err : new Error(String(err));
    if (isOffline) {
      throw new ApiDiagnosticError({
        errorType: "NETWORK_CONNECTION_FAILED",
        url,
        diagnosticMessage: `Network connection failed: Browser appears offline. Cannot reach ${url}.`,
        rawDetails: errorObj.message,
      });
    }

    const errStr = errorObj.message.toLowerCase();
    if (errStr.includes("cors") || errStr.includes("cross-origin")) {
      throw new ApiDiagnosticError({
        errorType: "CORS_OR_POLICY_ERROR",
        url,
        diagnosticMessage: `CORS / Network Policy Error: Request to ${url} was blocked by browser cross-origin policy.`,
        rawDetails: errorObj.message,
      });
    }

    // Default connection failure (Connection Refused / server not running)
    const isLocalhost = url.includes("localhost") || url.includes("127.0.0.1") || url.includes("0.0.0.0");
    throw new ApiDiagnosticError({
      errorType: "BACKEND_UNAVAILABLE",
      url,
      diagnosticMessage: isLocalhost
        ? `FastAPI backend is unavailable at ${API_BASE} (Connection Refused). Make sure the backend server is running.`
        : `Backend server at ${API_BASE} is unreachable or connection was refused.`,
      rawDetails: errorObj.message,
    });
  }

  if (!res.ok) {
    let errorDetail = "";
    try {
      const text = await res.text();
      try {
        const json = JSON.parse(text);
        errorDetail = json.detail || json.message || text;
      } catch {
        errorDetail = text;
      }
    } catch {
      errorDetail = res.statusText;
    }

    if (res.status >= 400 && res.status < 500) {
      throw new ApiDiagnosticError({
        errorType: "HTTP_4XX",
        status: res.status,
        url,
        diagnosticMessage: `Client Error ${res.status} (${res.statusText}): ${errorDetail || "Bad Request"} on ${url}`,
        rawDetails: errorDetail,
      });
    }

    if (res.status >= 500) {
      throw new ApiDiagnosticError({
        errorType: "HTTP_5XX",
        status: res.status,
        url,
        diagnosticMessage: `Server Error ${res.status} (${res.statusText}): ${errorDetail || "Internal Server Error"} on ${url}`,
        rawDetails: errorDetail,
      });
    }
  }

  try {
    return (await res.json()) as T;
  } catch (err: unknown) {
    const errorObj = err instanceof Error ? err : new Error(String(err));
    throw new ApiDiagnosticError({
      errorType: "INVALID_API_RESPONSE",
      status: res.status,
      url,
      diagnosticMessage: `Invalid API response: Expected JSON payload from ${url} but response could not be parsed.`,
      rawDetails: errorObj.message,
    });
  }
}

export async function fetchStatus(): Promise<PrivilegeStatus> {
  return apiFetch<PrivilegeStatus>("/api/status");
}

export async function fetchRamInfo(): Promise<RamInfo> {
  return apiFetch<RamInfo>("/api/ram");
}

export async function fetchPagesMap(
  startPfn?: number,
  count?: number,
  resolution: number = 512
): Promise<PagesMapResponse> {
  const params = new URLSearchParams();
  if (startPfn !== undefined && startPfn !== null) {
    params.append("start_pfn", startPfn.toString());
  }
  if (count !== undefined && count !== null) {
    params.append("count", count.toString());
  }
  params.append("resolution", resolution.toString());

  return apiFetch<PagesMapResponse>(`/api/pages?${params.toString()}`);
}

export async function fetchPageDetail(pfn: number): Promise<PageDetail> {
  return apiFetch<PageDetail>(`/api/page/${pfn}`);
}

export async function fetchProcesses(limit: number = 200): Promise<ProcessInfo[]> {
  return apiFetch<ProcessInfo[]>(`/api/processes?limit=${limit}`);
}

export async function fetchProcessPages(
  pid: number,
  maxPages: number = 10000
): Promise<ProcessPagesResponse> {
  return apiFetch<ProcessPagesResponse>(`/api/process/${pid}/pages?max_pages=${maxPages}`);
}

export function formatBytes(bytes: number, decimals: number = 2): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["B", "KB", "MB", "GB", "TB", "PB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

export function formatNumber(num: number): string {
  return new Intl.NumberFormat().format(num);
}
