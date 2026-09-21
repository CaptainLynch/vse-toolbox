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

  function stateLabel(state) {
    var labels = {
      queued: '待显式生成',
      generating: '正在生成官方报表',
      generation_unknown: '生成状态未知',
      generated: '已生成，待读取',
      downloading: '正在读取官方报表',
      parsed: '已读取结果',
    };
    return labels[state] || (state ? String(state) : '未开始');
  }

  function errorStageLabel(stage) {
    var normalized = String(stage || '').trim().toLowerCase().replace(/_/g, '-');
    var labels = {
      download: '下载阶段',
      parse: '解析阶段',
      'download-or-parse': '下载或解析阶段',
    };
    return labels[normalized] || '读取阶段';
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
    var panel = document.createElement('section');
    panel.className = 'ewo-enrichment-panel';

    // Header
    var header = document.createElement('div');
    header.className = 'ewo-panel-header';

    var title = document.createElement('h3');
    title.className = 'ewo-panel-title';
    title.textContent = '待签人与要求完成时间（官方报表补充）';
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

    // Business-first result and snapshot times remain visible. Technical metadata
    // is disclosed below, so the panel can be understood without a job ID.
    var resultSection = document.createElement('section');
    resultSection.className = 'ewo-result-section';
    var resultHead = document.createElement('div');
    resultHead.className = 'ewo-result-head';
    var resultTitle = document.createElement('h4');
    resultTitle.textContent = '结果预览';
    var resultState = document.createElement('span');
    resultState.className = 'ewo-result-state';
    resultState.textContent = '未开始';
    resultState.setAttribute('aria-live', 'polite');
    resultHead.appendChild(resultTitle);
    resultHead.appendChild(resultState);
    resultSection.appendChild(resultHead);

    var snapshotGrid = document.createElement('div');
    snapshotGrid.className = 'ewo-snapshot-grid';

    function createSnapshotCard(labelStr, initialText) {
      var card = document.createElement('div');
      card.className = 'ewo-snapshot-card';
      var label = document.createElement('span');
      label.className = 'ewo-snapshot-label';
      label.textContent = labelStr;
      var value = document.createElement('time');
      value.className = 'ewo-snapshot-value';
      value.textContent = initialText;
      card.appendChild(label);
      card.appendChild(value);
      snapshotGrid.appendChild(card);
      return value;
    }

    var baseSnapshotVal = createSnapshotCard('基础选择快照', '无');
    var resultSnapshotVal = createSnapshotCard('结果快照时间', '尚未读取');
    resultSection.appendChild(snapshotGrid);

    var resultHint = document.createElement('p');
    resultHint.className = 'ewo-result-hint';
    resultHint.textContent = '请先准备官方报表，再由你显式点击生成。';
    resultHint.setAttribute('aria-live', 'polite');
    resultSection.appendChild(resultHint);
    panel.appendChild(resultSection);

    // Actions toolbar. Preparation and generation stay separate user actions.
    var toolbar = document.createElement('div');
    toolbar.className = 'ewo-actions-toolbar';

    var btnPrepare = document.createElement('button');
    btnPrepare.className = 'ewo-btn ewo-btn-prepare segment';
    btnPrepare.textContent = '准备官方报表';
    toolbar.appendChild(btnPrepare);

    var btnRun = document.createElement('button');
    btnRun.className = 'ewo-btn ewo-btn-run primary-btn';
    btnRun.textContent = '生成官方报表';
    btnRun.disabled = true;
    btnRun.hidden = true;
    toolbar.appendChild(btnRun);

    var btnResume = document.createElement('button');
    btnResume.className = 'ewo-btn ewo-btn-resume segment';
    btnResume.textContent = '读取已生成报表';
    btnResume.disabled = true;
    btnResume.hidden = true;
    toolbar.appendChild(btnResume);

    panel.appendChild(toolbar);

    // Technical details are folded by default. Unknown and stale notices above
    // remain visible because they affect whether the result can be trusted.
    var technicalDetails = document.createElement('details');
    technicalDetails.className = 'ewo-technical-details';
    var technicalSummary = document.createElement('summary');
    technicalSummary.textContent = '获取详情';
    technicalDetails.appendChild(technicalSummary);
    var technicalBody = document.createElement('div');
    technicalBody.className = 'ewo-technical-body';

    var btnRestore = document.createElement('button');
    btnRestore.className = 'ewo-btn ewo-btn-restore segment';
    btnRestore.textContent = '恢复上次任务';

    var btnRefresh = document.createElement('button');
    btnRefresh.className = 'ewo-btn ewo-btn-refresh segment';
    btnRefresh.textContent = '刷新任务状态';
    btnRefresh.disabled = true;

    var secondaryActions = document.createElement('div');
    secondaryActions.className = 'ewo-secondary-actions';
    var secondaryTitle = document.createElement('h5');
    secondaryTitle.textContent = '任务控制';
    secondaryActions.appendChild(secondaryTitle);
    secondaryActions.appendChild(btnRestore);
    secondaryActions.appendChild(btnRefresh);
    technicalBody.appendChild(secondaryActions);

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

    var jobIdVal = createMetaRow('任务 ID');
    jobIdVal.textContent = '无';

    var stateVal = createMetaRow('任务状态');
    stateVal.textContent = '未开始';

    var baseTimeVal = createMetaRow('基础选择时间');
    baseTimeVal.textContent = '无';

    var enhancementTimeVal = createMetaRow('结果读取时间');
    enhancementTimeVal.textContent = '无';

    var diagnosticVal = createMetaRow('诊断阶段');
    diagnosticVal.textContent = '无';

    technicalBody.appendChild(metaSection);

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

    technicalBody.appendChild(countsContainer);

    var baseDetails = document.createElement('section');
    baseDetails.className = 'ewo-base-records-section';
    var baseTitle = document.createElement('h5');
    baseTitle.textContent = '基础记录 ID（用于固定版本绑定）';
    baseDetails.appendChild(baseTitle);
    var baseRecordsHost = document.createElement('div');
    baseRecordsHost.className = 'ewo-base-records';
    baseDetails.appendChild(baseRecordsHost);
    technicalBody.appendChild(baseDetails);

    technicalDetails.appendChild(technicalBody);
    panel.appendChild(technicalDetails);

    // Table section
    var tableSection = document.createElement('div');
    tableSection.className = 'ewo-table-section';

    var tableLimitLabel = document.createElement('div');
    tableLimitLabel.className = 'ewo-table-limit-label';
    tableLimitLabel.textContent = '暂无结果；请先准备并显式生成官方报表';
    tableSection.appendChild(tableLimitLabel);

    var table = document.createElement('table');
    table.className = 'ewo-table';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    var colHeaders = ['序号', '业务单号', '关联状态', 'EWO状态', '待签人', '要求完成时间', '责任工程师'];
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
        btnPrepare.hidden = true;
        btnRun.hidden = true;
        btnResume.hidden = true;
        btnRefresh.hidden = !isValidJobId(currentJobId);
        return;
      }
      btnPrepare.disabled = false;
      btnRestore.disabled = false;
      var hasValidJob = isValidJobId(currentJobId);
      btnRefresh.disabled = !hasValidJob;
      btnRun.disabled = !(hasValidJob && currentState === 'queued');
      btnResume.disabled = !(hasValidJob && currentState === 'generated');
      btnPrepare.hidden = !(currentState === 'parsed' || !hasValidJob || !currentState);
      btnRun.hidden = !(hasValidJob && currentState === 'queued');
      btnResume.hidden = !(hasValidJob && currentState === 'generated');
      btnRefresh.hidden = !hasValidJob;

      // Keep generation as the primary action after preparation. Once the
      // official file exists, reading that file becomes the primary recovery
      // action; generation_unknown never enters either branch.
      if (currentState === 'generated') {
        btnRun.className = 'ewo-btn ewo-btn-run segment';
        btnResume.className = 'ewo-btn ewo-btn-resume primary-btn';
        btnResume.textContent = '读取已生成报表';
      } else if (currentState === 'queued' || !currentState) {
        btnRun.className = 'ewo-btn ewo-btn-run primary-btn';
        btnResume.className = 'ewo-btn ewo-btn-resume segment';
        btnRun.textContent = '生成官方报表';
      } else {
        btnRun.className = 'ewo-btn ewo-btn-run segment';
        btnResume.className = 'ewo-btn ewo-btn-resume segment';
        btnRun.textContent = currentState === 'generating'
          ? '生成中…'
          : currentState === 'downloading'
            ? '读取中…'
            : currentState === 'parsed'
              ? '已读取结果'
              : currentState === 'generation_unknown'
                ? '生成状态未知'
                : '生成官方报表';
      }
      if (currentState === 'generated') {
        btnRun.textContent = '生成官方报表';
      }
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

      var errorStage = typeof data.errorStage === 'string' ? data.errorStage.trim() : '';
      var hasReadError = Boolean(errorStage) && currentState !== 'generation_unknown';
      resultState.textContent = hasReadError
        ? stateLabel(currentState) + ' · 读取失败'
        : stateLabel(currentState);
      baseSnapshotVal.textContent = formatUnixSeconds(data.baseTime);
      baseSnapshotVal.setAttribute('datetime', formatUnixSeconds(data.baseTime));
      resultSnapshotVal.textContent = data.enhancementTime
        ? formatUnixSeconds(data.enhancementTime)
        : '尚未读取';
      if (data.enhancementTime) {
        resultSnapshotVal.setAttribute('datetime', formatUnixSeconds(data.enhancementTime));
      } else {
        resultSnapshotVal.setAttribute('datetime', '');
      }
      resultHint.className = hasReadError ? 'ewo-result-hint ewo-result-hint-error' : 'ewo-result-hint';
      resultHint.textContent = currentState === 'generation_unknown'
          ? '生成结果未确认，请先在原系统核对后再决定下一步。'
          : hasReadError
              ? currentState === 'generated'
                ? '官方报表在' + errorStageLabel(errorStage) + '未能完成读取。请显式点击“读取已生成报表”重试读取；不会重新生成文件。'
                : '官方报表在' + errorStageLabel(errorStage) + '未能完成读取，请展开“获取详情”查看当前任务状态。'
              : currentState === 'parsed'
                ? '官方报表已读取，以下待签人和要求完成时间仅作补充展示。'
                : currentState === 'generated'
                  ? '官方报表已生成；请显式点击“读取已生成报表”获取结果。'
                  : currentState === 'queued'
                    ? '范围已准备完成；请显式点击“生成官方报表”开始官方导出。'
                    : '正在处理官方报表，请根据当前状态继续操作。';
      diagnosticVal.textContent = data.errorStage ? String(data.errorStage) : '无';

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
      tableLimitLabel.textContent = Array.isArray(data.associations)
        ? '显示记录：前 ' + slice.length + ' 条（共 ' + total + ' 条）'
        : '暂无结果；请先准备并显式生成官方报表';

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
        tdStatus.className = 'col-association-status';
        tdStatus.textContent = String(item.status != null ? item.status : '');
        tr.appendChild(tdStatus);

        var fields = item.fields || {};
        var tdEwoStatus = document.createElement('td');
        tdEwoStatus.className = 'col-ewo-status';
        tdEwoStatus.textContent = String(fields['状态'] != null ? fields['状态'] : '');
        tr.appendChild(tdEwoStatus);

        var tdPendingSigner = document.createElement('td');
        tdPendingSigner.className = 'col-pending-signer';
        tdPendingSigner.textContent = String(fields['当前阶段未签署的角色&人员'] != null ? fields['当前阶段未签署的角色&人员'] : '');
        tr.appendChild(tdPendingSigner);

        var tdDueDate = document.createElement('td');
        tdDueDate.className = 'col-due-date';
        tdDueDate.textContent = String(fields['要求完成时间'] != null ? fields['要求完成时间'] : '');
        tr.appendChild(tdDueDate);

        var tdEngineer = document.createElement('td');
        tdEngineer.className = 'col-engineer';
        tdEngineer.textContent = String(fields['责任工程师名称'] != null ? fields['责任工程师名称'] : '');
        tr.appendChild(tdEngineer);

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
