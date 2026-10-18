"use client";

import React from "react";
import { Info } from "lucide-react";
import { PrivilegeStatus } from "@/types/ram";

interface PrivilegeBannerProps {
  status: PrivilegeStatus | null;
}

export const PrivilegeBanner: React.FC<PrivilegeBannerProps> = ({ status }) => {
  if (!status) return null;

  const isPrivileged = status.is_root || status.can_read_kpageflags || status.privileged;
  if (isPrivileged) {
    return null;
  }

  return (
    <div className="mx-4 lg:mx-8 mt-4 rounded-lg border border-amber-200 bg-amber-50/80 p-3.5 text-amber-900 text-xs">
      <div className="flex items-start gap-2.5">
        <Info className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
        <div className="space-y-1 flex-1">
          <div className="font-semibold text-amber-900">
            Basic memory information available. Run the backend with elevated privileges for detailed physical-frame inspection.
          </div>
          <p className="text-amber-800 leading-relaxed">
            Linux restricts access to <code className="px-1 py-0.5 bg-amber-100 rounded font-mono text-[11px]">/proc/kpageflags</code> and <code className="px-1 py-0.5 bg-amber-100 rounded font-mono text-[11px]">/proc/&lt;pid&gt;/pagemap</code> to root or CAP_SYS_ADMIN. Global RAM metrics and process tables remain active.
          </p>
          <div className="pt-1 flex items-center gap-2 font-mono text-[11px] text-slate-700">
            <span>To start with full privileges:</span>
            <code className="bg-white border border-amber-200 px-2 py-0.5 rounded text-slate-900 font-semibold">
              sudo uvicorn app.main:app --host 0.0.0.0 --port 8000
            </code>
          </div>
        </div>
      </div>
    </div>
  );
};
