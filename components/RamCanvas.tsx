"use client";

import React, { useRef, useEffect, useState } from "react";
import { ZoomIn, ZoomOut, RotateCcw, Crosshair, Sparkles, ChevronLeft, ChevronRight } from "lucide-react";
import { PageBlockSummary, PagesMapResponse } from "@/types/ram";
import { formatBytes, formatNumber } from "@/lib/api";

interface RamCanvasProps {
  mapData: PagesMapResponse | null;
  highlightedPfns: Set<number>;
  highlightedProcessName?: string | null;
  activeFilter: string;
  onSelectPfn: (pfn: number) => void;
  onSelectBlock: (block: PageBlockSummary) => void;
  onZoomChange: (startPfn: number, count: number) => void;
  onResolutionChange?: (res: number) => void;
  selectedResolution: number;
  isLoading: boolean;
}

const LIGHT_COLOR_MAP: Record<string, string> = {
  used: "#2563eb",       // Blue 600
  free: "#16a34a",       // Green 600
  kernel: "#d97706",     // Amber 600
  reserved: "#64748b",   // Slate 500
  allocated: "#0891b2",  // Cyan 600 (Distinct from Green Free & Blue Used)
  unknown: "#94a3b8",    // Slate 400
  mixed: "#7c3aed",      // Purple 600
  highlight: "#e11d48",  // Rose 600
};

