import React from 'react';
import { useState, useEffect, useCallback, useRef } from 'react';
import GridLayout from 'react-grid-layout';
import type { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { useAppStore } from '@/stores/appStore';
import { defaultLayouts } from '@/config/defaultLayouts';
import { verticalCompactor } from 'react-grid-layout';

interface DraggableGridProps {
  pageKey: string;
  children: React.ReactNode;
  cols?: number;
  rowHeight?: number;
}

let saveTimer: ReturnType<typeof setTimeout>;

export function DraggableGrid({ pageKey, children, cols = 4, rowHeight = 120 }: DraggableGridProps) {
  const { layouts, fetchLayouts, saveLayouts } = useAppStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1200);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width);
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    fetchLayouts(pageKey);
  }, [pageKey]);

  const dbLayout = layouts[pageKey];
  const currentLayout = (dbLayout && dbLayout.length > 0)
    ? dbLayout
    : (defaultLayouts[pageKey] ?? []);

  const toGrid: Layout = currentLayout.map((c) => ({
    i: c.cardId,
    x: c.x,
    y: c.y,
    w: c.w,
    h: c.h,
  }));

  const handleLayoutChange = useCallback(
    (newLayout: Layout) => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        const updated = newLayout.map((l) => ({
          pageKey,
          cardId: l.i,
          cardType: currentLayout.find((c) => c.cardId === l.i)?.cardType ?? 'custom',
          x: l.x,
          y: l.y,
          w: l.w,
          h: l.h,
        }));
        saveLayouts(pageKey, updated);
      }, 500);
    },
    [pageKey, currentLayout]
  );

  return (
    <div ref={containerRef}>
      <GridLayout
        className="layout"
        layout={toGrid}
        gridConfig={{ cols, rowHeight, margin: [12, 12] as const, containerPadding: null, maxRows: Infinity }}
        width={width}
        onLayoutChange={handleLayoutChange}
        dragConfig={{ enabled: true, bounded: false, handle: '.drag-handle', cancel: 'button,input,textarea,select,option,.no-drag', threshold: 3 }}
        resizeConfig={{ enabled: true, handles: ['nw', 'ne', 'sw', 'se'] as const }}
        compactor={verticalCompactor}
      >
        {React.Children.map(children, (child) => {
          if (!React.isValidElement(child)) return child;
          return (
            <div key={child.key}>
              {child}
            </div>
          );
        })}
      </GridLayout>
    </div>
  );
}
