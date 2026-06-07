import React from 'react';
import { useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { AnalyticsOverview } from './AnalyticsOverview';
import { DeliverableIssues } from './DeliverableIssues';
import { DeliverableEWO } from './DeliverableEWO';
import { DeliverableTIR } from './DeliverableTIR';
import { SubPageNav } from '@/components/SubPageNav';

const subPages: Record<string, { label: string }> = {
  overview: { label: '项目总览' },
  issues: { label: '造车问题' },
  ewo: { label: 'EWO/NCR' },
  tir: { label: 'TIR' },
};

export function AnalyticsLayout() {
  const { activeSubPage, setActiveSubPage } = useAppStore();

  const renderSubPage = () => {
    switch (activeSubPage) {
      case 'issues':
        return <DeliverableIssues />;
      case 'ewo':
        return <DeliverableEWO />;
      case 'tir':
        return <DeliverableTIR />;
      default:
        return <AnalyticsOverview onNavigate={setActiveSubPage} />;
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      <div className="flex-1 overflow-auto">
        {renderSubPage()}
      </div>
      <SubPageNav
        pages={subPages}
        active={activeSubPage}
        onChange={setActiveSubPage}
      />
    </div>
  );
}