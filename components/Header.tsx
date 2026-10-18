"use client";

import React from "react";
import { Layers, RefreshCw, ShieldCheck, ShieldAlert, Cpu } from "lucide-react";
import { PrivilegeStatus } from "@/types/ram";

interface HeaderProps {
  status: PrivilegeStatus | null;
  lastUpdated: Date | null;
  isLive: boolean;
  onRefresh: () => void;
  isLoading: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  status,
  lastUpdated,
  isLive,
  onRefresh,
  isLoading,
}) => {
  const [secondsAgo, setSecondsAgo] = React.useState<string>("--");

  React.useEffect(() => {
    if (!lastUpdated) {
      return;
    }

    const updateAgo = () => {
      const diff = Math.max(0, Math.floor((Date.now() - lastUpdated.getTime()) / 1000));
      setSecondsAgo(`${diff}s ago`);
    };

    const initialTimeout = setTimeout(updateAgo, 0);
    const timer = setInterval(updateAgo, 1000);

    return () => {
      clearTimeout(initialTimeout);
      clearInterval(timer);
    };
  }, [lastUpdated]);

  const isPrivileged = status?.is_root || status?.can_read_kpageflags || status?.privileged;

  return (
    <header className="border-b border-slate-200 bg-white sticky top-0 z-40 px-4 lg:px-8 py-3 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="h-9 w-9 rounded-lg bg-slate-900 flex items-center justify-center text-white shadow-sm">
          <Layers className="h-5 w-5" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-slate-900 tracking-tight">
              RAMScope
            </h1>
            <span className="text-[11px] px-1.5 py-0.5 rounded font-mono font-medium bg-slate-100 text-slate-700 border border-slate-200">
              Linux Physical Memory
            </span>
          </div>
          <p className="text-xs text-slate-500 font-normal">
            Physical Memory Visualization & Monitoring System
          </p>
        </div>
      </div>

      <div className="flex items-center flex-wrap gap-2">
        {/* Kernel module status */}
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border ${
            status?.kernel_module_loaded
              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
              : "bg-slate-50 text-slate-600 border-slate-200"
          }`}
        >
          <Cpu className="h-3.5 w-3.5" />
          <span>{status?.kernel_module_loaded ? "/dev/ramscope Active" : "Procfs Interface"}</span>
        </div>

        {/* Privileges Badge */}
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border ${
            isPrivileged
              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
              : "bg-amber-50 text-amber-800 border-amber-200"
          }`}
        >
          {isPrivileged ? (
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
          ) : (
            <ShieldAlert className="h-3.5 w-3.5 text-amber-600" />
          )}
          <span>{isPrivileged ? "Elevated Access (Root)" : "Standard User Access"}</span>
        </div>

        {/* Live indicator & Refresh */}
        <div className="flex items-center gap-2 pl-2 border-l border-slate-200">
          <div className="flex items-center gap-1.5 text-xs text-slate-600 px-2.5 py-1 bg-slate-50 rounded border border-slate-200 font-mono">
            <span
              className={`h-2 w-2 rounded-full ${
                isLive ? "bg-emerald-500 animate-pulse" : "bg-slate-400"
              }`}
            />
            <span>Live • {secondsAgo}</span>
          </div>

          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="p-1.5 rounded bg-white hover:bg-slate-100 border border-slate-200 text-slate-700 transition disabled:opacity-50"
            title="Refresh Memory Data"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin text-slate-900" : ""}`} />
          </button>
        </div>
      </div>
    </header>
  );
};
