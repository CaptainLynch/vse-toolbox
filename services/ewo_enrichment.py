"""Explicit, read-only EWO export orchestration with durable generation ownership."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from core.ewo_export_jobs import ExportJobConflict, _reference
from services.ewo_export_transport import EWOExportTransport
from services.ewo_readonly import associate_export_rows, summarize_states
from services.ewo_workbook import read_ewo_workbook


class EWOEnrichment:
    def __init__(self, jobs, directory, *, transport_factory=EWOExportTransport, reader=read_ewo_workbook):
        self.jobs = jobs
        self.directory = Path(directory)
        self.transport_factory = transport_factory
        self.reader = reader

    @staticmethod
    def _signature(filters, source_item_id=None):
        values = asdict(filters)
        if source_item_id is not None:
            values['_source_item_id'] = _reference(source_item_id)
        return hashlib.sha256(json.dumps(
            values, sort_keys=True, ensure_ascii=True, allow_nan=False
        ).encode('utf-8')).hexdigest()

    def restore(self, scope, filters, *, source_item_id=None):
        job_id = self.jobs.latest(scope, self._signature(filters, source_item_id))
        self.jobs.recover()
        return self.status(job_id, scope)

    def prepare(self, scope, crawler, filters, *, source_item_id=None):
        selected = _reference(source_item_id) if source_item_id is not None else None
        result = crawler.crawl_ewo_report_all(filters, page_size=1000, max_pages=6, max_records=5000)
        if not result.complete or result.truncated:
            raise ValueError('EWO selection is incomplete; narrow the filters')
        if not result.rows or len(result.rows) != len(result.item_ids):
            raise ValueError('EWO selection has no complete item identity')
        ids = [_reference(value) for value in result.item_ids]
        if len(set(ids)) != len(ids):
            raise ValueError('EWO selection contains duplicate identities')
        base = []
        for source_id, row in zip(ids, result.rows):
            if row.get('id') and _reference(row['id']) != source_id:
                raise ValueError('EWO selection identity mismatch')
            base.append({'id': source_id, '_no': row.get('_no'), 'state': row.get('state')})
        if selected is not None:
            base = [row for row in base if row['id'] == selected]
            if not base:
                raise ValueError('Fixed EWO source item no longer matches; reconfirm the revision')
            ids = [selected]
        signature = self._signature(filters, selected)
        context = {'version': 1, 'base_rows': base, 'base_time': time.time(),
                   'query_signature': signature, 'states': summarize_states(base)}
        job = self.jobs.create(scope, ids, context=context)
        return self.status(job['id'], scope)

    def status(self, job_id, scope):
        job, context, snapshot, error_stage = self.jobs.read(job_id, scope)
        return {
            'id': job['id'], 'state': job['state'], 'baseTime': context.get('base_time'),
            'enhancementTime': job['updated'] if job['state'] == 'parsed' else None,
            'counts': ({k: v for k, v in snapshot.items() if k != 'associations'} if snapshot
                       else {'base_count': len(context.get('base_rows', []))}),
            'baseRecords': [{'sourceItemId': row['id'], 'businessNumber': row.get('_no'),
                             'state': row.get('state')} for row in context.get('base_rows', [])],
            'stateCounts': context.get('states'),
            'associations': snapshot['associations'] if snapshot else None,
            'errorStage': 'generation' if job['state'] == 'generation_unknown' else error_stage,
        }

    def run(self, job_id, scope, crawler):
        # Recovery never changes unknown generation back to queued.
        self.jobs.get(job_id, scope)
        self.jobs.recover()
        job = self.jobs.get(job_id, scope)
        context, _ = self.jobs.data(job_id, scope)
        if not context.get('base_rows'):
            raise ExportJobConflict('Export context unavailable')
        if job['state'] not in ('queued', 'generated'):
            return self.status(job_id, scope)
        transport = self.transport_factory(crawler)
        if job['state'] == 'queued':
            run = self.jobs.claim(job_id, scope)
            try:
                file_id = transport.generate(json.loads(run['item_ids']))
                self.jobs.generated(job_id, scope, run['lease_token'], file_id)
            except Exception:
                self._interrupt(job_id, scope, run['lease_token'])
                return self.status(job_id, scope)
        run = self.jobs.claim(job_id, scope, lease_seconds=1800)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix='ewo-', dir=self.directory) as destination:
                path = transport.download(run['file_id'], Path(destination))
                workbook = self.reader(path)
                snapshot = associate_export_rows(context['base_rows'], workbook['headers'], workbook['rows'])
            self.jobs.complete(job_id, scope, run['lease_token'], snapshot)
        except Exception:
            self._interrupt(job_id, scope, run['lease_token'])
            result = self.status(job_id, scope)
            result['errorStage'] = 'download-or-parse'
            return result
        return self.status(job_id, scope)

    def _interrupt(self, job_id, scope, token):
        try:
            self.jobs.interrupted(job_id, scope, token)
        except ExportJobConflict:
            # A newer owner/recovery decision takes precedence over this stale worker.
            pass
