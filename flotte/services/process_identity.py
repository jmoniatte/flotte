"""Cross-platform identity checks for processes Flotte manages."""

import ctypes
import os
import platform
from pathlib import Path


class _MacProcessBSDInfo(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("exit_status", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("parent_pid", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("real_uid", ctypes.c_uint32),
        ("real_gid", ctypes.c_uint32),
        ("saved_uid", ctypes.c_uint32),
        ("saved_gid", ctypes.c_uint32),
        ("reserved", ctypes.c_uint64),
        ("command", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("open_files", ctypes.c_uint32),
        ("process_group", ctypes.c_uint32),
        ("job_control_count", ctypes.c_uint32),
        ("controlling_terminal", ctypes.c_uint32),
        ("terminal_process_group", ctypes.c_uint32),
        ("nice", ctypes.c_int32),
        ("started_seconds", ctypes.c_uint64),
        ("started_microseconds", ctypes.c_uint64),
    ]


def capture_process_identity(pid: int) -> dict[str, int | str] | None:
    """Return an identity that distinguishes a live process from a reused PID."""
    try:
        started_at = _process_start_time(pid)
        if started_at is None:
            return None
        return {
            "pid": pid,
            "process_group": os.getpgid(pid),
            "session": os.getsid(pid),
            "started_at": started_at,
        }
    except OSError:
        return None


def matches_process_identity(identity: object) -> bool:
    """Return whether a stored process identity still identifies the same process."""
    if not isinstance(identity, dict):
        return False
    try:
        pid = int(identity["pid"])
        return (
            identity["started_at"] == _process_start_time(pid)
            and int(identity["process_group"]) == os.getpgid(pid)
            and int(identity["session"]) == os.getsid(pid)
        )
    except (KeyError, OSError, TypeError, ValueError):
        return False


def _process_start_time(pid: int) -> int | str | None:
    system = platform.system()
    if system == "Linux":
        return _linux_process_start_time(pid)
    if system == "Darwin":
        return _macos_process_start_time(pid)
    return None


def _linux_process_start_time(pid: int) -> int | None:
    stat = Path(f"/proc/{pid}/stat").read_text()
    fields = stat[stat.rfind(")") + 2 :].split()
    if len(fields) <= 19:
        return None
    return int(fields[19])


def _macos_process_start_time(pid: int) -> str | None:
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    proc_pidinfo = libproc.proc_pidinfo
    proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    proc_pidinfo.restype = ctypes.c_int

    info = _MacProcessBSDInfo()
    bytes_written = proc_pidinfo(
        pid,
        3,
        0,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if bytes_written != ctypes.sizeof(info):
        return None
    return f"{info.started_seconds}:{info.started_microseconds}"
