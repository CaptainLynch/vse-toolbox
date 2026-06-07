import React from 'react';
import { GripVertical } from 'lucide-react';
import { cn } from '@/lib/utils';

interface DraggableCardProps {
  id: string;
  title?: string;
  className?: string;
  children: React.ReactNode;
}

export function DraggableCard({ id, title, className, children }: DraggableCardProps) {
  return (
    <div
      key={id}
      className={cn(
        'bg-[#141416] border border-[#2a2a2e] rounded-[4px] overflow-hidden h-full flex flex-col',
        className
      )}
    >
      {title && (
        <div className="drag-handle px-4 py-2 border-b border-[#2a2a2e] cursor-grab active:cursor-grabbing flex items-center justify-between flex-shrink-0">
          <span className="text-xs text-[#8a8f98] font-medium">{title}</span>
          <GripVertical className="w-3 h-3 text-[#3a3a3e]" />
        </div>
      )}
      <div className="flex-1 overflow-auto">
        {children}
      </div>
    </div>
  );
}
