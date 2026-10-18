"use client";

import React, { useState, useMemo } from "react";
import { Search, ArrowUpDown, Cpu, Eye, Sparkles } from "lucide-react";
import { ProcessInfo } from "@/types/ram";
import { formatBytes, formatNumber } from "@/lib/api";

interface ProcessTableProps {
  processes: ProcessInfo[];
  selectedPid: number | null;
  onSelectProcess: (process: ProcessInfo) => void;
  onHighlightProcess: (process: ProcessInfo) => void;
  highlightedPid: number | null;
  totalRamBytes?: number;
}

type SortField = "name" | "pid" | "rss" | "pss" | "vsz" | "residentPages" | "memoryPercent";
type SortOrder = "asc" | "desc";

export const ProcessTable: React.FC<ProcessTableProps> = ({
  processes,
  selectedPid,
  onSelectProcess,
  onHighlightProcess,
  highlightedPid,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [sortField, setSortField] = useState<SortField>("rss");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortOrder("desc");
    }
  };

  const filteredAndSorted = useMemo(() => {
    return processes
      .filter((p) => {
        const query = searchTerm.toLowerCase();
        return (
          p.name.toLowerCase().includes(query) ||
          p.pid.toString().includes(query) ||
          (p.user && p.user.toLowerCase().includes(query))
        );
      })
      .sort((a, b) => {
        let valA: string | number = a[sortField] ?? 0;
        let valB: string | number = b[sortField] ?? 0;

        if (sortField === "pss") {
          valA = a.pss ?? a.rss ?? 0;
          valB = b.pss ?? b.rss ?? 0;
        } else if (sortField === "residentPages") {
          valA = a.residentPages ?? a.resident_pages ?? 0;
          valB = b.residentPages ?? b.resident_pages ?? 0;
        } else if (sortField === "memoryPercent") {
          valA = a.memoryPercent ?? a.memory_percent ?? 0;
          valB = b.memoryPercent ?? b.memory_percent ?? 0;
        }

        if (typeof valA === "string" && typeof valB === "string") {
          return sortOrder === "asc" ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }

        const numA = Number(valA) || 0;
        const numB = Number(valB) || 0;
        return sortOrder === "asc" ? numA - numB : numB - numA;
      });
  }, [processes, searchTerm, sortField, sortOrder]);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-xs flex flex-col gap-3">
      {/* Header & Search */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-slate-700" />
          <h2 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
            Process Memory Statistics
          </h2>
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600 font-mono">
            {filteredAndSorted.length} Active Processes
          </span>
        </div>

        {/* Search */}
        <div className="relative min-w-[200px]">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
          <input
            type="text"
            placeholder="Search PID or Name..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-8 pr-3 py-1 rounded border border-slate-200 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-slate-400"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-slate-50 text-slate-600 font-mono uppercase text-[11px] border-b border-slate-200">
            <tr>
              <th
                onClick={() => handleSort("name")}
                className="py-2 px-3 cursor-pointer hover:text-slate-900 transition"
              >
                <div className="flex items-center gap-1">
                  <span>Process Name</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th
                onClick={() => handleSort("pid")}
                className="py-2 px-3 cursor-pointer hover:text-slate-900 transition text-right"
              >
                <div className="flex items-center justify-end gap-1">
                  <span>PID</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th
                onClick={() => handleSort("rss")}
                className="py-2 px-3 cursor-pointer hover:text-slate-900 transition text-right"
              >
                <div className="flex items-center justify-end gap-1">
                  <span>RSS</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th
                onClick={() => handleSort("pss")}
                className="py-2 px-3 cursor-pointer hover:text-slate-900 transition text-right"
                title="Proportional Set Size"
              >
                <div className="flex items-center justify-end gap-1">
                  <span>PSS</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th
                onClick={() => handleSort("vsz")}
                className="py-2 px-3 cursor-pointer hover:text-slate-900 transition text-right"
              >
                <div className="flex items-center justify-end gap-1">
                  <span>VSZ</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th
                onClick={() => handleSort("residentPages")}
                className="py-2 px-3 cursor-pointer hover:text-slate-900 transition text-right"
              >
                <div className="flex items-center justify-end gap-1">
                  <span>Pages</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th className="py-2 px-3 text-center">Inspect</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filteredAndSorted.map((p) => {
              const isSelected = selectedPid === p.pid;
              const isHighlighted = highlightedPid === p.pid;
              const residentCount = p.residentPages ?? p.resident_pages ?? 0;

              return (
                <tr
                  key={p.pid}
                  onClick={() => onSelectProcess(p)}
                  className={`group cursor-pointer transition hover:bg-slate-50 ${
                    isSelected ? "bg-blue-50/70 font-medium" : ""
                  }`}
                >
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-2">
                      <div
                        className={`h-2 w-2 rounded-full ${
                          isHighlighted ? "bg-rose-500" : "bg-slate-300 group-hover:bg-blue-600"
                        }`}
                      />
                      <span className="font-semibold text-slate-900 group-hover:text-blue-600">
                        {p.name}
                      </span>
                    </div>
                  </td>
                  <td className="py-2 px-3 font-mono text-slate-600 text-right">{p.pid}</td>
                  <td className="py-2 px-3 font-mono text-slate-900 text-right font-semibold">
                    {formatBytes(p.rss)}
                  </td>
                  <td className="py-2 px-3 font-mono text-slate-700 text-right">
                    {p.pss !== null && p.pss !== undefined ? formatBytes(p.pss) : "--"}
                  </td>
                  <td className="py-2 px-3 font-mono text-slate-500 text-right">
                    {formatBytes(p.vsz)}
                  </td>
                  <td className="py-2 px-3 font-mono text-slate-700 text-right">
                    {formatNumber(residentCount)}
                  </td>
                  <td className="py-2 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-center gap-1">
                      <button
                        onClick={() => onSelectProcess(p)}
                        className="p-1 rounded hover:bg-slate-200 text-slate-600 hover:text-slate-900 transition"
                        title="Inspect process physical pages"
                      >
                        <Eye className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => onHighlightProcess(p)}
                        className={`p-1 rounded transition ${
                          isHighlighted
                            ? "bg-rose-100 text-rose-700 font-bold"
                            : "hover:bg-slate-200 text-slate-400 hover:text-rose-600"
                        }`}
                        title={
                          isHighlighted
                            ? "Clear RAM highlight"
                            : "Highlight mapped pages on RAM canvas"
                        }
                      >
                        <Sparkles className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
