"""Bounded stdio transport; owns and terminates the complete worker process tree."""
from __future__ import annotations

import ctypes
import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable


class ProtocolError(RuntimeError):
    pass


class RpcProcess:
    def __init__(self, command: list[str], cwd: Path, env: dict[str, str], timeout: float):
        self.deadline = time.monotonic() + timeout
        self.messages: queue.Queue = queue.Queue(maxsize=4096)
        self.overflow = False
        self.sequence = 0
        self.job = None
        self.cleanup_complete = False
        self.process = None
        flags = 0x08000000 | 0x00000004 if os.name == 'nt' else 0
        try:
            self.process = subprocess.Popen(
                command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                creationflags=flags, start_new_session=os.name != 'nt',
            )
            if os.name == 'nt':
                self._attach_job()
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._discard_stderr, daemon=True).start()
        except BaseException:
            self.close()
            raise

    def _attach_job(self):
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', w.DWORD), ('min_ws', ctypes.c_size_t),
                        ('max_ws', ctypes.c_size_t), ('active_limit', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('ro', 'wo', 'oo', 'rt', 'wt', 'ot')]

        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', Io), ('process_mem', ctypes.c_size_t),
                        ('job_mem', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.kernel = kernel
        self.job = kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.job or not kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError('Cannot configure worker Job Object')
        if not kernel.AssignProcessToJobObject(self.job, int(self.process._handle)):
            raise OSError('Cannot isolate worker process tree')
        ntdll = ctypes.WinDLL('ntdll')
        ntdll.NtResumeProcess.argtypes = [w.HANDLE]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        if ntdll.NtResumeProcess(int(self.process._handle)) < 0:
            raise OSError('Cannot resume isolated worker')

    def _read_stdout(self):
        for line in self.process.stdout:
            if len(line) > 4_000_000:
                self.overflow = True
                return
            try:
                value = json.loads(line)
            except ValueError:
                continue
            try:
                self.messages.put_nowait(value)
            except queue.Full:
                self.overflow = True
                return

    def _discard_stderr(self):
        # Provider errors can contain credentials: never persist raw stderr.
        while self.process.stderr.read(4096):
            pass

    def send(self, value: dict[str, Any]):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def receive(self, deadline: float | None = None) -> dict[str, Any]:
        until = min(self.deadline, deadline or self.deadline)
        while time.monotonic() < until:
            if self.overflow:
                raise ProtocolError('Protocol output limit exceeded')
            try:
                return self.messages.get(timeout=min(0.2, max(0.001, until - time.monotonic())))
            except queue.Empty:
                if self.process.poll() is not None:
                    raise ProtocolError('Worker process exited')
        raise TimeoutError('Worker deadline exceeded')

    def request(self, method: str, params: dict, handler: Callable, timeout: float = 40):
        self.sequence += 1
        request_id = self.sequence
        self.send({'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while True:
            message = self.receive(deadline)
            if message.get('id') == request_id and 'method' not in message:
                if 'error' in message:
                    raise ProtocolError(str(message['error'].get('message', 'Protocol request failed')))
                return message.get('result', {})
            handler(message)

    def close(self):
        process = self.process
        if process is None:
            return
        if os.name == 'nt' and self.job:
            from ctypes import wintypes as w

            class Accounting(ctypes.Structure):
                _fields_ = [(name, ctypes.c_int64) for name in ('user', 'kernel', 'period_user', 'period_kernel')] + [
                    (name, w.DWORD) for name in ('faults', 'total', 'active', 'terminated')]

            self.kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
            accounting = Accounting()
            confirmed = False
            try:
                self.kernel.TerminateJobObject(self.job, 1)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if not self.kernel.QueryInformationJobObject(self.job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
                        break
                    if accounting.active == 0:
                        confirmed = True
                        break
                    time.sleep(0.02)
            finally:
                self.kernel.CloseHandle(self.job)
                self.job = None
            if not confirmed:
                process.kill()
                process.wait(timeout=10)
                raise ProtocolError('Worker process tree termination not confirmed')
        elif os.name != 'nt':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        self.cleanup_complete = True
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe:
                pipe.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
