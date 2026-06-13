import React, { forwardRef } from 'react';
import { GripVertical, X } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface DraggableCardProps extends React.HTMLAttributes<HTMLDivElement> {
  id: string;
  title?: string;
  className?: string;
  children: React.ReactNode;
  onRemove?: () => void;
}

export const DraggableCard = forwardRef<HTMLDivElement, DraggableCardProps>(
  ({ id, title, className, children, onRemove, ...rest }, ref) => {
    return (
      <div
        ref={ref}
        key={id}
        {...rest}
        className={cn(
          'bg-[#141416] border border-[#2a2a2e] rounded-[4px] overflow-hidden h-full flex flex-col drag-handle cursor-grab active:cursor-grabbing group relative',
          className
        )}
      >
        {title && (
          <div className="drag-handle px-4 py-2 border-b border-[#2a2a2e] cursor-grab active:cursor-grabbing flex items-center justify-between flex-shrink-0">
            <span className="text-xs text-[#8a8f98] font-medium">{title}</span>
            <div className="flex items-center gap-2">
              {onRemove && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove();
                  }}
                  className="p-0.5 hover:bg-[#222225] rounded text-[#8a8f98] hover:text-red-400 transition-colors no-drag"
                  title="移除卡片"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
              <GripVertical className="w-3 h-3 text-[#3a3a3e]" />
            </div>
          </div>
        )}
        <div className="flex-1 overflow-auto">
          {children}
        </div>
      </div>
    );
  }
);

DraggableCard.displayName = 'DraggableCard';
