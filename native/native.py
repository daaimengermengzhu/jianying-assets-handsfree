"""JSON adapter for Jianying's installed native addon; no GUI automation."""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

PROJECT = Path(__file__).resolve().parent
DEFAULT_INSTALL = Path(os.environ.get('JY_INSTALL_DIR', r'C:\Program Files\JianyingPro\Apps\11.5.0.14471'))

class NativeError(RuntimeError):
    pass

class NativeSession:
    def __init__(self, install=DEFAULT_INSTALL, timeout=25):
        self.install = Path(install).resolve()
        self.timeout = timeout
        self.messages = queue.Queue()
        self.sequence = 0
        self.process = None
        self.trace = []

    def __enter__(self):
        for name in ('bun.exe', 'videoeditor_addon.node'):
            if not (self.install/name).is_file():
                raise NativeError(f'Missing installed component: {name}')
        env = os.environ.copy()
        env['JY_INSTALL_DIR'] = str(self.install)
        env['PATH'] = str(self.install) + os.pathsep + env.get('PATH', '')
        self.process = subprocess.Popen(
            [str(self.install/'bun.exe'), str(PROJECT/'native-host.cjs')],
            cwd=PROJECT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            ready = self._receive()
            if ready.get('type') != 'ready' or not ready.get('result', {}).get('admissible'):
                raise NativeError(f'Native initialization failed: {ready}')
            self.ready = ready['result']
            return self
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            for line in self.process.stdout:
                if line.startswith('JYNATIVE:'):
                    try:
                        self.messages.put(json.loads(line[9:]))
                    except ValueError:
                        self.messages.put({'type':'fatal', 'error':'Invalid native response'})
        finally:
            self.messages.put({'type':'eof'})

    def _receive(self):
        try:
            result = self.messages.get(timeout=self.timeout)
        except queue.Empty as error:
            raise NativeError('Native operation timed out') from error
        if result.get('type') in ('fatal', 'eof'):
            raise NativeError(f'Native process stopped: {result}')
        return result

    def call(self, domain, operation, params=None, target=None):
        self.sequence += 1
        request = {'id':str(self.sequence), 'domain':domain, 'operation':operation}
        if params is not None:
            request['params'] = params
        if target is not None:
            request['targetId'] = target
        started = time.monotonic()
        record = {'domain':domain, 'operation':operation, 'accepted':False, 'status':'pending'}
        self.trace.append(record)
        try:
            self.process.stdin.write(json.dumps(request, ensure_ascii=False)+'\n')
            self.process.stdin.flush()
            response = self._receive()
        except (OSError, NativeError) as error:
            record.update(status='failed', elapsed_ms=round((time.monotonic()-started)*1000,2),
                          error=str(error))
            # A timeout desynchronizes the stream. Do not reuse this worker.
            self.close()
            raise
        if response.get('id') != request['id']:
            raise NativeError('Mismatched native response')
        result = response.get('result', {})
        record.update(status='returned', elapsed_ms=round((time.monotonic()-started)*1000,2),
                      accepted=response.get('type')=='response' and result.get('accepted') is not False)
        if response.get('type') != 'response' or result.get('accepted') is False:
            raise NativeError(json.dumps(response, ensure_ascii=False))
        return result

    def read(self, path):
        path = Path(path).resolve()
        return self.call('draft','readFile',{'path':str(path),'rootPath':str(path.parent)})

    def write_new(self, path, content):
        path = Path(path).resolve()
        if path.exists():
            raise FileExistsError(f'Output already exists: {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        return self.call('draft','writeFile',{'path':str(path),'rootPath':str(path.parent),
                         'content':json.dumps(content,ensure_ascii=False),'encrypted':True})

    def close(self):
        if not self.process:
            return
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        for pipe in (self.process.stdout, self.process.stdin):
            if pipe and not pipe.closed:
                pipe.close()

    def __exit__(self, *_):
        self.close()
