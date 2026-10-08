"""Protected, atomic local shutdown capability records."""
from __future__ import annotations

import ctypes
import json
import os
import stat
import tempfile
from ctypes import wintypes
from contextlib import contextmanager
from pathlib import Path


class RecordError(RuntimeError):
    """Secure local instance state is unavailable or invalid."""


def _function(library, name, argtypes):
    function = getattr(library, name)
    function.argtypes = argtypes
    function.restype = wintypes.BOOL
    return function


def _windows_sid() -> str:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    token = wintypes.HANDLE()
    open_token = _function(security, "OpenProcessToken",
                           [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)])
    if not open_token(wintypes.HANDLE(-1), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        get_info = _function(security, "GetTokenInformation",
                             [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)])
        get_info(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not get_info(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        value = wintypes.LPWSTR()
        convert = _function(security, "ConvertSidToStringSidW",
                            [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)])
        if not convert(sid, ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return value.value
        finally:
            kernel.LocalFree(ctypes.cast(value, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)


def _windows_protect(path: Path) -> None:
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    inheritance = "OICI" if path.is_dir() else ""
    sddl = f"D:P(A;{inheritance};FA;;;{_windows_sid()})"
    descriptor = ctypes.c_void_p()
    convert = _function(security, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                        [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                         ctypes.c_void_p])
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        apply = _function(security, "SetFileSecurityW",
                          [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p])
        if not apply(str(path), 0x80000004, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def _windows_check(path: Path) -> None:
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_security = _function(security, "GetFileSecurityW",
                            [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)])
    size = wintypes.DWORD()
    get_security(str(path), 5, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    if not get_security(str(path), 5, buffer, size, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    convert = _function(security, "ConvertSecurityDescriptorToStringSecurityDescriptorW",
                        [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                         ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p])
    value = wintypes.LPWSTR()
    if not convert(buffer, 1, 5, ctypes.byref(value), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        sid = _windows_sid()
        inheritance = "OICI" if path.is_dir() else ""
        expected = f"O:{sid}D:P(A;{inheritance};FA;;;{sid})"
        if value.value != expected:
            raise RecordError("runtime record must be owned by and accessible only to this user")
    finally:
        kernel.LocalFree(ctypes.cast(value, ctypes.c_void_p))


def _reject_link(path: Path) -> None:
    for item in [path, *path.parents]:
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise RecordError("runtime record paths must not contain links or junctions")


def protect(path: Path) -> None:
    _reject_link(path)
    if os.name == "nt":
        _windows_protect(path)
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def check_protected(path: Path) -> None:
    _reject_link(path)
    if os.name == "nt":
        _windows_check(path)
    else:
        info = path.stat()
        expected_mode = 0o700 if path.is_dir() else 0o600
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != expected_mode:
            raise RecordError("runtime state must be owned by and accessible only to this user")


def record_path(runtime_dir: Path, port: int) -> Path:
    return Path(runtime_dir) / f"board-{port}.json"



@contextmanager
def _record_lock(runtime_dir: Path, port: int):
    """Serialize publication and conditional cleanup across service instances."""
    path = runtime_dir / f"board-{port}.lock"
    _reject_link(path)
    with path.open("a+b") as stream:
        protect(path)
        check_protected(path)
        if path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        _lock_file(stream, unlock=False)
        try:
            yield
        finally:
            stream.seek(0)
            _lock_file(stream, unlock=True)


def _lock_file(stream, *, unlock: bool) -> None:
    if os.name == "nt":
        import msvcrt
        mode = msvcrt.LK_UNLCK if unlock else msvcrt.LK_LOCK
        msvcrt.locking(stream.fileno(), mode, 1)
    else:
        import fcntl
        mode = fcntl.LOCK_UN if unlock else fcntl.LOCK_EX
        fcntl.flock(stream.fileno(), mode)


def write_record(runtime_dir: Path, record: dict) -> Path:
    """Secure the directory and empty temp file before writing any capability."""
    runtime_dir = Path(runtime_dir)
    _reject_link(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    protect(runtime_dir)
    check_protected(runtime_dir)
    with _record_lock(runtime_dir, record["port"]):
        return _publish_record(runtime_dir, record)


def _publish_record(runtime_dir: Path, record: dict) -> Path:
    target = record_path(runtime_dir, record["port"])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=runtime_dir, delete=False) as stream:
            temporary = Path(stream.name)
            protect(temporary)
            stream.write(json.dumps(record).encode())
            stream.flush()
            os.fsync(stream.fileno())
        check_protected(temporary)
        os.replace(temporary, target)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_record(runtime_dir: Path, port: int) -> dict:
    path = record_path(runtime_dir, port)
    check_protected(path)
    if path.stat().st_size > 4096:
        raise RecordError("runtime record is too large")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise RecordError("malformed runtime record")
    return record


def remove_record(runtime_dir: Path, port: int, instance_id: str) -> None:
    runtime_dir = Path(runtime_dir)
    if not runtime_dir.exists():
        return
    with _record_lock(runtime_dir, port):
        _remove_matching_record(runtime_dir, port, instance_id)


def _remove_matching_record(runtime_dir: Path, port: int, instance_id: str) -> None:
    try:
        record = read_record(runtime_dir, port)
    except FileNotFoundError:
        return
    if record.get("instance_id") == instance_id:
        record_path(runtime_dir, port).unlink()
