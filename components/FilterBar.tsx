"use client";

import React from "react";
import { Filter, Sparkles } from "lucide-react";

interface FilterBarProps {
  activeFilter: string;
  onFilterChange: (filter: string) => void;
  hasHighlightedProcess: boolean;
  onClearHighlight: () => void;
}

export const FilterBar: React.FC<FilterBarProps> = ({
  activeFilter,
  onFilterChange,
  hasHighlightedProcess,
  onClearHighlight,
}) => {
  const filters = [
    { id: "all", label: "All Pages" },
    { id: "used", label: "Used" },
    { id: "free", label: "Free" },
    { id: "kernel", label: "Kernel / Cache" },
    { id: "unknown", label: "Unknown / Other" },
  ];

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 lg:px-8 mt-3">
      <div className="flex items-center flex-wrap gap-2">
        <div className="flex items-center gap-1 text-xs text-slate-500 mr-1 font-medium">
          <Filter className="h-3.5 w-3.5 text-slate-600" />
          <span>Filter State:</span>
        </div>

        <div className="flex items-center gap-1 bg-white p-1 rounded-md border border-slate-200 shadow-xs">
          {filters.map((f) => (
            <button
              key={f.id}
              onClick={() => onFilterChange(f.id)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition ${
                activeFilter === f.id
                  ? "bg-slate-900 text-white"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
              }`}
            >
              {f.label}
            </button>
          ))}

          {hasHighlightedProcess && (
            <button
              onClick={() => onFilterChange(activeFilter === "process_only" ? "all" : "process_only")}
              className={`px-2.5 py-1 rounded text-xs font-medium transition flex items-center gap-1 ${
                activeFilter === "process_only"
                  ? "bg-rose-600 text-white"
                  : "text-rose-600 hover:bg-rose-50"
              }`}
            >
              <Sparkles className="h-3 w-3" />
              <span>Process Mapped Only</span>
            </button>
          )}
        </div>
      </div>

      {hasHighlightedProcess && (
        <button
          onClick={onClearHighlight}
          className="text-xs text-slate-500 hover:text-rose-600 underline transition font-medium"
        >
          Clear Process Highlight
        </button>
      )}
    </div>
  );
};
