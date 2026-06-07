import type { LayoutCard } from '@/types';

export const defaultLayouts: Record<string, LayoutCard[]> = {
  overview: [
    { pageKey: 'overview', cardId: 'kpi-open', cardType: 'kpi', x: 0, y: 0, w: 1, h: 1 },
    { pageKey: 'overview', cardId: 'kpi-new', cardType: 'kpi', x: 1, y: 0, w: 1, h: 1 },
    { pageKey: 'overview', cardId: 'kpi-closed', cardType: 'kpi', x: 2, y: 0, w: 1, h: 1 },
    { pageKey: 'overview', cardId: 'kpi-risk', cardType: 'kpi', x: 3, y: 0, w: 1, h: 1 },
    { pageKey: 'overview', cardId: 'deliverable-nav', cardType: 'custom', x: 0, y: 1, w: 2, h: 2 },
    { pageKey: 'overview', cardId: 'trend-chart', cardType: 'area', x: 2, y: 1, w: 2, h: 2 },
    { pageKey: 'overview', cardId: 'milestones', cardType: 'milestone', x: 0, y: 3, w: 2, h: 2 },
    { pageKey: 'overview', cardId: 'dept-stats', cardType: 'bar', x: 2, y: 3, w: 2, h: 2 },
  ],
  issues: [
    { pageKey: 'issues', cardId: 'issue-kpi', cardType: 'kpi', x: 0, y: 0, w: 4, h: 1 },
    { pageKey: 'issues', cardId: 'issue-table', cardType: 'table', x: 0, y: 1, w: 3, h: 3 },
    { pageKey: 'issues', cardId: 'issue-milestones', cardType: 'milestone', x: 3, y: 1, w: 1, h: 3 },
  ],
  ewo: [
    { pageKey: 'ewo', cardId: 'ewo-kpi', cardType: 'kpi', x: 0, y: 0, w: 4, h: 1 },
    { pageKey: 'ewo', cardId: 'ewo-table', cardType: 'table', x: 0, y: 1, w: 4, h: 3 },
  ],
  tir: [
    { pageKey: 'tir', cardId: 'tir-kpi', cardType: 'kpi', x: 0, y: 0, w: 4, h: 1 },
    { pageKey: 'tir', cardId: 'tir-table', cardType: 'table', x: 0, y: 1, w: 4, h: 3 },
  ],
};