export const RamCanvas: React.FC<RamCanvasProps> = ({
  mapData,
  highlightedPfns,
  highlightedProcessName,
  activeFilter,
  onSelectPfn,
  onSelectBlock,
  onZoomChange,
  onResolutionChange,
  selectedResolution,
  isLoading,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const [hoveredBlock, setHoveredBlock] = useState<PageBlockSummary | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);
  const [selectedBlock, setSelectedBlock] = useState<PageBlockSummary | null>(null);
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [pfnInput, setPfnInput] = useState<string>("");

  const blocks = React.useMemo(() => mapData?.blocks ?? mapData?.pages ?? [], [mapData]);
  const totalPages = mapData?.totalPages ?? mapData?.total_pages ?? 1048576;
  const maxPfnSpan = Math.max(totalPages, mapData?.maxPFN ?? mapData?.max_pfn ?? totalPages);
  const currentStart = mapData?.startPFN ?? mapData?.start_pfn ?? 0;
  const currentEnd = mapData?.endPFN ?? mapData?.end_pfn ?? maxPfnSpan;
  const currentCount = currentEnd - currentStart;

  // Render 2D grid on Canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !blocks || blocks.length === 0) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

    // Background
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);

    const cols = Math.min(64, Math.ceil(Math.sqrt(blocks.length * (width / height))));
    const rows = Math.ceil(blocks.length / cols);

    const cellGap = 1.5;
    const cellWidth = Math.max(2, (width - (cols + 1) * cellGap) / cols);
    const cellHeight = Math.max(2, (height - (rows + 1) * cellGap) / rows);

    blocks.forEach((block, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);

      const x = cellGap + col * (cellWidth + cellGap);
      const y = cellGap + row * (cellHeight + cellGap);

      const startP = block.startPFN ?? block.start_pfn ?? 0;
      const endP = block.endPFN ?? block.end_pfn ?? 0;
      const count = block.pageCount ?? block.page_count ?? 1;

      // Check if any PFN in this block is highlighted
      let isHighlighted = false;
      if (highlightedPfns.size > 0) {
        if (count <= 64) {
          for (let p = startP; p < endP; p++) {
            if (highlightedPfns.has(p)) {
              isHighlighted = true;
              break;
            }
          }
        } else {
          for (const hp of highlightedPfns) {
            if (hp >= startP && hp < endP) {
              isHighlighted = true;
              break;
            }
          }
        }
      }

      // Base color
      const baseColor = LIGHT_COLOR_MAP[block.status] || LIGHT_COLOR_MAP.unknown;

      // Filter dimming
      let alpha = 1.0;
      if (activeFilter !== "all") {
        if (activeFilter === "process_only") {
          alpha = isHighlighted ? 1.0 : 0.15;
        } else if (block.status !== activeFilter) {
          alpha = 0.15;
        }
      }

      ctx.globalAlpha = alpha;
      ctx.fillStyle = isHighlighted ? LIGHT_COLOR_MAP.highlight : baseColor;
      ctx.fillRect(x, y, cellWidth, cellHeight);

      // Selected block border
      const isSelected = selectedBlock && (selectedBlock.startPFN ?? selectedBlock.start_pfn) === startP;
      if (isSelected) {
        ctx.globalAlpha = 1.0;
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 2;
        ctx.strokeRect(x - 0.5, y - 0.5, cellWidth + 1, cellHeight + 1);
      }

      // Highlighted stroke
      if (isHighlighted) {
        ctx.globalAlpha = 1.0;
        ctx.strokeStyle = "#be123c";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x - 0.5, y - 0.5, cellWidth + 1, cellHeight + 1);
      }
    });

    ctx.globalAlpha = 1.0;
  }, [blocks, highlightedPfns, activeFilter, selectedBlock]);

  // Handle Canvas Resize
  useEffect(() => {
    const handleResize = () => {
      const container = containerRef.current;
      const canvas = canvasRef.current;
      if (container && canvas) {
        const rect = container.getBoundingClientRect();
        canvas.width = Math.floor(rect.width);
        canvas.height = Math.max(300, Math.floor(rect.height || 360));
      }
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || blocks.length === 0) return;

    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const cols = Math.min(64, Math.ceil(Math.sqrt(blocks.length * (canvas.width / canvas.height))));
    const rows = Math.ceil(blocks.length / cols);

    const cellGap = 1.5;
    const cellWidth = Math.max(2, (canvas.width - (cols + 1) * cellGap) / cols);
    const cellHeight = Math.max(2, (canvas.height - (rows + 1) * cellGap) / rows);

    const col = Math.floor((mouseX - cellGap) / (cellWidth + cellGap));
    const row = Math.floor((mouseY - cellGap) / (cellHeight + cellGap));

    if (col >= 0 && col < cols && row >= 0 && row < rows) {
      const index = row * cols + col;
      if (index >= 0 && index < blocks.length) {
        setHoveredBlock(blocks[index]);
        setHoverPos({ x: e.clientX, y: e.clientY });
        return;
      }
    }
    setHoveredBlock(null);
  };

  const handleMouseLeave = () => {
    setHoveredBlock(null);
  };

  const handleClick = () => {
    if (hoveredBlock) {
      setSelectedBlock(hoveredBlock);
      onSelectBlock(hoveredBlock);
      const sPfn = hoveredBlock.startPFN ?? hoveredBlock.start_pfn ?? 0;
      onSelectPfn(sPfn);
    }
  };

  const canPanLeft = currentStart > 0;
  const canPanRight = currentEnd < maxPfnSpan;
  const isZoomed = zoomLevel > 1 || currentCount < maxPfnSpan;

  const handleZoomIn = () => {
    const currentRatio = Math.max(1, Math.round(maxPfnSpan / Math.max(1, currentCount)));
    const baseZoom = Math.max(zoomLevel, currentRatio);
    const nextZoom = Math.min(baseZoom * 4, 1024);
    setZoomLevel(nextZoom);
    const newCount = Math.max(64, Math.floor(maxPfnSpan / nextZoom));
    const centerPfn = selectedBlock
      ? Math.floor(((selectedBlock.startPFN ?? selectedBlock.start_pfn ?? 0) + (selectedBlock.endPFN ?? selectedBlock.end_pfn ?? 0)) / 2)
      : Math.floor((currentStart + currentEnd) / 2);
    const newStart = Math.max(0, Math.min(maxPfnSpan - newCount, centerPfn - Math.floor(newCount / 2)));
    onZoomChange(newStart, newCount);
  };

  const handleZoomOut = () => {
    const currentRatio = Math.max(1, Math.round(maxPfnSpan / Math.max(1, currentCount)));
    const baseZoom = Math.max(zoomLevel, currentRatio);
    const nextZoom = Math.max(1, Math.floor(baseZoom / 4));
    setZoomLevel(nextZoom);
    const newCount = Math.min(maxPfnSpan, Math.floor(maxPfnSpan / nextZoom));
    const centerPfn = Math.floor((currentStart + currentEnd) / 2);
    const newStart = Math.max(0, Math.min(maxPfnSpan - newCount, centerPfn - Math.floor(newCount / 2)));
    onZoomChange(newStart, newCount);
  };

  const handleResetZoom = () => {
    setZoomLevel(1);
    onZoomChange(0, maxPfnSpan);
  };

  const handlePanLeft = () => {
    if (!canPanLeft) return;
    const step = Math.max(1, Math.floor(currentCount / 2));
    const newStart = Math.max(0, currentStart - step);
    onZoomChange(newStart, currentCount);
  };

  const handlePanRight = () => {
    if (!canPanRight) return;
    const step = Math.max(1, Math.floor(currentCount / 2));
    const newStart = Math.max(0, Math.min(maxPfnSpan - currentCount, currentStart + step));
    onZoomChange(newStart, currentCount);
  };

  const handleGoToPfn = (e: React.FormEvent) => {
    e.preventDefault();
    const raw = pfnInput.trim().replace(/,/g, "");
    if (!raw) return;

    const parsed = raw.toLowerCase().startsWith("0x")
      ? parseInt(raw, 16)
      : parseInt(raw, 10);
    if (Number.isNaN(parsed) || parsed < 0) return;

    const targetPfn = Math.min(Math.max(0, maxPfnSpan - 1), parsed);
    // If at 1x full view, zoom into a focused window around targetPfn; if already zoomed in, keep current window width
    const defaultWindow = Math.min(maxPfnSpan, Math.max(64, selectedResolution * 4));
    const span = currentCount < maxPfnSpan ? currentCount : defaultWindow;
    const newStart = Math.max(0, Math.min(maxPfnSpan - span, targetPfn - Math.floor(span / 2)));
    const nextZoom = Math.min(1024, Math.max(1, Math.round(maxPfnSpan / span)));

    setZoomLevel(nextZoom);
    onZoomChange(newStart, span);
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-xs flex flex-col gap-3">
      {/* Top Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2">
          <Crosshair className="h-4 w-4 text-slate-700" />
          <h2 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
            Physical Memory Map
          </h2>
          <span className="text-xs text-slate-500 font-mono">
            PFN {formatNumber(currentStart)} — {formatNumber(currentEnd)} ({formatBytes(currentCount * 4096)})
          </span>
        </div>

        <div className="flex items-center flex-wrap gap-2">
          {highlightedProcessName && (
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
              <Sparkles className="h-3 w-3 text-rose-600" />
              <span>{highlightedProcessName} ({highlightedPfns.size} mapped pages)</span>
            </div>
          )}

          {/* Go to PFN Jump Input */}
          <form onSubmit={handleGoToPfn} className="flex items-center gap-1">
            <input
              type="text"
              value={pfnInput}
              onChange={(e) => setPfnInput(e.target.value)}
              placeholder="Go to PFN (e.g. 250000)"
              className="w-36 px-2 py-1 rounded text-xs font-mono border border-slate-200 bg-white text-slate-800 placeholder-slate-400 focus:outline-none focus:border-slate-400"
              title="Enter a decimal or 0x hex PFN and press Enter to jump & zoom there"
            />
            <button
              type="submit"
              disabled={!pfnInput.trim()}
              className="px-2 py-1 rounded text-xs font-semibold bg-slate-900 hover:bg-slate-800 disabled:bg-slate-200 disabled:text-slate-400 text-white transition"
              title="Jump to PFN"
            >
              Go
            </button>
          </form>

          {/* Resolution Selector */}
          {onResolutionChange && (
            <select
              value={selectedResolution}
              onChange={(e) => onResolutionChange(Number(e.target.value))}
              className="px-2 py-1 rounded text-xs border border-slate-200 bg-white text-slate-700 focus:outline-none"
              title="Grid Resolution (Number of Aggregation Buckets)"
            >
              <option value={128}>128 Blocks</option>
              <option value={256}>256 Blocks</option>
              <option value={512}>512 Blocks</option>
              <option value={1024}>1024 Blocks</option>
            </select>
          )}

          {/* Pan & Zoom controls */}
          <div className="flex items-center gap-0.5 bg-slate-50 rounded border border-slate-200 p-0.5">
            <button
              type="button"
              onClick={handlePanLeft}
              disabled={!canPanLeft}
              className="p-1 rounded hover:bg-white text-slate-600 hover:text-slate-900 transition disabled:opacity-35"
              title="Pan Left (Earlier PFNs)"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={handlePanRight}
              disabled={!canPanRight}
              className="p-1 rounded hover:bg-white text-slate-600 hover:text-slate-900 transition disabled:opacity-35"
              title="Pan Right (Later PFNs)"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>

            <span className="h-3.5 w-px bg-slate-200 mx-0.5" />

            <button
              type="button"
              onClick={handleZoomIn}
              disabled={zoomLevel >= 1024}
              className="p-1 rounded hover:bg-white text-slate-600 hover:text-slate-900 transition disabled:opacity-40"
              title="Zoom In"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
            <span className="text-xs font-mono font-semibold text-slate-800 px-1">
              {Math.max(zoomLevel, Math.round(maxPfnSpan / Math.max(1, currentCount)))}x
            </span>
            <button
              type="button"
              onClick={handleZoomOut}
              disabled={!isZoomed}
              className="p-1 rounded hover:bg-white text-slate-600 hover:text-slate-900 transition disabled:opacity-40"
              title="Zoom Out"
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={handleResetZoom}
              disabled={!isZoomed}
              className="p-1 rounded hover:bg-white text-slate-500 hover:text-slate-900 transition disabled:opacity-40"
              title="Reset View (Full RAM)"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Simple Clean Legend */}
      <div className="flex items-center flex-wrap gap-4 text-xs font-medium text-slate-600">
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-xs bg-blue-600 inline-block" />
          <span>Used</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-xs bg-green-600 inline-block" />
          <span>Free</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-xs bg-amber-600 inline-block" />
          <span>Kernel / Cache</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-xs bg-cyan-600 inline-block ring-1 ring-cyan-700" />
          <span className="font-semibold text-cyan-800">Allocated (Project)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-xs bg-violet-600 inline-block" />
          <span>Mixed</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-xs bg-slate-500 inline-block" />
          <span>Reserved / Hole</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-xs bg-rose-600 inline-block" />
          <span>Process Mapped</span>
        </div>
      </div>

      {/* 2D Canvas Area */}
      <div
        ref={containerRef}
        className="w-full h-[320px] bg-slate-50 rounded border border-slate-200 overflow-hidden relative cursor-crosshair"
      >
        <canvas
          ref={canvasRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          onClick={handleClick}
          className="w-full h-full block"
        />

        {isLoading && (
          <div className="absolute inset-0 bg-white/60 flex items-center justify-center pointer-events-none">
            <span className="text-xs font-mono text-slate-800 bg-white px-3 py-1.5 rounded border border-slate-200 shadow-xs">
              Updating memory blocks...
            </span>
          </div>
        )}
      </div>

      {/* Hover Floating Tooltip */}
      {hoveredBlock && hoverPos && (
        <div
          className="fixed pointer-events-none z-50 rounded-md border border-slate-300 bg-white p-2.5 shadow-lg text-xs space-y-1 min-w-[220px]"
          style={{
            left: `${Math.min(window.innerWidth - 240, hoverPos.x + 14)}px`,
            top: `${Math.min(window.innerHeight - 140, hoverPos.y + 14)}px`,
          }}
        >
          <div className="flex items-center justify-between border-b border-slate-100 pb-1">
            <span className="font-bold text-slate-900 font-mono">
              PFN {hoveredBlock.startPFN ?? hoveredBlock.start_pfn} — {hoveredBlock.endPFN ?? hoveredBlock.end_pfn}
            </span>
            <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${
              hoveredBlock.status === "allocated"
                ? "bg-cyan-100 text-cyan-800 border border-cyan-300"
                : "bg-slate-100 text-slate-600"
            }`}>
              {hoveredBlock.status}
            </span>
          </div>

          <div className="text-[11px] font-mono text-slate-600 space-y-0.5">
            <div>
              <span className="text-slate-400">Address: </span>
              {hoveredBlock.startAddressHex ?? hoveredBlock.start_address_hex}
            </div>
            <div>
              <span className="text-slate-400">Span: </span>
              {formatNumber(hoveredBlock.pageCount ?? hoveredBlock.page_count ?? 1)} Pages ({formatBytes((hoveredBlock.pageCount ?? hoveredBlock.page_count ?? 1) * 4096)})
            </div>
            {(hoveredBlock.allocatedCount ?? hoveredBlock.allocated_count ?? 0) > 0 && (
              <div>
                <span className="text-cyan-700 font-semibold">Allocated: </span>
                <span className="text-cyan-900 font-bold">{formatNumber(hoveredBlock.allocatedCount ?? hoveredBlock.allocated_count ?? 0)} Pages</span>
              </div>
            )}
          </div>

          <div className="pt-0.5 text-[10px] text-blue-600 font-medium">
            Click to inspect detailed frame
          </div>
        </div>
      )}
    </div>
  );
};
