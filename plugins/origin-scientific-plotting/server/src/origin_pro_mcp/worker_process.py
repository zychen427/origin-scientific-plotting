"""One Origin session per subprocess. COM objects never cross the pipe."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading


def _worker_main():
    from .daemon import Session, _default_registry, _real_origin_factory, _real_origin_get_pid
    from .existing_origin import _process_identity

    protocol = sys.stdout
    # Tools and dependency diagnostics must never corrupt the JSON protocol.
    sys.stdout = sys.stderr
    lock = threading.Lock()

    def send(message):
        with lock:
            protocol.write(json.dumps(message, ensure_ascii=True) + '\n')
            protocol.flush()

    session_id = sys.argv[1]
    factory = _real_origin_factory
    backend = os.environ.get('ORIGIN_PRO_MCP_BACKEND', 'originpro')
    if backend == 'originpro':
        from .originpro_native import create_owned_origin
        factory = create_owned_origin
    elif backend != 'com':
        raise ValueError(f'Unsupported Origin backend: {backend!r}')
    session = Session(session_id, factory, _default_registry(),
                      _real_origin_get_pid)
    session.close_owned_on_release = True
    try:
        session.start(ready_timeout=120)
        if not session.pid:
            raise RuntimeError('Origin PID was not verified.')
        send({'kind': 'ready', 'pid': session.pid,
              'identity': _process_identity(session.pid), 'worker_pid': os.getpid()})
        for line in sys.stdin:
            request = json.loads(line)
            kind = request.get('kind')
            if kind == 'request':
                session.submit(request['request_id'], request['name'],
                               request.get('kwargs') or {},
                               lambda response: send({'kind': 'response', 'response': response}))
            elif kind == 'stop':
                session.stop()
                return
    except BaseException as exc:
        send({'kind': 'failure', 'error_type': type(exc).__name__, 'error': str(exc)})
    finally:
        # A disconnected parent does not authorize closing a possibly dirty project.
        session.force_close()


class ProcessSession:
    """Daemon-side handle; the child contains the only Origin COM apartment."""

    def __init__(self, session_id):
        self.session_id = session_id
        self.pid = None
        self.worker_pid = None
        self.identity = None
        self.reaping = False
        self.verified_target = None
        self._process = None
        self._lock = threading.Lock()
        self._callbacks = {}
        self._ready = threading.Event()
        self._error = None
        self._dead = False

    def start(self, ready_timeout=45):
        env = os.environ.copy()
        env['ORIGIN_PRO_MCP_WORKER'] = '1'
        source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['PYTHONPATH'] = source + os.pathsep + env.get('PYTHONPATH', '')
        self._process = subprocess.Popen(
            [sys.executable, '-u', '-m', 'origin_pro_mcp.worker_process', self.session_id],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', bufsize=1, env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._read, name='origin-worker-reader', daemon=True).start()
        if not self._ready.wait(ready_timeout):
            raise TimeoutError('Origin worker startup timed out; outcome unknown. Inspect Origin processes before starting another session.')
        if self._error:
            raise RuntimeError(self._error)

    def _read(self):
        try:
            for line in self._process.stdout:
                msg = json.loads(line)
                if msg.get('kind') == 'ready':
                    self.pid, self.worker_pid, self.identity = msg['pid'], msg['worker_pid'], msg['identity']
                    self._ready.set()
                elif msg.get('kind') == 'failure':
                    self._error = f"{msg.get('error_type')}: {msg.get('error')}"
                    self._ready.set()
                elif msg.get('kind') == 'response':
                    response = msg['response']
                    with self._lock:
                        callback = self._callbacks.pop(response.get('request_id'), None)
                    if callback:
                        callback(response)
                    if response.get('ok') and response.get('request_id') == getattr(self, '_release_id', None):
                        self.stop()
                    elif (response.get('request_id') == getattr(self, '_release_id', None)
                          and str(response.get('error') or '').startswith('COM was released')):
                        self._dead = True
                        self.stop()
        except Exception as exc:
            self._error = f'Worker protocol failed: {type(exc).__name__}: {exc}'
        finally:
            self._dead = True
            if not self._ready.is_set() and not self._error:
                self._error = 'Worker exited before verifying Origin identity.'
            self._ready.set()
            with self._lock:
                pending, self._callbacks = self._callbacks, {}
            for request_id, callback in pending.items():
                callback({'type': 'response', 'request_id': request_id, 'ok': False,
                          'result': None, 'error': 'Worker exited; operation outcome may be partial or unknown. Inspect the owned Origin project; do not replay automatically.'})

    def submit(self, request_id, name, kwargs, reply_fn):
        with self._lock:
            if self._dead or not self._process or self._process.poll() is not None:
                raise RuntimeError('Origin worker exited; session cannot be rebound. Inspect the original Origin instance.')
            self._callbacks[request_id] = reply_fn
            if name == '__release_origin_session':
                self._release_id = request_id
            try:
                self._process.stdin.write(json.dumps({'kind': 'request', 'request_id': request_id,
                                                      'name': name, 'kwargs': kwargs}) + '\n')
                self._process.stdin.flush()
            except Exception:
                self._callbacks.pop(request_id, None)
                raise

    def poll_dialogs_now(self):
        return None

    def submit_snapshot(self):
        pass  # No unsolicited autosave across the process boundary.

    def submit_reap(self, recovery_dir, getter, on_done=None):
        # Retain the session after transport disconnect; it may contain unsaved work.
        self.reaping = False
        if on_done:
            on_done()

    def force_close(self):
        # Never kill a worker whose launch or write outcome is uncertain.
        pass

    def stop(self, join_timeout=5):
        # Daemon shutdown drops the pipe, not the Origin window.
        if self._process and self._process.stdin:
            try:
                self._process.stdin.close()
            except OSError:
                pass


if __name__ == '__main__':
    _worker_main()
