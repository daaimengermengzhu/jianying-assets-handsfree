"""Bounded reusable draft-model worker; never attaches to the user's GUI."""
import json
from pathlib import Path
import queue
import subprocess
import threading

from native import DEFAULT_INSTALL, PROJECT, NativeError


class ModelSession:
    def __init__(self,install=DEFAULT_INSTALL,timeout=40):
        self.install=Path(install).resolve();self.timeout=timeout
        self.process=None;self.messages=queue.Queue();self.sequence=0

    def __enter__(self):
        self.process=subprocess.Popen([str(self.install/'bun.exe'),str(PROJECT/'data-sdk-server.cjs'),str(self.install)],
            cwd=PROJECT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._reader,daemon=True).start()
        try:
            if self._receive().get('type')!='ready':raise NativeError('Draft-model initialization failed')
            return self
        except BaseException:self.close();raise

    def _reader(self):
        try:
            for line in self.process.stdout:
                if line.startswith('JYMODEL:'):
                    try:self.messages.put(json.loads(line[8:]))
                    except ValueError:self.messages.put({'type':'fatal'})
        finally:self.messages.put({'type':'eof'})

    def _receive(self):
        try:message=self.messages.get(timeout=self.timeout)
        except queue.Empty as error:raise NativeError('Draft-model operation timed out') from error
        if not isinstance(message,dict) or message.get('type') in ('fatal','eof'):
            raise NativeError('Draft-model worker stopped unexpectedly')
        return message

    def apply(self,snapshot,kind,params):
        self.sequence+=1
        request=json.dumps({'id':self.sequence,'snapshot':snapshot,'kind':kind,'params':params},ensure_ascii=False)
        if len(request.encode('utf-8'))>8*1024*1024:raise ValueError('Draft-model request exceeds 8 MB')
        try:
            self.process.stdin.write(request+'\n');self.process.stdin.flush()
            reply=self._receive()
            if reply.get('id')!=self.sequence or reply.get('ok') is not True or not isinstance(reply.get('model'),dict):
                raise NativeError('Draft-model action failed: '+str(reply.get('error','mismatched response'))[:1000])
            return reply['model']
        except BaseException:self.close();raise

    def close(self):
        if not self.process:return
        if self.process.poll() is None:
            try:self.process.stdin.close();self.process.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):self.process.kill();self.process.wait(timeout=3)
        for pipe in (self.process.stdin,self.process.stdout):
            if pipe and not pipe.closed:pipe.close()

    def __exit__(self,*_):self.close()
