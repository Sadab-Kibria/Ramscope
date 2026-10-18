"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { Header } from "@/components/Header";
import { PrivilegeBanner } from "@/components/PrivilegeBanner";
import { SummaryCards } from "@/components/SummaryCards";
import { FilterBar } from "@/components/FilterBar";
import { RamCanvas } from "@/components/RamCanvas";
import { ProcessTable } from "@/components/ProcessTable";
import { ProcessDetailModal } from "@/components/ProcessDetailModal";
import { PageDetailModal } from "@/components/PageDetailModal";
import {
  PrivilegeStatus,
  RamInfo,
  PagesMapResponse,
  PageBlockSummary,
  PageDetail,
  ProcessInfo,
  ProcessPagesResponse,
} from "@/types/ram";
import {
  fetchStatus,
  fetchRamInfo,
  fetchPagesMap,
  fetchPageDetail,
  fetchProcesses,
  fetchProcessPages,
  API_BASE,
  ApiDiagnosticError,
} from "@/lib/api";
import { AlertTriangle, Terminal, RefreshCw } from "lucide-react";

const WS_BASE = API_BASE.replace(/^http/, "ws");

export default function Dashboard() {
  const [status, setStatus] = useState<PrivilegeStatus | null>(null);
  const [ramInfo, setRamInfo] = useState<RamInfo | null>(null);
  const [pagesMap, setPagesMap] = useState<PagesMapResponse | null>(null);
  const [processes, setProcesses] = useState<ProcessInfo[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [isLive, setIsLive] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [apiError, setApiError] = useState<ApiDiagnosticError | null>(null);

  // Resolution & View Range
  const [resolution, setResolution] = useState<number>(512);
  const [zoomRange, setZoomRange] = useState<{ startPfn?: number; count?: number }>({});
  const [activeFilter, setActiveFilter] = useState<string>("all");

  // Process Selection & Highlight
  const [selectedProcess, setSelectedProcess] = useState<ProcessInfo | null>(null);
  const [processPages, setProcessPages] = useState<ProcessPagesResponse | null>(null);
  const [isLoadingPages, setIsLoadingPages] = useState<boolean>(false);

  const [highlightedProcess, setHighlightedProcess] = useState<ProcessInfo | null>(null);
  const [highlightedPfns, setHighlightedPfns] = useState<Set<number>>(new Set());

  // Page Frame (PFN) Detail Modal
  const [selectedPfn, setSelectedPfn] = useState<number | null>(null);
  const [pageDetail, setPageDetail] = useState<PageDetail | null>(null);
  const [isLoadingPageDetail, setIsLoadingPageDetail] = useState<boolean>(false);

  const wsRef = useRef<WebSocket | null>(null);

  // Load pages map
  const loadPagesMap = useCallback(async (startPfn?: number, count?: number, res: number = resolution) => {
    try {
      const data = await fetchPagesMap(startPfn, count, res);
      setPagesMap(data);
      setApiError(null);
    } catch (err: unknown) {
      if (err instanceof ApiDiagnosticError) {
        setApiError(err);
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        setApiError(new ApiDiagnosticError({
          errorType: "BACKEND_UNAVAILABLE",
          url: `${API_BASE}/api/pages`,
          diagnosticMessage: msg || "Failed to load physical RAM page map",
        }));
      }
    }
  }, [resolution]);

  // Refresh all system statistics
  const refreshAllData = useCallback(async () => {
    setIsLoading(true);
    try {
      let fetchErr: ApiDiagnosticError | null = null;

      const [stat, ram, procs] = await Promise.all([
        fetchStatus().catch((e) => {
          if (e instanceof ApiDiagnosticError) fetchErr = e;
          return null;
        }),
        fetchRamInfo().catch((e) => {
          if (e instanceof ApiDiagnosticError) fetchErr = e;
          return null;
        }),
        fetchProcesses(200).catch((e) => {
          if (e instanceof ApiDiagnosticError) fetchErr = e;
          return [];
        }),
      ]);

      if (stat) setStatus(stat);
      if (ram) {
        setRamInfo(ram);
      }
      if (procs && procs.length > 0) setProcesses(procs);

      if (fetchErr) {
        setApiError(fetchErr);
      } else {
        setApiError(null);
      }

      await loadPagesMap(zoomRange.startPfn, zoomRange.count, resolution);
      setLastUpdated(new Date());
    } finally {
      setIsLoading(false);
    }
  }, [loadPagesMap, zoomRange, resolution]);

  // Initial fetch and periodic polling (every 2.5s)
  useEffect(() => {
    const timer = setTimeout(() => {
      void refreshAllData();
    }, 0);

    const interval = setInterval(() => {
      fetchRamInfo()
        .then((ram) => {
          setRamInfo(ram);
          setLastUpdated(new Date());
          setApiError(null);
        })
        .catch((e) => {
          if (e instanceof ApiDiagnosticError) {
            setApiError(e);
          }
        });

      fetchProcesses(100)
        .then((procs) => {
          if (procs && procs.length > 0) setProcesses(procs);
        })
        .catch(() => {});
    }, 2500);

    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [refreshAllData]);

  // WebSocket Live Connection
  useEffect(() => {
    let ws: WebSocket;
    try {
      ws = new WebSocket(`${WS_BASE}/ws/live`);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsLive(true);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "ram_update") {
            if (msg.ram) setRamInfo(msg.ram);
            if (msg.status) setStatus(msg.status);
            setLastUpdated(new Date());
          }
        } catch {
          // ignore parsing error on heartbeat
        }
      };

      ws.onclose = () => {
        setIsLive(false);
      };

      ws.onerror = () => {
        setIsLive(false);
      };
    } catch {
      // WebSocket initial connection fallback to polling
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const handleZoomChange = (startPfn: number, count: number) => {
    setZoomRange({ startPfn, count });
    loadPagesMap(startPfn, count, resolution);
  };

  const handleResolutionChange = (newRes: number) => {
    setResolution(newRes);
    loadPagesMap(zoomRange.startPfn, zoomRange.count, newRes);
  };

  const handleSelectProcess = async (proc: ProcessInfo) => {
    setSelectedProcess(proc);
    setIsLoadingPages(true);
    try {
      const pData = await fetchProcessPages(proc.pid);
      setProcessPages(pData);
    } catch {
      setProcessPages({
        pid: proc.pid,
        name: proc.name,
        totalMappedPages: 0,
        residentPages: 0,
        pfnList: [],
        pages: [],
        error: "Failed to load process pagemap",
      });
    } finally {
      setIsLoadingPages(false);
    }
  };

  const handleHighlightProcess = async (proc: ProcessInfo) => {
    if (highlightedProcess && highlightedProcess.pid === proc.pid) {
      setHighlightedProcess(null);
      setHighlightedPfns(new Set());
      if (activeFilter === "process_only") {
        setActiveFilter("all");
      }
      return;
    }

    setHighlightedProcess(proc);
    try {
      const pData = await fetchProcessPages(proc.pid);
      const pfnSet = new Set(pData.pfnList ?? pData.pfn_list ?? []);
      setHighlightedPfns(pfnSet);
    } catch (e) {
      console.error("Failed to load PFNs for highlight", e);
    }
  };

  const handleClearHighlight = () => {
    setHighlightedProcess(null);
    setHighlightedPfns(new Set());
    if (activeFilter === "process_only") {
      setActiveFilter("all");
    }
  };

  const handleSelectPfn = async (pfn: number) => {
    setSelectedPfn(pfn);
    setIsLoadingPageDetail(true);
    try {
      const detail = await fetchPageDetail(pfn);
      setPageDetail(detail);
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoadingPageDetail(false);
    }
  };

  const handleSelectBlock = (block: PageBlockSummary) => {
    const sPfn = block.startPFN ?? block.start_pfn ?? 0;
    const pCount = block.pageCount ?? block.page_count ?? 1;
    if (pCount === 1) {
      handleSelectPfn(sPfn);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans">
      {/* Header */}
      <Header
        status={status}
        lastUpdated={lastUpdated}
        isLive={isLive}
        onRefresh={refreshAllData}
        isLoading={isLoading}
      />

      {/* Diagnostic API Error Banner */}
      {apiError && (
        <div className="mx-4 lg:mx-8 mt-3 p-3.5 bg-red-50/90 border border-red-200 text-red-900 text-xs rounded-lg shadow-xs flex flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-red-950">
                    Connection Diagnostic Alert
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-red-100 border border-red-300 text-red-800">
                    {apiError.errorType.replace(/_/g, " ")}
                  </span>
                  {apiError.status && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-white border border-red-200 text-red-700">
                      HTTP {apiError.status}
                    </span>
                  )}
                </div>
                <p className="text-red-800 font-sans leading-relaxed">
                  {apiError.diagnosticMessage}
                </p>
                {apiError.rawDetails && apiError.rawDetails !== apiError.diagnosticMessage && (
                  <p className="text-[11px] font-mono text-red-700 bg-red-100/50 p-1.5 rounded border border-red-200">
                    Details: {apiError.rawDetails}
                  </p>
                )}
              </div>
            </div>

            <button
              onClick={refreshAllData}
              disabled={isLoading}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-white hover:bg-red-100 border border-red-200 text-red-900 font-medium transition shrink-0"
              title="Retry Connection"
            >
              <RefreshCw className={`h-3 w-3 ${isLoading ? "animate-spin" : ""}`} />
              <span>Retry</span>
            </button>
          </div>

          {apiError.errorType === "BACKEND_UNAVAILABLE" && (
            <div className="mt-1 pt-2 border-t border-red-200 flex flex-wrap items-center gap-2 text-[11px] font-mono text-slate-700">
              <div className="flex items-center gap-1 font-semibold text-slate-900">
                <Terminal className="h-3.5 w-3.5 text-slate-700" />
                <span>Start Backend Server:</span>
              </div>
              <code className="bg-white border border-slate-300 px-2 py-0.5 rounded text-slate-900 select-all font-semibold">
                cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
              </code>
            </div>
          )}
        </div>
      )}

      {/* Privilege Diagnostic Banner */}
      <PrivilegeBanner status={status} />

      {/* Summary Metrics */}
      <SummaryCards ram={ramInfo} />

      {/* Filter Bar */}
      <FilterBar
        activeFilter={activeFilter}
        onFilterChange={setActiveFilter}
        hasHighlightedProcess={!!highlightedProcess}
        onClearHighlight={handleClearHighlight}
      />

      {/* Main Grid */}
      <main className="flex-1 px-4 lg:px-8 py-4 grid grid-cols-1 xl:grid-cols-12 gap-5 items-start">
        {/* Physical RAM Visualizer */}
        <section className="xl:col-span-7 flex flex-col gap-4">
          <RamCanvas
            mapData={pagesMap}
            highlightedPfns={highlightedPfns}
            highlightedProcessName={highlightedProcess?.name}
            activeFilter={activeFilter}
            onSelectPfn={handleSelectPfn}
            onSelectBlock={handleSelectBlock}
            onZoomChange={handleZoomChange}
            onResolutionChange={handleResolutionChange}
            selectedResolution={resolution}
            isLoading={isLoading}
          />
        </section>

        {/* Process Statistics Table */}
        <section className="xl:col-span-5 flex flex-col gap-4">
          <ProcessTable
            processes={processes}
            selectedPid={selectedProcess?.pid || null}
            onSelectProcess={handleSelectProcess}
            onHighlightProcess={handleHighlightProcess}
            highlightedPid={highlightedProcess?.pid || null}
            totalRamBytes={ramInfo?.totalBytes ?? ramInfo?.total_bytes ?? 0}
          />
        </section>
      </main>

      {/* Process Modal */}
      {selectedProcess && (
        <ProcessDetailModal
          process={selectedProcess}
          pagesData={processPages}
          isLoadingPages={isLoadingPages}
          onClose={() => setSelectedProcess(null)}
          onSelectPfn={handleSelectPfn}
          onHighlightProcess={handleHighlightProcess}
          isHighlighted={highlightedProcess?.pid === selectedProcess.pid}
        />
      )}

      {/* Page Detail Modal */}
      {selectedPfn !== null && (
        <PageDetailModal
          pageDetail={pageDetail}
          isLoading={isLoadingPageDetail}
          onClose={() => {
            setSelectedPfn(null);
            setPageDetail(null);
          }}
          onSelectProcessPid={(pid) => {
            const match = processes.find((p) => p.pid === pid);
            if (match) {
              handleSelectProcess(match);
            }
          }}
        />
      )}

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-white px-8 py-3 text-center text-xs text-slate-500 font-mono">
        RAMScope — Linux Physical Memory Visualization System
      </footer>
    </div>
  );
}
