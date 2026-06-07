import { useEffect, useState, useRef } from 'react';
import { useAppStore } from '@/stores/appStore';

export function LoadingScreen() {
  const { setIsLoading } = useAppStore();
  const [phase, setPhase] = useState<'blocks' | 'text' | 'done'>('blocks');
  const hasAnimated = useRef(false);

  useEffect(() => {
    if (hasAnimated.current) return;
    hasAnimated.current = true;
    const t1 = setTimeout(() => setPhase('text'), 600);
    const t2 = setTimeout(() => {
      setPhase('done');
      setTimeout(() => setIsLoading(false), 200);
    }, 1400);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [setIsLoading]);

  if (phase === 'done') {
    return (
      <div
        className="fixed inset-0 z-[100] bg-[#0a0a0c] animate-slide-up"
        style={{ animationFillMode: 'forwards' }}
      />
    );
  }

  const showBlocks = phase === 'blocks';
  const showText = phase === 'text';

  return (
    <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-[#0a0a0c]">
      {/* 3 golden blocks */}
      <div className="flex items-center gap-3 mb-6">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="w-5 h-5 bg-[#d4af37] rounded-[2px]"
            style={{
              animation: showBlocks ? `logo-pulse 0.6s steps(4) ${i * 0.15}s forwards` : undefined,
              opacity: showText ? 1 : (showBlocks ? 0.3 : 1),
              transform: showText ? 'scale(1)' : (showBlocks ? 'scale(0.8)' : 'scale(1)'),
              transition: 'all 0.3s ease-out',
            }}
          />
        ))}
      </div>

      {/* Logo text */}
      <div
        className="text-[#d4af37] text-sm font-bold tracking-[0.05em] opacity-0"
        style={{
          animation: showText ? 'logo-text 0.5s ease-out forwards' : undefined,
        }}
      >
        VSE TOOLBOX
      </div>
    </div>
  );
}
