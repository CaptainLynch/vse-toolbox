const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { buildContext } = require('../web/static/node-overview.js');
const data = {
  phase: { today: '2026-09-13' },
  milestones: [
    {id: 3, name:'Later', date:'2026-10-10', sortOrder:3, status:'未开始'},
    {id: 1, name:'Done', date:'2026-09-01', sortOrder:1, status:'已完成'},
    {id: 2, name:'Overdue', date:'2026-09-10', sortOrder:2, status:'已超期'},
  ],
  deliverables: [
    {id:'a',name:'A',status:'已完成',note:'无',syncDisplay:{state:'manual'}},
    {id:'b',name:'B',status:'已逾期',note:'等待批准',syncDisplay:{state:'manual'}},
    {id:'c',name:'C',status:'已完成',note:'待同步',syncDisplay:{state:'sync_failed'}},
  ],
};
let ctx=buildContext(data);
assert.equal(ctx.node.id,2); // Overdue node must not be skipped based on today's date.
assert.equal(ctx.days,-3);
assert.equal(ctx.ruleConfigured,false);
assert.equal(ctx.completed,null); // Unknown is never 0%/all complete.
assert.equal(ctx.items.length,0);
assert.equal(ctx.projectRisks.length,1);
assert.equal(ctx.projectDataIssues.length,1);
ctx=buildContext(data,{'2':['a','b','c']});
assert.equal(ctx.ruleConfigured,true);
assert.equal(ctx.completed,1);
assert.equal(ctx.total,3);
assert.equal(ctx.risks.length,1);
assert.equal(ctx.dataIssues.length,1); // Sync failure is not business completion/risk.
ctx=buildContext(data,{'2':[]});
assert.equal(ctx.ruleConfigured,true);
assert.equal(ctx.total,0);
assert.equal(ctx.progress,null);
assert.equal(buildContext(data,{'2':['missing']}).ruleConfigured,false);
const undated=structuredClone(data);undated.milestones[2].date=null;
assert.equal(buildContext(undated).node.id,2);
assert.equal(buildContext(undated).days,null);
const allDone=structuredClone(data);allDone.milestones.forEach(m=>m.status='已完成');
assert.equal(buildContext(allDone).node,null);
assert.equal(buildContext({phase:{},milestones:[],deliverables:[]}).node,null);
const stale=structuredClone(data);
stale.deliverables[0].syncDisplay={state:'snapshot',syncState:'failed'};
const staleContext=buildContext(stale,{'2':['a']});
assert.equal(staleContext.completed,1); // Retain the valid snapshot, visibly flag update failure.
assert.equal(staleContext.dataIssues.length,1);
const appSource=fs.readFileSync('web/static/app.js','utf8');
const validateSource=appSource.slice(appSource.indexOf('function validateMilestoneDraft()'),appSource.indexOf('function clearMilestoneFieldErrors()'));
const validation=vm.createContext({
  overviewDraft:{rows:[{localId:'a',name:'Overdue node',date:'2026-09-10',type:'planned',status:'已超期'}]},
  overviewSavedState:{phase:{startDate:'2026-09-01',endDate:'2026-09-30',today:'2026-09-13'}},
  MILESTONE_LABEL_BY_TYPE:{planned:'未开始'},
});
assert.equal(JSON.stringify(vm.runInContext(validateSource+';validateMilestoneDraft()',validation)),'{}');
console.log('Node overview contract passed');
