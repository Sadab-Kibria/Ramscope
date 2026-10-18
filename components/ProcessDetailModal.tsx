"use client";

import React, { useState } from "react";
import { X, Sparkles, AlertCircle, ArrowUpRight, Cpu, Layers } from "lucide-react";
import { ProcessInfo, ProcessPagesResponse } from "@/types/ram";
import { formatBytes, formatNumber } from "@/lib/api";

interface ProcessDetailModalProps {
  process: ProcessInfo | null;
  pagesData: ProcessPagesResponse | null;
  isLoadingPages: boolean;
  onClose: () => void;
  onSelectPfn: (pfn: number) => void;
  onHighlightProcess: (process: ProcessInfo) => void;
  isHighlighted: boolean;
}

export const ProcessDetailModal: React.FC<ProcessDetailModalProps> = ({
  process,
  pagesData,
  isLoadingPages,
  onClose,
  onSelectPfn,
  onHighlightProcess,
  isHighlighted,
}) => {
  const [filterQuery, setFilterQuery] = useState("");

  if (!process) return null;

  const pages = pagesData?.pages || [];
  const residentPages = pagesData?.residentPages ?? pagesData?.resident_pages ?? (process.residentPages ?? process.resident_pages ?? 0);

  const filteredPages = pages.filter((p) => {
    const q = filterQuery.toLowerCase();
    const vHex = (p.virtualAddressHex ?? p.virtual_address_hex ?? "").toLowerCase();
    const pHex = (p.physicalAddressHex ?? p.physical_address_hex ?? "").toLowerCase();
    return (
      p.pfn.toString().includes(q) ||
      vHex.includes(q) ||
      pHex.includes(q) ||
      p.flags.some((f) => f.toLowerCase().includes(q))
    );
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs animate-in fade-in duration-150">
      <div className="w-full max-w-3xl max-h-[85vh] rounded-lg border border-slate-200 bg-white p-5 shadow-xl flex flex-col gap-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-md bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-800">
              <Cpu className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-slate-900">{process.name}</h3>
                <span className="px-1.5 py-0.5 rounded text-xs font-mono bg-slate-100 border border-slate-200 text-slate-600">
                  PID {process.pid}
                </span>
              </div>
              <p className="text-xs text-slate-500 font-mono truncate max-w-md mt-0.5">
                {process.cmdline || "No command line arguments"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => onHighlightProcess(process)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition ${
                isHighlighted
                  ? "bg-rose-100 text-rose-700 border border-rose-200"
                  : "bg-white text-slate-700 border border-slate-200 hover:bg-slate-50"
              }`}
            >
              <Sparkles className="h-3.5 w-3.5 text-rose-600" />
              <span>{isHighlighted ? "Highlighted" : "Highlight on Map"}</span>
            </button>

            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-800 transition"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
          <div className="p-2.5 rounded bg-slate-50 border border-slate-200">
            <div className="font-sans text-slate-500 text-[11px]">RSS (Resident)</div>
            <div className="text-sm font-bold text-slate-900 mt-0.5">{formatBytes(process.rss)}</div>
          </div>
          <div className="p-2.5 rounded bg-slate-50 border border-slate-200">
            <div className="font-sans text-slate-500 text-[11px]">PSS (Proportional)</div>
            <div className="text-sm font-bold text-slate-900 mt-0.5">
              {process.pss !== null && process.pss !== undefined ? formatBytes(process.pss) : "--"}
            </div>
          </div>
          <div className="p-2.5 rounded bg-slate-50 border border-slate-200">
            <div className="font-sans text-slate-500 text-[11px]">VSZ (Virtual)</div>
            <div className="text-sm font-bold text-slate-900 mt-0.5">{formatBytes(process.vsz)}</div>
          </div>
          <div className="p-2.5 rounded bg-slate-50 border border-slate-200">
            <div className="font-sans text-slate-500 text-[11px]">Resident Pages</div>
            <div className="text-sm font-bold text-blue-600 mt-0.5">{formatNumber(residentPages)}</div>
          </div>
        </div>

        {/* Warning if pagemap requires root */}
        {pagesData?.error && (
          <div className="flex items-start gap-2 p-2.5 rounded bg-amber-50 border border-amber-200 text-amber-900 text-xs">
            <AlertCircle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold">Notice: </span>
              <span>{pagesData.error}</span>
            </div>
          </div>
        )}

        {/* Table & search */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-800">
            <Layers className="h-4 w-4 text-slate-600" />
            <span>Virtual → Physical Page Mappings ({pages.length} Pages Listed)</span>
          </div>

          <input
            type="text"
            placeholder="Filter VAddr, PFN, Flag..."
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            className="px-2.5 py-1 rounded border border-slate-200 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-slate-400"
          />
        </div>

        {/* Table content */}
        <div className="flex-1 overflow-x-auto overflow-y-auto border border-slate-200 rounded min-h-[180px] max-h-[300px]">
          {isLoadingPages ? (
            <div className="h-32 flex items-center justify-center text-xs font-mono text-slate-600">
              Querying /proc/{process.pid}/pagemap...
            </div>
          ) : filteredPages.length === 0 ? (
            <div className="h-32 flex items-center justify-center text-xs text-slate-500">
              No physical page entries available. Run backend with root to inspect page tables.
            </div>
          ) : (
            <table className="w-full text-left text-xs font-mono">
              <thead className="sticky top-0 bg-slate-50 text-slate-600 text-[11px] border-b border-slate-200 uppercase">
                <tr>
                  <th className="py-1.5 px-2.5">Virtual Address</th>
                  <th className="py-1.5 px-2.5">PFN</th>
                  <th className="py-1.5 px-2.5">Physical Address</th>
                  <th className="py-1.5 px-2.5">Flags</th>
                  <th className="py-1.5 px-2.5 text-center">Inspect</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredPages.slice(0, 300).map((pg, i) => {
                  const isPres = pg.isPresent ?? pg.is_present;
                  return (
                    <tr key={i} className="hover:bg-slate-50">
                      <td className="py-1.5 px-2.5 text-blue-600 font-semibold">{pg.virtualAddressHex ?? pg.virtual_address_hex}</td>
                      <td className="py-1.5 px-2.5 text-slate-800">{isPres ? pg.pfn : "--"}</td>
                      <td className="py-1.5 px-2.5 text-slate-600">{pg.physicalAddressHex ?? pg.physical_address_hex}</td>
                      <td className="py-1.5 px-2.5 text-slate-600">
                        {pg.flags.join(", ") || "Active"}
                      </td>
                      <td className="py-1.5 px-2.5 text-center">
                        {isPres && (
                          <button
                            onClick={() => {
                              onSelectPfn(pg.pfn);
                              onClose();
                            }}
                            className="p-0.5 text-blue-600 hover:text-blue-900"
                            title="Inspect PFN"
                          >
                            <ArrowUpRight className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};
