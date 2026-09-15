(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof define === 'function' && define.amd) {
    define([], function () {
      return api;
    });
  }
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (typeof root !== 'undefined') {
    root.EWOEnrichment = api;
  }
}(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : this), function () {
  'use strict';

  var HEX32_REGEX = /^[0-9a-fA-F]{32}$/;

  function isValidJobId(id) {
    return typeof id === 'string' && HEX32_REGEX.test(id);
  }

  function formatUnixSeconds(sec) {
    if (typeof sec !== 'number' || isNaN(sec) || sec <= 0) {
      return '无';
    }
    try {
      return new Date(sec * 1000).toISOString();
    } catch (e) {
      return String(sec);
    }
  }

  function mount(options) {
    if (!options || !options.host) {
      throw new Error('mount requires a host element in options');
    }

    var host = options.host;
    var request = options.request;
    var getFilters = options.getFilters;

    if (typeof request !== 'function') {
      throw new Error('mount requires a request function in options');
    }

    var destroyed = false;
    var busy = false;
    var currentJobId = null;
    var currentState = null;
    var lastData = null;
    var staleWarningText = '';

    // Create container
    var panel = document.createElement('div');
    panel.className = 'ewo-enrichment-panel';

    // Header
    var header = document.createElement('div');
    header.className = 'ewo-panel-header';

    var title = document.createElement('h3');
    title.className = 'ewo-panel-title';
    title.textContent = 'EWO增强导表状态（只读）';
    header.appendChild(title);

    var readonlyExplanation = document.createElement('p');
    readonlyExplanation.className = 'ewo-readonly-explanation';
    readonlyExplanation.textContent = '只读增强展示：不会自动更新本项目的负责人、计划完成日期，也不会向原系统反写。';
    header.appendChild(readonlyExplanation);

    panel.appendChild(header);

    // Notice banners
    var staleNotice = document.createElement('div');
    staleNotice.className = 'ewo-stale-notice';
    staleNotice.style.display = 'none';
    panel.appendChild(staleNotice);

    var unknownNotice = document.createElement('div');
    unknownNotice.className = 'ewo-unknown-notice';
    unknownNotice.style.display = 'none';
    panel.appendChild(unknownNotice);

    var errorStageNotice = document.createElement('div');
    errorStageNotice.className = 'ewo-error-stage-notice';
    errorStageNotice.style.display = 'none';
    panel.appendChild(errorStageNotice);

    // Meta section
    var metaSection = document.createElement('div');
    metaSection.className = 'ewo-meta-section';

    function createMetaRow(labelStr) {
      var row = document.createElement('div');
      row.className = 'ewo-meta-row';
      var label = document.createElement('span');
      label.className = 'ewo-meta-label';
      label.textContent = labelStr;
      var value = document.createElement('span');
      value.className = 'ewo-meta-value';
      row.appendChild(label);
      row.appendChild(value);
      metaSection.appendChild(row);
      return value;
    }

    var jobIdVal = createMetaRow('任务ID: ');
    jobIdVal.textContent = '无';

    var stateVal = createMetaRow('任务状态: ');
    stateVal.textContent = '未开始';

    var baseTimeVal = createMetaRow('基准时间: ');
    baseTimeVal.textContent = '无';

    var enhancementTimeVal = createMetaRow('增强时间: ');
    enhancementTimeVal.textContent = '无';

    panel.appendChild(metaSection);
    var baseDetails = document.createElement('details');
    var baseSummary = document.createElement('summary');
    baseSummary.textContent = '基础记录 ID（用于固定版本绑定）';
    var baseRecordsHost = document.createElement('div');
    baseRecordsHost.className = 'ewo-base-records';
    baseDetails.appendChild(baseSummary);
    baseDetails.appendChild(baseRecordsHost);
    panel.appendChild(baseDetails);

    // Actions toolbar
    var toolbar = document.createElement('div');
    toolbar.className = 'ewo-actions-toolbar';

    var btnPrepare = document.createElement('button');
    btnPrepare.className = 'ewo-btn ewo-btn-prepare';
    btnPrepare.textContent = '准备增强导表';
    toolbar.appendChild(btnPrepare);
    var btnRestore = document.createElement('button');
    btnRestore.className = 'ewo-btn ewo-btn-restore';
    btnRestore.textContent = '恢复上次任务';
    toolbar.appendChild(btnRestore);

    var btnRun = document.createElement('button');
    btnRun.className = 'ewo-btn ewo-btn-run';
    btnRun.textContent = '生成并读取增强';
    btnRun.disabled = true;
    toolbar.appendChild(btnRun);

    var btnResume = document.createElement('button');
    btnResume.className = 'ewo-btn ewo-btn-resume';
    btnResume.textContent = '继续读取已生成报表';
    btnResume.disabled = true;
    toolbar.appendChild(btnResume);

    var btnRefresh = document.createElement('button');
    btnRefresh.className = 'ewo-btn ewo-btn-refresh';
    btnRefresh.textContent = '刷新状态';
    btnRefresh.disabled = true;
    toolbar.appendChild(btnRefresh);

    panel.appendChild(toolbar);

    // Counts summary
    var countsContainer = document.createElement('div');
    countsContainer.className = 'ewo-counts-grid';

    function createCountBadge(labelStr) {
      var item = document.createElement('div');
      item.className = 'ewo-count-item';
      var label = document.createElement('span');
      label.className = 'ewo-count-label';
      label.textContent = labelStr;
      var value = document.createElement('span');
      value.className = 'ewo-count-value';
      value.textContent = '-';
      item.appendChild(label);
      item.appendChild(value);
      countsContainer.appendChild(item);
      return value;
    }

    var countBaseVal = createCountBadge('基准行数: ');
    var countExportVal = createCountBadge('导出总行数: ');
    var countMatchedVal = createCountBadge('匹配行数: ');
    var countBlankVal = createCountBadge('空白单号行数: ');
    var countUnmatchedVal = createCountBadge('未匹配行数: ');
    var countAmbiguousVal = createCountBadge('歧义行数: ');

    panel.appendChild(countsContainer);

    // Table section
    var tableSection = document.createElement('div');
    tableSection.className = 'ewo-table-section';

    var tableLimitLabel = document.createElement('div');
    tableLimitLabel.className = 'ewo-table-limit-label';
    tableLimitLabel.textContent = '显示记录：前 0 条（共 0 条）';
    tableSection.appendChild(tableLimitLabel);

    var table = document.createElement('table');
    table.className = 'ewo-table';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    var colHeaders = ['序号', '业务单号', '状态', '责任工程师名称', '要求完成时间'];
    for (var h = 0; h < colHeaders.length; h++) {
      var th = document.createElement('th');
      th.textContent = colHeaders[h];
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    tbody.className = 'ewo-tbody';
    table.appendChild(tbody);

    tableSection.appendChild(table);
    panel.appendChild(tableSection);

    // Attach panel to host
    host.appendChild(panel);

    function updateButtonStates() {
      if (destroyed) return;
      if (busy) {
        btnPrepare.disabled = true;
        btnRestore.disabled = true;
        btnRun.disabled = true;
        btnResume.disabled = true;
        btnRefresh.disabled = true;
        return;
      }
      btnPrepare.disabled = false;
      btnRestore.disabled = false;
      var hasValidJob = isValidJobId(currentJobId);
      btnRefresh.disabled = !hasValidJob;
      btnRun.disabled = !(hasValidJob && currentState === 'queued');
      btnResume.disabled = !(hasValidJob && currentState === 'generated');
    }

    function renderStaleNotice() {
      if (destroyed) return;
      if (staleWarningText) {
        staleNotice.textContent = staleWarningText;
        staleNotice.style.display = 'block';
      } else {
        staleNotice.textContent = '';
        staleNotice.style.display = 'none';
      }
    }

    function renderData(data) {
      if (destroyed || !data || typeof data !== 'object') return;
      if (!isValidJobId(data.id)) throw new Error('收到无效的增强任务编号');

      if (data.id !== undefined && data.id !== null) {
        if (isValidJobId(data.id)) {
          currentJobId = data.id;
        } else {
          staleWarningText = '收到无效的 Job ID (' + String(data.id) + ')，已忽略该 ID';
        }
      }

      if (typeof data.state === 'string') {
        currentState = data.state;
      }

      lastData = data;

      jobIdVal.textContent = currentJobId ? currentJobId : '无';
      stateVal.textContent = currentState ? currentState : '未开始';
      baseTimeVal.textContent = formatUnixSeconds(data.baseTime);
      enhancementTimeVal.textContent = formatUnixSeconds(data.enhancementTime);
      baseRecordsHost.textContent = '';
      var baseRecords = Array.isArray(data.baseRecords) ? data.baseRecords : [];
      var baseInfo = document.createElement('p');
      baseInfo.textContent = '共 ' + baseRecords.length + ' 条，显示前100条；可缩小匹配条件查找，再复制内部 ID。';
      baseRecordsHost.appendChild(baseInfo);
      baseRecords.slice(0, 100).forEach(function (record) {
        var line = document.createElement('p');
        line.textContent = String(record.businessNumber || '未编号') + ' | '
          + String(record.state || '未知状态') + ' | ' + String(record.sourceItemId || '');
        baseRecordsHost.appendChild(line);
      });

      if (data.errorStage) {
        errorStageNotice.textContent = '错误阶段: ' + String(data.errorStage);
        errorStageNotice.style.display = 'block';
      } else {
        errorStageNotice.textContent = '';
        errorStageNotice.style.display = 'none';
      }

      if (currentState === 'generation_unknown') {
        unknownNotice.textContent = '生成状态未知，结果不确定，请前往原系统核对！不可直接重试生成。';
        unknownNotice.style.display = 'block';
      } else {
        unknownNotice.textContent = '';
        unknownNotice.style.display = 'none';
      }

      var counts = data.counts || {};
      countBaseVal.textContent = String(counts.base_count != null ? counts.base_count : '-');
      countExportVal.textContent = String(counts.export_count != null ? counts.export_count : '-');
      countMatchedVal.textContent = String(counts.matched_count != null ? counts.matched_count : '-');
      countBlankVal.textContent = String(counts.blank_number_count != null ? counts.blank_number_count : '-');
      countUnmatchedVal.textContent = String(counts.unmatched_count != null ? counts.unmatched_count : '-');
      countAmbiguousVal.textContent = String(counts.ambiguous_count != null ? counts.ambiguous_count : '-');

      var assocs = Array.isArray(data.associations) ? data.associations : [];
      var total = assocs.length;
      var limit = 100;
      var slice = assocs.slice(0, limit);
      tableLimitLabel.textContent = '显示记录：前 ' + slice.length + ' 条（共 ' + total + ' 条）';

      while (tbody.firstChild) {
        tbody.removeChild(tbody.firstChild);
      }

      for (var i = 0; i < slice.length; i++) {
        var item = slice[i] || {};
        var tr = document.createElement('tr');
        tr.className = 'ewo-row';

        var tdIdx = document.createElement('td');
        tdIdx.textContent = String(item.row_index != null ? item.row_index : (i + 1));
        tr.appendChild(tdIdx);

        var tdNum = document.createElement('td');
        tdNum.className = 'col-business-number';
        tdNum.textContent = String(item.business_number != null ? item.business_number : '');
        tr.appendChild(tdNum);

        var tdStatus = document.createElement('td');
        tdStatus.className = 'col-status';
        tdStatus.textContent = String(item.status != null ? item.status : '');
        tr.appendChild(tdStatus);

        var fields = item.fields || {};
        var tdEngineer = document.createElement('td');
        tdEngineer.className = 'col-engineer';
        tdEngineer.textContent = String(fields['责任工程师名称'] != null ? fields['责任工程师名称'] : '');
        tr.appendChild(tdEngineer);

        var tdDueDate = document.createElement('td');
        tdDueDate.className = 'col-due-date';
        tdDueDate.textContent = String(fields['要求完成时间'] != null ? fields['要求完成时间'] : '');
        tr.appendChild(tdDueDate);

        tbody.appendChild(tr);
      }

      renderStaleNotice();
      updateButtonStates();
    }

    async function handlePrepare(restore) {
      if (destroyed || busy) return;
      busy = true;
      updateButtonStates();
      try {
        var filters = typeof getFilters === 'function' ? getFilters() : {};
        var path = '/api/aras/ewo/enrichment/jobs' + (restore === true ? '/restore' : '');
        var res = await request(path, { filters: filters });
        if (destroyed) return;
        staleWarningText = '';
        renderData(res);
      } catch (err) {
        if (destroyed) return;
        staleWarningText = '准备或恢复任务失败（已保留上次数据）：' + (err && err.message ? err.message : String(err));
        renderStaleNotice();
      } finally {
        if (!destroyed) {
          busy = false;
          updateButtonStates();
        }
      }
    }

    async function handleRun() {
      if (destroyed || busy) return;
      if (!isValidJobId(currentJobId) || currentState !== 'queued') return;
      busy = true;
      updateButtonStates();
      try {
        var res = await request('/api/aras/ewo/enrichment/jobs/' + encodeURIComponent(currentJobId) + '/run', {});
        if (destroyed) return;
        staleWarningText = '';
        renderData(res);
      } catch (err) {
        if (destroyed) return;
        staleWarningText = '生成并读取增强请求失败（已保留上次数据）：' + (err && err.message ? err.message : String(err));
        renderStaleNotice();
      } finally {
        if (!destroyed) {
          busy = false;
          updateButtonStates();
        }
      }
    }

    async function handleResume() {
      if (destroyed || busy) return;
      if (!isValidJobId(currentJobId) || currentState !== 'generated') return;
      busy = true;
      updateButtonStates();
      try {
        var res = await request('/api/aras/ewo/enrichment/jobs/' + encodeURIComponent(currentJobId) + '/run', {});
        if (destroyed) return;
        staleWarningText = '';
        renderData(res);
      } catch (err) {
        if (destroyed) return;
        staleWarningText = '继续读取已生成报表请求失败（已保留上次数据）：' + (err && err.message ? err.message : String(err));
        renderStaleNotice();
      } finally {
        if (!destroyed) {
          busy = false;
          updateButtonStates();
        }
      }
    }

    async function handleRefresh() {
      if (destroyed || busy) return;
      if (!isValidJobId(currentJobId)) return;
      busy = true;
      updateButtonStates();
      try {
        var res = await request('/api/aras/ewo/enrichment/jobs/' + encodeURIComponent(currentJobId) + '/status', {});
        if (destroyed) return;
        staleWarningText = '';
        renderData(res);
      } catch (err) {
        if (destroyed) return;
        staleWarningText = '刷新状态请求失败（已保留上次数据）：' + (err && err.message ? err.message : String(err));
        renderStaleNotice();
      } finally {
        if (!destroyed) {
          busy = false;
          updateButtonStates();
        }
      }
    }

    btnPrepare.addEventListener('click', handlePrepare);
    function handleRestore() { return handlePrepare(true); }
    btnRestore.addEventListener('click', handleRestore);
    btnRun.addEventListener('click', handleRun);
    btnResume.addEventListener('click', handleResume);
    btnRefresh.addEventListener('click', handleRefresh);

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      btnPrepare.removeEventListener('click', handlePrepare);
      btnRestore.removeEventListener('click', handleRestore);
      btnRun.removeEventListener('click', handleRun);
      btnResume.removeEventListener('click', handleResume);
      btnRefresh.removeEventListener('click', handleRefresh);

      if (panel && panel.parentNode) {
        panel.parentNode.removeChild(panel);
      }
    }

    updateButtonStates();

    return {
      destroy: destroy
    };
  }

  return {
    mount: mount
  };
}));
