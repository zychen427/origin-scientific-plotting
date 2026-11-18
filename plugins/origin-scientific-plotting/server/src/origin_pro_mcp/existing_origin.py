"""Enumerate and verify existing Origin windows without desktop input."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import ntpath
import uuid


def _process_identity(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME)]
    handle=kernel.OpenProcess(0x1000,False,int(pid))
    if not handle: raise OSError(ctypes.get_last_error(), 'Cannot inspect process')
    try:
        buf=ctypes.create_unicode_buffer(32768); n=wintypes.DWORD(len(buf))
        if not kernel.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(n)): raise OSError(ctypes.get_last_error(),'Cannot read process image')
        created=wintypes.FILETIME();ended=wintypes.FILETIME();kernel_t=wintypes.FILETIME();user_t=wintypes.FILETIME()
        if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(ended),ctypes.byref(kernel_t),ctypes.byref(user_t)): raise OSError(ctypes.get_last_error(),'Cannot read process start time')
        return {'pid':int(pid),'image':buf.value,'creation_filetime':(created.dwHighDateTime<<32)|created.dwLowDateTime}
    finally:kernel.CloseHandle(handle)


def list_windows():
    import win32gui,win32process
    found=[]
    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd): return
        title=win32gui.GetWindowText(hwnd)
        if not title or 'origin' not in title.casefold(): return
        pid=win32process.GetWindowThreadProcessId(hwnd)[1]
        try: info=_process_identity(pid)
        except OSError: return
        if ntpath.basename(info['image']).casefold() not in ('origin.exe','origin64.exe'):return
        found.append({**info,'hwnd':int(hwnd),'title':title})
    win32gui.EnumWindows(visit,None)
    return found


def require_window(pid):
    if isinstance(pid,bool) or not isinstance(pid,int) or pid <= 0: raise ValueError('pid must be a positive integer.')
    matches=[v for v in list_windows() if v['pid']==pid]
    if len(matches)!=1: raise RuntimeError('Requested PID must identify exactly one visible Origin main window; no connection was made.')
    return matches[0]


def query_peer_pid(app):
    """Read the COM server's own PID without changing project contents."""
    var='__opm_pid_'+uuid.uuid4().hex[:12]
    statement=f"run.python(\"import os,PyOrigin; PyOrigin.LT_set_var('{var}',os.getpid())\",0);"
    if not app.Execute(statement):
        raise RuntimeError('Unable to query COM peer identity; refusing connection.')
    try:
        actual=int(app.LTVar(var))
    except Exception as exc:
        raise RuntimeError('Unable to read COM peer PID; refusing connection.') from exc
    if actual <= 0:
        raise RuntimeError('Origin returned an invalid COM peer PID; refusing connection.')
    return actual


def connect_verified(pid, creation_filetime):
    """ApplicationSI with OS identity checks: exact PID or no usable proxy.

    Origin may select a different existing instance or create one in a race.
    This function never touches project data and refuses a non-matching proxy.
    """
    expected=require_window(pid)
    if expected['creation_filetime']!=creation_filetime: raise RuntimeError('Origin PID was reused or restarted; enumerate windows again.')
    import win32com.client
    before={x['pid'] for x in list_windows()}
    app=win32com.client.Dispatch('Origin.ApplicationSI')
    # This writes only a uniquely named transient LabTalk variable, not project
    # contents. Python runs inside Origin, so os.getpid() identifies the COM peer.
    actual=query_peer_pid(app)
    if actual!=pid:
        after={x['pid'] for x in list_windows()}
        created=after-before
        raise RuntimeError(f'Origin ApplicationSI selected PID {actual}, not target {pid}; no target project was edited. New visible PIDs: {sorted(created)}. This API cannot select an arbitrary instance.')
    checked=require_window(pid)
    if checked['creation_filetime']!=creation_filetime: raise RuntimeError('Target process changed during connection; refusing connection.')
    return app
