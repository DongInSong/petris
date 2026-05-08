"""Windows boot-time autostart via Task Scheduler.

Registers a logon-triggered task with HighestAvailable run level, so an
elevated launch survives reboots. The HKCU Run key would be simpler but
auto-launched processes always come up at the user's standard token, which
breaks keystroke capture from UAC-elevated apps (UIPI).

Trade-off: creating or deleting a task with HIGHEST run level requires admin,
so each toggle triggers a UAC prompt. The query path doesn't — `is_enabled()`
runs as standard user.
"""
from __future__ import annotations

import os
import sys
import tempfile
from xml.sax.saxutils import escape as xml_escape

TASK_NAME = "Petris Autostart"


def is_supported() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def is_enabled() -> bool:
    """True if the scheduled task exists. Standard user can query."""
    if sys.platform != "win32":
        return False
    import subprocess
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def enable() -> bool:
    """Register the logon task. Triggers UAC; returns False if user declines."""
    if not is_supported():
        return False
    exe = sys.executable
    if not exe:
        return False
    xml = _build_task_xml(exe)
    fd, path = tempfile.mkstemp(prefix="petris_task_", suffix=".xml")
    try:
        # Task Scheduler XML must be UTF-16 with BOM — Python's 'utf-16'
        # codec writes both.
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(xml)
        params = f'/create /tn "{TASK_NAME}" /xml "{path}" /f'
        return _run_elevated("schtasks.exe", params)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def disable() -> bool:
    """Delete the logon task. Triggers UAC; no-op + success if already absent."""
    if sys.platform != "win32":
        return False
    if not is_enabled():
        return True
    params = f'/delete /tn "{TASK_NAME}" /f'
    return _run_elevated("schtasks.exe", params)


def _build_task_xml(exe_path: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <Triggers>\n'
        '    <LogonTrigger>\n'
        '      <Enabled>true</Enabled>\n'
        '    </LogonTrigger>\n'
        '  </Triggers>\n'
        '  <Principals>\n'
        '    <Principal id="Author">\n'
        '      <LogonType>InteractiveToken</LogonType>\n'
        '      <RunLevel>HighestAvailable</RunLevel>\n'
        '    </Principal>\n'
        '  </Principals>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        '    <AllowHardTerminate>false</AllowHardTerminate>\n'
        '    <StartWhenAvailable>true</StartWhenAvailable>\n'
        '    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n'
        '    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n'
        '    <Hidden>false</Hidden>\n'
        '    <Priority>7</Priority>\n'
        '  </Settings>\n'
        '  <Actions Context="Author">\n'
        '    <Exec>\n'
        f'      <Command>{xml_escape(exe_path)}</Command>\n'
        '    </Exec>\n'
        '  </Actions>\n'
        '</Task>\n'
    )


def _run_elevated(file: str, params: str) -> bool:
    """ShellExecuteExW with the 'runas' verb — UAC prompt, wait for the
    elevated child to exit, return True iff exit code was 0. False covers
    both UAC denial and schtasks failure; the caller can't distinguish but
    doesn't need to (revert the checkbox in either case).
    """
    import ctypes
    from ctypes import wintypes

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NO_CONSOLE = 0x00008000
    SW_HIDE = 0
    INFINITE = 0xFFFFFFFF

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('fMask', wintypes.ULONG),
            ('hwnd', wintypes.HWND),
            ('lpVerb', wintypes.LPCWSTR),
            ('lpFile', wintypes.LPCWSTR),
            ('lpParameters', wintypes.LPCWSTR),
            ('lpDirectory', wintypes.LPCWSTR),
            ('nShow', ctypes.c_int),
            ('hInstApp', wintypes.HINSTANCE),
            ('lpIDList', ctypes.c_void_p),
            ('lpClass', wintypes.LPCWSTR),
            ('hkeyClass', wintypes.HKEY),
            ('dwHotKey', wintypes.DWORD),
            ('hIconOrMonitor', wintypes.HANDLE),
            ('hProcess', wintypes.HANDLE),
        ]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    info.lpVerb = "runas"
    info.lpFile = file
    info.lpParameters = params
    info.nShow = SW_HIDE

    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL

    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        return False
    try:
        kernel32.WaitForSingleObject(info.hProcess, INFINITE)
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            return False
        return code.value == 0
    finally:
        kernel32.CloseHandle(info.hProcess)
