"use client";

import React from "react";
import { Server, Activity, CheckCircle2, FileText, Database, HardDrive } from "lucide-react";
import { RamInfo } from "@/types/ram";
import { formatBytes, formatNumber } from "@/lib/api";

interface SummaryCardsProps {
  ram: RamInfo | null;
}

export const SummaryCards: React.FC<SummaryCardsProps> = ({ ram }) => {
  const total = ram?.totalBytes ?? ram?.total_bytes ?? 0;
  const used = ram?.usedBytes ?? ram?.used_bytes ?? 0;
  const avail = ram?.availableBytes ?? ram?.available_bytes ?? 0;
  const free = ram?.freeBytes ?? ram?.free_bytes ?? 0;
  const pageSize = ram?.pageSize ?? ram?.page_size ?? 4096;
  const totalPages = ram?.totalPages ?? ram?.total_pages ?? (total > 0 ? Math.floor(total / pageSize) : 0);
  const maxPfn = ram?.maxPfn ?? ram?.max_pfn ?? totalPages;
  const usagePct = ram?.usagePercentage ?? ram?.usage_percentage ?? ((total > 0) ? (used / total * 100) : 0);
  const cached = ram?.cachedBytes ?? ram?.cached_bytes ?? 0;
  const slab = ram?.slabBytes ?? ram?.slab_bytes ?? 0;

  const cards = [
    {
      label: "Total Physical RAM",
      value: formatBytes(total),
      sub: `${formatNumber(totalPages)} Pages`,
      icon: Server,
    },
    {
      label: "Used RAM",
      value: formatBytes(used),
      sub: `${usagePct.toFixed(1)}% Allocated`,
      icon: Activity,
    },
    {
      label: "Available RAM",
      value: formatBytes(avail),
      sub: `${formatBytes(free)} Free`,
      icon: CheckCircle2,
    },
    {
      label: "Physical Page Size",
      value: formatBytes(pageSize),
      sub: `${pageSize} Bytes Architecture`,
      icon: FileText,
    },
    {
      label: "Total Physical Pages",
      value: formatNumber(totalPages),
      sub: `Max PFN: 0x${maxPfn.toString(16).toUpperCase()}`,
      icon: Database,
    },
    {
      label: "Kernel & Cache",
      value: formatBytes(cached + slab),
      sub: `Slab: ${formatBytes(slab)}`,
      icon: HardDrive,
    },
  ];

  return (
    <div className="space-y-3 px-4 lg:px-8 mt-4">
      {/* Top 6 Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {cards.map((c, i) => {
          const Icon = c.icon;
          return (
            <div
              key={i}
              className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-xs transition hover:border-slate-300"
            >
              <div className="flex items-center justify-between mb-1.5 text-slate-500 text-xs">
                <span className="font-medium">{c.label}</span>
                <Icon className="h-3.5 w-3.5 text-slate-400" />
              </div>
              <div className="text-lg font-bold font-mono text-slate-900 tracking-tight">
                {c.value}
              </div>
              <div className="text-[11px] text-slate-500 font-mono mt-0.5 truncate">
                {c.sub}
              </div>
            </div>
          );
        })}
      </div>

      {/* Clean Linear Memory Allocation Bar */}
      <div className="rounded-lg border border-slate-200 bg-white p-3 space-y-2">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <div className="flex items-center gap-4">
            <span className="font-semibold text-slate-900">RAM Allocation Breakdown</span>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-blue-600 inline-block" />
                Used ({formatBytes(used)})
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500 inline-block" />
                Available ({formatBytes(avail)})
              </span>
              {cached > 0 && (
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm bg-amber-500 inline-block" />
                  Cache ({formatBytes(cached)})
                </span>
              )}
            </div>
          </div>
          <span className="font-mono font-semibold text-slate-800">
            {usagePct.toFixed(1)}% Used
          </span>
        </div>

        <div className="h-2.5 w-full overflow-hidden rounded bg-slate-100 flex border border-slate-200">
          {total > 0 && (
            <>
              <div
                style={{ width: `${(used / total) * 100}%` }}
                className="h-full bg-blue-600 transition-all duration-300"
                title="Used RAM"
              />
              <div
                style={{ width: `${(avail / total) * 100}%` }}
                className="h-full bg-emerald-500 transition-all duration-300"
                title="Available RAM"
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
};
