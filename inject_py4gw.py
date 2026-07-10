"""Inject the adjacent Py4GW.dll into running 32-bit Gw.exe processes."""

from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import struct
import time
from ctypes import wintypes


PROCESS_ACCESS = 0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
MEM_COMMIT_RESERVE = 0x00003000
MEM_RELEASE = 0x00008000
PAGE_READWRITE = 0x04
WAIT_OBJECT_0 = 0x00000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * 260),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32FirstW.restype = wintypes.BOOL
kernel32.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32NextW.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.VirtualAllocEx.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    ctypes.c_size_t,
    wintypes.DWORD,
    wintypes.DWORD,
]
kernel32.VirtualAllocEx.restype = wintypes.LPVOID
kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.LPCVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetProcAddress.argtypes = [wintypes.HMODULE, wintypes.LPCSTR]
kernel32.GetProcAddress.restype = wintypes.LPVOID
kernel32.CreateRemoteThread.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    ctypes.c_size_t,
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeThread.restype = wintypes.BOOL
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD]
kernel32.VirtualFreeEx.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def win_error(operation: str) -> OSError:
    return OSError(ctypes.get_last_error(), operation)


def running_gw_processes() -> list[int]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise win_error("CreateToolhelp32Snapshot(processes)")
    process_ids: list[int] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.casefold() == "gw.exe":
                process_ids.append(int(entry.th32ProcessID))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return process_ids


def loaded_py4gw(pid: int) -> tuple[int, str] | None:
    flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
    for attempt in range(5):
        snapshot = kernel32.CreateToolhelp32Snapshot(flags, pid)
        if snapshot != INVALID_HANDLE_VALUE:
            break
        if attempt == 4:
            raise win_error(f"CreateToolhelp32Snapshot(modules, pid={pid})")
        time.sleep(0.1)
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Module32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szModule.casefold() == "py4gw.dll":
                base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                return base, entry.szExePath
            ok = kernel32.Module32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


def inject(pid: int, dll_path: Path) -> int:
    process = kernel32.OpenProcess(PROCESS_ACCESS, False, pid)
    if not process:
        raise win_error(f"OpenProcess(pid={pid})")
    remote_path = None
    thread = None
    try:
        payload = os.fspath(dll_path).encode("utf-16-le") + b"\x00\x00"
        remote_path = kernel32.VirtualAllocEx(
            process,
            None,
            len(payload),
            MEM_COMMIT_RESERVE,
            PAGE_READWRITE,
        )
        if not remote_path:
            raise win_error(f"VirtualAllocEx(pid={pid})")

        buffer = ctypes.create_string_buffer(payload)
        written = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(
            process,
            remote_path,
            buffer,
            len(payload),
            ctypes.byref(written),
        ) or written.value != len(payload):
            raise win_error(f"WriteProcessMemory(pid={pid})")

        local_kernel32 = kernel32.GetModuleHandleW("kernel32.dll")
        load_library = kernel32.GetProcAddress(local_kernel32, b"LoadLibraryW")
        if not load_library:
            raise win_error("GetProcAddress(LoadLibraryW)")

        thread_id = wintypes.DWORD()
        thread = kernel32.CreateRemoteThread(
            process,
            None,
            0,
            load_library,
            remote_path,
            0,
            ctypes.byref(thread_id),
        )
        if not thread:
            raise win_error(f"CreateRemoteThread(pid={pid})")
        wait_result = kernel32.WaitForSingleObject(thread, 20_000)
        if wait_result != WAIT_OBJECT_0:
            raise RuntimeError(f"LoadLibraryW wait failed for PID {pid}: 0x{wait_result:08X}")

        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeThread(thread, ctypes.byref(exit_code)):
            raise win_error(f"GetExitCodeThread(pid={pid})")
        if exit_code.value == 0:
            raise RuntimeError(f"LoadLibraryW returned NULL for PID {pid}")
        return int(exit_code.value)
    finally:
        if thread:
            kernel32.CloseHandle(thread)
        if remote_path:
            kernel32.VirtualFreeEx(process, remote_path, 0, MEM_RELEASE)
        kernel32.CloseHandle(process)


def main() -> int:
    if struct.calcsize("P") != 4:
        print("ERROR: this injector must run with 32-bit Python.")
        return 1

    dll_path = Path(__file__).resolve().with_name("Py4GW.dll")
    if not dll_path.is_file():
        print(f"ERROR: DLL not found: {dll_path}")
        return 1

    digest = hashlib.sha256(dll_path.read_bytes()).hexdigest().upper()
    print(f"Py4GW DLL: {dll_path}")
    print(f"SHA256: {digest}")

    process_ids = running_gw_processes()
    if not process_ids:
        print("ERROR: no running Gw.exe process was found.")
        return 2

    failures = 0
    for pid in process_ids:
        try:
            loaded = loaded_py4gw(pid)
            if loaded:
                print(f"SKIP PID {pid}: Py4GW.dll already loaded at 0x{loaded[0]:08X}")
                continue
            load_result = inject(pid, dll_path)
            time.sleep(0.25)
            loaded = loaded_py4gw(pid)
            if not loaded:
                raise RuntimeError("module verification failed after LoadLibraryW")
            print(
                f"OK PID {pid}: LoadLibraryW=0x{load_result:08X}, "
                f"module=0x{loaded[0]:08X}"
            )
        except Exception as exc:
            failures += 1
            print(f"ERROR PID {pid}: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
