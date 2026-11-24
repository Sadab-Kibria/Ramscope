"use client";

import React, { useState } from "react";
import {
  Layers,
  PlusCircle,
  Trash2,
  Cpu,
  CheckCircle2,
  AlertCircle,
  HardDrive,
  Focus,
  Loader2,
  Sparkles,
} from "lucide-react";
import { ReservationInfo, ProcessInfo, ReserveRequest } from "@/types/ram";
import { reserveMemory, releaseMemory, formatBytes, formatNumber } from "@/lib/api";

interface ReservationPanelProps {
  reservations: ReservationInfo[];
  processes: ProcessInfo[];
  onReservationChanged: () => Promise<void>;
  onLocateRange?: (startPfn: number, pageCount: number) => void;
  availableRamBytes?: number;
}

const PRESET_SIZES = [
  { label: "4 MB", mb: 4 },
  { label: "16 MB", mb: 16 },
  { label: "32 MB", mb: 32 },
  { label: "64 MB", mb: 64 },
  { label: "128 MB", mb: 128 },
  { label: "256 MB", mb: 256 },
];

export const ReservationPanel: React.FC<ReservationPanelProps> = ({
  reservations,
  processes,
  onReservationChanged,
  onLocateRange,
  availableRamBytes = 0,
}) => {
  const [appName, setAppName] = useState<string>("");
  const [sizeMb, setSizeMb] = useState<number>(64);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [releasingId, setReleasingId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const handleSelectProcess = (procName: string) => {
    setAppName(procName);
  };

  const handleReserve = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!appName.trim()) {
      setFeedback({ type: "error", message: "Please specify an application name." });
      return;
    }
    if (sizeMb <= 0 || sizeMb > 512) {
      setFeedback({ type: "error", message: "Allocation size must be between 1 MB and 512 MB." });
      return;
    }

    setIsSubmitting(true);
    setFeedback(null);
    try {
      const req: ReserveRequest = {
        application: appName.trim(),
        sizeMb: sizeMb,
      };
      const res = await reserveMemory(req);
      setFeedback({
        type: "success",
        message: res.message || `Allocated Region #${res.regionId} (${res.sizeMb} MB) for '${res.application}' at PFN ${res.startPfn}.`,
      });
      setAppName("");
      await onReservationChanged();
      if (onLocateRange && res.startPfn !== undefined) {
        onLocateRange(res.startPfn, res.pageCount);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setFeedback({ type: "error", message: `Allocation failed: ${msg}` });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRelease = async (regionId: number) => {
    setReleasingId(regionId);
    setFeedback(null);
    try {
      const res = await releaseMemory(regionId);
      setFeedback({
        type: "success",
        message: `Region #${res.regionId} successfully deallocated and returned to free pool.`,
      });
      await onReservationChanged();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setFeedback({ type: "error", message: `Deallocation failed: ${msg}` });
    } finally {
      setReleasingId(null);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden flex flex-col">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-slate-200 bg-slate-50/70 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-emerald-100 text-emerald-700">
            <Layers className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              Physical RAM Allocation & Reservation
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200">
                Step 6
              </span>
            </h3>
            <p className="text-[11px] text-slate-500">
              Reserve contiguous physical page frames directly for specific applications
            </p>
          </div>
        </div>
        <div className="text-right text-xs">
          <span className="text-slate-400">Active Allocations: </span>
          <span className="font-bold text-emerald-700 font-mono">{reservations.length}</span>
        </div>
      </div>

      <div className="p-5 flex flex-col gap-5">
        {/* Feedback Alert */}
        {feedback && (
          <div
            className={`p-3 rounded-lg text-xs flex items-start justify-between gap-2 border ${
              feedback.type === "success"
                ? "bg-emerald-50 border-emerald-200 text-emerald-900"
                : "bg-red-50 border-red-200 text-red-900"
            }`}
          >
            <div className="flex items-start gap-2">
              {feedback.type === "success" ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
              )}
              <span className="leading-relaxed font-medium">{feedback.message}</span>
            </div>
            <button
              onClick={() => setFeedback(null)}
              className="text-slate-400 hover:text-slate-700 font-bold shrink-0 px-1"
            >
              ✕
            </button>
          </div>
        )}

        {/* Allocation Form */}
        <form onSubmit={handleReserve} className="flex flex-col gap-4 bg-slate-50/60 p-4 rounded-xl border border-slate-200/80">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-3.5 items-end">
            {/* Application Name */}
            <div className="md:col-span-5 flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
                <Cpu className="h-3.5 w-3.5 text-slate-500" />
                Target Application
              </label>
              <input
                type="text"
                value={appName}
                onChange={(e) => setAppName(e.target.value)}
                placeholder="e.g. PostgreSQL, Chrome, DemoWorker"
                className="px-3 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500 font-medium text-slate-800"
                disabled={isSubmitting}
              />
            </div>

            {/* Size in MB */}
            <div className="md:col-span-4 flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
                <HardDrive className="h-3.5 w-3.5 text-slate-500" />
                Allocation Size (MB)
              </label>
              <input
                type="number"
                min="1"
                max="512"
                value={sizeMb}
                onChange={(e) => setSizeMb(Number(e.target.value))}
                className="px-3 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500 font-mono font-semibold text-slate-800"
                disabled={isSubmitting}
              />
            </div>

            {/* Submit Button */}
            <div className="md:col-span-3">
              <button
                type="submit"
                disabled={isSubmitting || !appName.trim()}
                className="w-full flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white text-xs font-bold transition shadow-xs disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Allocating...</span>
                  </>
                ) : (
                  <>
                    <PlusCircle className="h-3.5 w-3.5" />
                    <span>Reserve RAM</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Quick Presets & Running Process Suggestions */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-200/60 text-xs">
            {/* Size presets */}
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-slate-500 font-medium">Size Presets:</span>
              <div className="flex items-center gap-1">
                {PRESET_SIZES.map((p) => (
                  <button
                    key={p.mb}
                    type="button"
                    onClick={() => setSizeMb(p.mb)}
                    className={`px-2 py-0.5 rounded text-[11px] font-mono font-medium transition ${
                      sizeMb === p.mb
                        ? "bg-emerald-600 text-white font-bold"
                        : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Running Process auto-pickers */}
            {processes.length > 0 && (
              <div className="flex items-center gap-1.5 overflow-x-auto max-w-full">
                <span className="text-[11px] text-slate-500 font-medium">Quick App:</span>
                <div className="flex items-center gap-1">
                  {processes.slice(0, 4).map((p) => (
                    <button
                      key={p.pid}
                      type="button"
                      onClick={() => handleSelectProcess(p.name)}
                      className="px-2 py-0.5 rounded text-[11px] bg-white border border-slate-200 hover:border-emerald-300 text-slate-700 hover:text-emerald-700 font-medium truncate max-w-[90px]"
                      title={`PID ${p.pid}: ${p.name}`}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </form>

        {/* Active Reservations Table */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wider">
              Active Project Allocations
            </h4>
            {availableRamBytes > 0 && (
              <span className="text-[11px] text-slate-500">
                System Available: <strong className="text-slate-700">{formatBytes(availableRamBytes)}</strong>
              </span>
            )}
          </div>

          {reservations.length === 0 ? (
            <div className="py-8 px-4 text-center rounded-xl border border-dashed border-slate-300 bg-slate-50/50 flex flex-col items-center justify-center gap-2">
              <Sparkles className="h-7 w-7 text-slate-400" />
              <p className="text-xs text-slate-600 font-medium">
                No active physical RAM reservations yet.
              </p>
              <p className="text-[11px] text-slate-400 max-w-sm">
                Use the form above to reserve physical 4KB memory blocks for any running or target application.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="bg-slate-100/80 text-slate-600 font-semibold border-b border-slate-200">
                    <th className="py-2 px-3">Region</th>
                    <th className="py-2 px-3">Application</th>
                    <th className="py-2 px-3">Size</th>
                    <th className="py-2 px-3 font-mono">PFN Range</th>
                    <th className="py-2 px-3 font-mono">Physical Address</th>
                    <th className="py-2 px-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {reservations.map((r) => {
                    const rId = r.regionId ?? r.region_id ?? 0;
                    const sPfn = r.startPfn ?? r.start_pfn ?? 0;
                    const ePfn = r.endPfn ?? r.end_pfn ?? sPfn;
                    const pCount = r.pageCount ?? r.page_count ?? (ePfn - sPfn);
                    const sBytes = r.sizeBytes ?? r.size_bytes ?? (pCount * 4096);
                    const isReleasing = releasingId === rId;

                    return (
                      <tr key={rId} className="hover:bg-emerald-50/40 transition">
                        <td className="py-2 px-3 font-mono font-bold text-emerald-700">
                          #{rId}
                        </td>
                        <td className="py-2 px-3">
                          <div className="font-semibold text-slate-900 flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block"></span>
                            <span>{r.application}</span>
                          </div>
                        </td>
                        <td className="py-2 px-3">
                          <span className="font-bold text-slate-800 font-mono">
                            {formatBytes(sBytes)}
                          </span>
                          <span className="text-[11px] text-slate-400 block">
                            {formatNumber(pCount)} pages
                          </span>
                        </td>
                        <td className="py-2 px-3 font-mono text-slate-700">
                          <div>{formatNumber(sPfn)} &rarr; {formatNumber(ePfn)}</div>
                          {r.ranges && r.ranges.length > 1 && (
                            <span className="text-[10px] text-cyan-700 font-sans font-semibold">
                              {r.ranges.length} locked physical blocks
                            </span>
                          )}
                        </td>
                        <td className="py-2 px-3 font-mono text-[11px] text-slate-500">
                          {r.physicalAddressHex ?? r.physical_address_hex ?? `0x${(sPfn * 4096).toString(16)}`}
                        </td>
                        <td className="py-2 px-3 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            {onLocateRange && (
                              <button
                                onClick={() => onLocateRange(sPfn, pCount)}
                                className="p-1 rounded text-slate-500 hover:text-emerald-700 hover:bg-emerald-100 transition"
                                title="Locate on RAM Map"
                              >
                                <Focus className="h-3.5 w-3.5" />
                              </button>
                            )}
                            <button
                              onClick={() => handleRelease(rId)}
                              disabled={isReleasing}
                              className="flex items-center gap-1 px-2 py-1 rounded text-red-600 hover:text-red-800 hover:bg-red-50 border border-red-200 text-[11px] font-semibold transition disabled:opacity-50"
                              title="Release / Deallocate Region"
                            >
                              {isReleasing ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Trash2 className="h-3 w-3" />
                              )}
                              <span>Release</span>
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
