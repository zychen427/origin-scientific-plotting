"""Experimental process-local OriginExt adapter; no module proxy substitution."""
from __future__ import annotations

import os
import time


class _Pages:
    def __init__(self, collection):
        self._collection = collection

    @property
    def Count(self):
        return self._collection.Count

    def Item(self, index):
        return self._collection[index]


class _Worksheet:
    def __init__(self, worksheet):
        self._worksheet = worksheet

    @property
    def Columns(self):
        return _Pages(self._worksheet.Columns)

    def __getattr__(self, name):
        return getattr(self._worksheet, name)


class _GraphLayer:
    def __init__(self, layer):
        self._layer = layer

    @property
    def DataPlots(self):
        return _Pages(self._layer.DataPlots)

    def __getattr__(self, name):
        return getattr(self._layer, name)


class NativeOrigin:
    """Compatibility for application-level COM calls on originpro's own app.

    Object-level COM interfaces are intentionally not patched: unverified
    tools must fail rather than use an object from a different Origin.
    """
    def __init__(self, api):
        self.api = api
        from originpro.config import po
        self._po = po

    @property
    def Visible(self):
        return self._po.Visible

    @property
    def IsModified(self):
        return self._po.IsModified

    @property
    def WorksheetPages(self):
        return _Pages(self._po.WorksheetPages)

    @property
    def GraphPages(self):
        return _Pages(self._po.GraphPages)

    @property
    def MatrixPages(self):
        return _Pages(self._po.MatrixPages)

    def LTStr(self, name):
        return self._po.LT_get_str(name)

    def LTVar(self, name):
        return self._po.LT_get_var(name)

    def Execute(self, script):
        return self._po.LT_execute(script)

    def FindWorksheet(self, name):
        item = self._po.FindWorksheet(name)
        return _Worksheet(item) if item and item.IsValid() else None

    def FindGraphLayer(self, name):
        item = self._po.FindGraphLayer(name)
        return _GraphLayer(item) if item and item.IsValid() else None

    def __getattr__(self, name):
        return getattr(self._po, name)


def create_owned_origin():
    """Use originpro's own Application, then verify its peer and process identity."""
    from .daemon import _origin_process_pids, _real_pid_tls, record_spawned_pid
    from .existing_origin import _process_identity, query_peer_pid
    before = _origin_process_pids()
    import originpro as op
    op.set_show(True)
    app = NativeOrigin(op)
    pid = query_peer_pid(app)
    deadline = time.monotonic() + 10
    while pid not in _origin_process_pids() and time.monotonic() < deadline:
        time.sleep(.2)
    if pid in before or pid not in _origin_process_pids():
        raise RuntimeError(f'originpro did not create a verified new Origin process: {pid}')
    identity = _process_identity(pid)
    if os.path.basename(identity['image']).lower() not in ('origin.exe', 'origin64.exe'):
        raise RuntimeError('originpro peer image is not an Origin executable')
    _real_pid_tls.pid = pid
    record_spawned_pid(pid)
    return app
