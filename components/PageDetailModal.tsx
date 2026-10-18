"use client";

import React from "react";
import { X, Database, Tag, Users } from "lucide-react";
import { PageDetail } from "@/types/ram";
import { formatBytes } from "@/lib/api";

interface PageDetailModalProps {
  pageDetail: PageDetail | null;
  isLoading: boolean;
  onClose: () => void;
  onSelectProcessPid?: (pid: number) => void;
}

export const PageDetailModal: React.FC<PageDetailModalProps> = ({
  pageDetail,
  isLoading,
  onClose,
  onSelectProcessPid,
}) => {
  if (!pageDetail && !isLoading) return null;

  const pfn = pageDetail?.pfn ?? 0;
  const status = pageDetail?.status ?? "unknown";
  const address = pageDetail?.physicalAddressHex ?? pageDetail?.physical_address_hex ?? "0x0";
  const pageSize = pageDetail?.pageSize ?? pageDetail?.page_size ?? 4096;
  const mapCount = pageDetail?.mapCount ?? pageDetail?.map_count ?? 0;
  const rawFlags = pageDetail?.rawFlagsHex ?? pageDetail?.raw_flags_hex ?? "0x0";
  const flags = pageDetail?.flags ?? [];
  const mappedProcesses = pageDetail?.mappedProcesses ?? pageDetail?.mapped_processes ?? [];
  const note = pageDetail?.note;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs animate-in fade-in duration-150">
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-5 shadow-xl flex flex-col gap-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-md bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-800">
              <Database className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-slate-900">
                  Physical Page Frame #{pfn}
                </h3>
                <span className="px-1.5 py-0.5 rounded text-xs font-mono font-bold uppercase bg-slate-100 border border-slate-200 text-slate-700">
                  {status}
                </span>
              </div>
              <p className="text-xs text-slate-500 font-mono mt-0.5">
                Address: <span className="text-blue-600">{address}</span> ({pageSize} Bytes)
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {isLoading ? (
          <div className="h-32 flex items-center justify-center text-xs font-mono text-slate-600">
            Querying Linux kernel page metadata...
          </div>
        ) : (
          <div className="space-y-3">
            {/* Quick Metrics */}
            <div className="grid grid-cols-3 gap-2 text-xs font-mono">
              <div className="p-2.5 rounded bg-slate-50 border border-slate-200">
                <div className="font-sans text-slate-500 text-[11px]">Map Count</div>
                <div className="text-sm font-bold text-slate-900 mt-0.5">{mapCount}</div>
              </div>
              <div className="p-2.5 rounded bg-slate-50 border border-slate-200">
                <div className="font-sans text-slate-500 text-[11px]">Raw Flags</div>
                <div className="text-sm font-bold text-slate-900 mt-0.5">{rawFlags}</div>
              </div>
              <div className="p-2.5 rounded bg-slate-50 border border-slate-200">
                <div className="font-sans text-slate-500 text-[11px]">Page Size</div>
                <div className="text-sm font-bold text-slate-900 mt-0.5">{formatBytes(pageSize)}</div>
              </div>
            </div>

            {/* Flags */}
            <div className="p-3 rounded bg-slate-50 border border-slate-200 space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                <Tag className="h-3.5 w-3.5 text-slate-600" />
                <span>Decoded Kernel Page Flags</span>
              </div>

              {flags.length > 0 ? (
                <div className="flex flex-wrap gap-1 pt-1">
                  {flags.map((flag, idx) => (
                    <span
                      key={idx}
                      className="px-2 py-0.5 rounded text-[11px] font-mono bg-white border border-slate-200 text-slate-700 shadow-2xs"
                    >
                      {flag}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-slate-500 italic">No specific page flags set</div>
              )}
            </div>

            {/* Mapped processes */}
            <div className="p-3 rounded bg-slate-50 border border-slate-200 space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                <Users className="h-3.5 w-3.5 text-slate-600" />
                <span>Mapped User Processes</span>
              </div>

              {mappedProcesses.length > 0 ? (
                <div className="divide-y divide-slate-200 border border-slate-200 rounded overflow-hidden bg-white">
                  {mappedProcesses.map((proc, i) => (
                    <div
                      key={i}
                      className="p-2 flex items-center justify-between text-xs hover:bg-slate-50"
                    >
                      <span className="font-semibold text-slate-800">
                        {proc.name} (PID {proc.pid})
                      </span>
                      {onSelectProcessPid && (
                        <button
                          onClick={() => {
                            onSelectProcessPid(proc.pid);
                            onClose();
                          }}
                          className="text-blue-600 hover:underline font-mono text-[11px]"
                        >
                          View Process
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-slate-600 font-mono py-1">
                  {note || "No user-space process mapping identified"}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
