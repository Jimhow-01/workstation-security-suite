
"""
Lock Workstation — internet-driven lock orchestration.

Changes in this revision:
- Lock is now TRIGGERED by the internet monitor after 30 minutes offline.
- While locked, the connectivity DB is FROZEN (no writes) even if the internet returns.
- On process start, monitor checks previous DB; if a 30+ min outage had occurred
  (or 'lock_required' persisted), it immediately triggers the lock again.
- The outage entry ('down_start') is only CLEARED after a successful unlock.
- 1-hour offline still schedules a forced shutdown in 60 seconds.
- Task Manager watchdog, single-display mode, and keyboard hook are enabled
  only when lock is activated (not at app start).
"""

import base64
import ctypes
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import subprocess
import threading
import time
import tkinter as tk
import winreg
from datetime import datetime, timedelta

import psutil
import pyautogui
import requests
import win32api
import win32con
import win32gui

# -----------------------------
# Logging / Globals
# -----------------------------
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONNECTIVITY_DB_PATH = os.path.join(BASE_DIR, "connectivity_log.json")

# HMAC secret (hardcoded per request)
HMAC_SECRET = os.environ["HMAC_SECRET"].encode()
HMAC_DIGEST = "sha256"
UNLOCK_KEY_LEN = 12

# Policy toggles (applied when lock activates)
BLOCK_TASK_MANAGER_ON_LOCK = True
FORCE_SINGLE_DISPLAY_ON_LOCK = True
RESTORE_MULTI_DISPLAY_ON_UNLOCK = True

# Timing thresholds
LOCK_THRESHOLD_MINUTES = 30           # lock UI after 30 minutes offline
SHUTDOWN_THRESHOLD_HOURS = 1          # shutdown after 1 hour offline
INTERNET_POLL_SECONDS = 60

# Runtime flags/state
SECURITY_SHUTDOWN_TRIGGERED = False
SESSION_MACHINE_ID: int | None = None
DB_FROZEN = False                     # true while lock UI is active
LOCK_ACTIVE = False                   # true when UI/policies are in effect
TASKMGR_WATCHDOG_STARTED = False
KEYBOARD_HOOK_INSTALLED = False
SHUTDOWN_SCHEDULED = False

# Patrol intervals (ms)
MOUSE_PATROL_MS = 25
TOPMOST_ENFORCE_MS = 800
FULLSCREEN_REAPPLY_MS = 1200


# -----------------------------
# Win32 helpers / structs
# -----------------------------
class RECT(ctypes.Structure):
    """
    Minimal RECT for ClipCursor compatibility.
    """
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def is_admin() -> bool:
    """
    Return whether the current process has administrator privileges.

    :return: True if admin; False otherwise.
    :rtype: bool
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:
        logger.warning("Failed to check admin privileges: %s", exc)
        return False


def get_primary_screen_rect() -> tuple[int, int]:
    """
    Get primary screen width and height.

    :return: (width, height)
    :rtype: tuple[int, int]
    """
    return win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)


# -----------------------------
# Machine ID & HMAC
# -----------------------------
def get_machine_id() -> int:
    """
    Generate a per-session 10-digit random machine ID.

    The ID is generated once at process start and cached in memory only.
    It remains stable for the lifetime of the running program. A new ID
    is created on the next program start or computer reboot.

    :return: A 10-digit integer in the range [1_000_000_000, 9_999_999_999].
    :rtype: int
    """
    global SESSION_MACHINE_ID
    if SESSION_MACHINE_ID is None:
        SESSION_MACHINE_ID = secrets.randbelow(9_000_000_000) + 1_000_000_000
        logger.debug("Generated per-session machine ID: %d", SESSION_MACHINE_ID)
    return SESSION_MACHINE_ID


def hmac_sign_id(id_value: int) -> str:
    """
    Compute the unlock key for the given ID using HMAC-SHA256 (base64-url).

    :param id_value: The numeric ID shown by the program.
    :type id_value: int
    :return: The unlock key (first 12 base64-url chars).
    :rtype: str
    """
    digestmod = getattr(hashlib, HMAC_DIGEST)
    mac = hmac.new(HMAC_SECRET, str(id_value).encode("utf-8"), digestmod)
    return base64.urlsafe_b64encode(mac.digest()).decode("utf-8")[:UNLOCK_KEY_LEN]


def hmac_verify_id(id_value: int, unlock_key: str) -> bool:
    """
    Verify whether the provided unlock_key matches this machine's ID.

    :param id_value: The numeric ID shown by the program.
    :type id_value: int
    :param unlock_key: Key input by the user/IT (first 12 base64-url chars).
    :type unlock_key: str
    :return: True if valid; False otherwise.
    :rtype: bool
    """
    try:
        expected = hmac_sign_id(id_value)
        return hmac.compare_digest(expected, unlock_key.strip())
    except Exception as exc:
        logger.error("HMAC verification error: %s", exc)
        return False


# -----------------------------
# Connectivity DB helpers
# -----------------------------
def _read_connectivity_db() -> dict:
    """
    Read the local connectivity log.

    Structure:
      - last_up: ISO str | None
      - last_down: ISO str | None  (time outage ended / came back)
      - down_start: ISO str | None (time outage started)
      - lock_required: bool | None (persist lock requirement across restarts)

    :return: Dict with fields above.
    :rtype: dict
    """
    if not os.path.exists(CONNECTIVITY_DB_PATH):
        return {"last_up": None, "last_down": None, "down_start": None, "lock_required": False}
    try:
        with open(CONNECTIVITY_DB_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"last_up": None, "last_down": None, "down_start": None, "lock_required": False}
        data.setdefault("lock_required", False)
        return data
    except Exception as exc:
        logger.warning("Failed to read connectivity_log.json: %s", exc)
        return {"last_up": None, "last_down": None, "down_start": None, "lock_required": False}


def _write_connectivity_db(data: dict) -> None:
    """
    Persist the local connectivity log.

    :param data: Structure with DB fields.
    :type data: dict
    """
    if DB_FROZEN:
        logger.debug("DB is frozen; refusing to write connectivity_log.json")
        return
    try:
        with open(CONNECTIVITY_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("Failed to write connectivity_log.json: %s", exc)


def log_in_lightdb(connection_lost: bool) -> None:
    """
    Update the connectivity log based on the current state (NO-OP while frozen).

    :param connection_lost: True if internet is down; False if up.
    :type connection_lost: bool
    """
    if DB_FROZEN:
        logger.debug("DB frozen; skip logging (connection_lost=%s).", connection_lost)
        return

    data = _read_connectivity_db()
    now_iso = datetime.utcnow().isoformat()

    if not connection_lost:
        data["last_up"] = now_iso
        if data.get("down_start"):
            data["last_down"] = now_iso
            data["down_start"] = None
            logger.debug("Connectivity restored; outage ended.")
    else:
        if not data.get("down_start"):
            data["down_start"] = now_iso
            logger.debug("Outage started at %s", now_iso)

    _write_connectivity_db(data)


def outage_elapsed() -> timedelta:
    """
    Get the timedelta since outage started (0 if no outage recorded).

    :return: Elapsed time since 'down_start'.
    :rtype: datetime.timedelta
    """
    data = _read_connectivity_db()
    down_start = data.get("down_start")
    if not down_start:
        return timedelta(0)
    try:
        started = datetime.fromisoformat(down_start)
    except ValueError:
        logger.warning("Invalid down_start: %s", down_start)
        return timedelta(0)
    return datetime.utcnow() - started


def is_lock_required_by_history() -> bool:
    """
    Determine whether history implies we should be locked now.

    True if:
      - DB says 'lock_required' is True; OR
      - There's a recorded outage whose elapsed time >= LOCK_THRESHOLD_MINUTES.

    :return: Whether a lock should be active based on DB alone.
    :rtype: bool
    """
    data = _read_connectivity_db()
    if bool(data.get("lock_required")):
        return True
    return outage_elapsed() >= timedelta(minutes=LOCK_THRESHOLD_MINUTES)


# -----------------------------
# Internet checks & shutdown
# -----------------------------
def _http_probe_204(timeout_seconds: int = 5) -> bool:
    """
    HTTP probe that expects a 204/No Content from well-known endpoints.
    Returns True if any endpoint gives the expected status code.

    :param timeout_seconds: Timeout per request in seconds.
    :type timeout_seconds: int
    :rtype: bool
    """
    urls = [
        "https://www.gstatic.com/generate_204",          # Google (HTTPS)
        "http://connectivitycheck.gstatic.com/generate_204",  # Google (HTTP)
        "http://www.msftconnecttest.com/connecttest.txt",     # Microsoft (expects 200)
    ]
    try:
        for url in urls:
            try:
                resp = requests.get(url, timeout=timeout_seconds, allow_redirects=False)
                if "generate_204" in url and resp.status_code == 204:
                    return True
                if "connecttest.txt" in url and resp.status_code == 200:
                    return True
            except requests.RequestException:
                continue
    except Exception:
        pass
    return False


def _tcp_probe(endpoints: list[tuple[str, int]] | None = None, timeout_seconds: int = 3) -> bool:
    """
    TCP connectivity probe to public IPs (no DNS needed).
    Returns True if any socket connects.

    :param endpoints: List of (host, port) tuples to try.
    :type endpoints: list[tuple[str, int]] | None
    :param timeout_seconds: Timeout per socket in seconds.
    :type timeout_seconds: int
    :rtype: bool
    """
    if endpoints is None:
        endpoints = [
            ("1.1.1.1", 443),
            ("8.8.8.8", 53),
            ("8.8.4.4", 53),
            ("9.9.9.9", 443),
        ]
    for host, port in endpoints:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                return True
        except OSError:
            continue
    return False


def _dns_probe(hosts: list[str] | None = None) -> bool:
    """
    DNS resolution probe.
    Returns True if we can resolve at least one common hostname.

    :param hosts: Hostnames to resolve.
    :type hosts: list[str] | None
    :rtype: bool
    """
    if hosts is None:
        hosts = ["www.microsoft.com", "www.google.com", "www.cloudflare.com"]
    for h in hosts:
        try:
            socket.gethostbyname(h)
            return True
        except OSError:
            continue
    return False


def check_internet(timeout_seconds: int = 5) -> bool:
    """
    Robust connectivity check combining HTTP-204, TCP, and DNS probes.
    Consider ONLINE only if at least 2 of the 3 categories succeed.

    :param timeout_seconds: Probe timeout in seconds (per probe).
    :type timeout_seconds: int
    :return: True if considered online; False otherwise.
    :rtype: bool
    """
    http_ok = _http_probe_204(timeout_seconds)
    tcp_ok = _tcp_probe(timeout_seconds=timeout_seconds)
    dns_ok = _dns_probe()

    ok_count = sum((1 if http_ok else 0, 1 if tcp_ok else 0, 1 if dns_ok else 0))
    logger.debug("Probes — HTTP:%s TCP:%s DNS:%s (ok=%d)", http_ok, tcp_ok, dns_ok, ok_count)
    return ok_count >= 2


def schedule_shutdown_after_delay(seconds: int = 60) -> None:
    """
    Schedule a Windows shutdown after 'seconds'.

    :param seconds: Seconds until shutdown.
    :type seconds: int
    :raises RuntimeError: If the command fails.
    """
    try:
        cmd = f"shutdown /s /f /t {int(seconds)}"
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            logger.warning("Shutdown scheduled to occur in %s seconds.", seconds)
        else:
            raise RuntimeError(result.stderr.decode("utf-8", errors="ignore"))
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
        logger.error("Failed to schedule shutdown: %s", stderr)
        raise RuntimeError(f"Failed to schedule shutdown: {stderr}") from exc


# -----------------------------
# Display control
# -----------------------------
def force_single_display() -> None:
    """
    Force single-display mode (disconnect other monitors) using DisplaySwitch.exe (/internal).
    """
    try:
        subprocess.run("DisplaySwitch.exe /internal", shell=True)
        logger.warning("Forced single display (/internal).")
    except Exception as exc:
        logger.error("Failed to force single display: %s", exc)


def restore_multi_display() -> None:
    """
    Restore multi-display mode (extend) using DisplaySwitch.exe (/extend).
    """
    try:
        subprocess.run("DisplaySwitch.exe /extend", shell=True)
        logger.debug("Restored multi display (/extend).")
    except Exception as exc:
        logger.error("Failed to restore multi display: %s", exc)


# -----------------------------
# Task Manager policy
# -----------------------------
def block_task_manager() -> None:
    """
    Block Task Manager via HKCU policy (DisableTaskMgr=1).
    """
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        logger.warning("Task Manager blocked (DisableTaskMgr=1).")
    except PermissionError:
        logger.error("No permission to change Task Manager policy.")
    except Exception as exc:
        logger.error("Failed to block Task Manager: %s", exc)


def unblock_task_manager() -> None:
    """
    Unblock Task Manager (DisableTaskMgr=0).
    """
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        logger.debug("Task Manager unblocked (DisableTaskMgr=0).")
    except Exception as exc:
        logger.error("Failed to unblock Task Manager: %s", exc)


# -----------------------------
# Task Manager watchdog + BitLocker
# -----------------------------
def _is_taskmgr_process_running() -> bool:
    """
    Check if Task Manager process is running by scanning process list.

    :return: True if a process matching Task Manager is found.
    :rtype: bool
    """
    targets = {"taskmgr.exe", "taskmgr"}  # process name is stable across locales
    try:
        for proc in psutil.process_iter(attrs=["name", "exe", "cmdline"]):
            name = (proc.info.get("name") or "").lower()
            exe = (proc.info.get("exe") or "").lower()
            cmd = " ".join(proc.info.get("cmdline") or ()).lower()
            if any(tok in (name, exe) for tok in targets) or "taskmgr" in cmd:
                return True
    except Exception as exc:
        logger.debug("Process scan error: %s", exc)
    return False


def _any_window_title_is_taskmgr() -> bool:
    """
    Enumerate top-level windows and look for Task Manager titles in common locales.

    :return: True if a Task Manager window is found by title.
    :rtype: bool
    """
    titles: list[str] = []

    def _enum_cb(hwnd, _param):
        try:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    titles.append(title)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception as exc:
        logger.debug("EnumWindows failed: %s", exc)
        return False

    needles = [
        "task manager",          # English
        "gerenciador de tarefas" # Portuguese (BR)
    ]
    for t in titles:
        low = t.lower()
        if any(needle in low for needle in needles) or "taskmgr" in low:
            return True
    return False


def is_task_manager_active() -> bool:
    """
    Determine if Task Manager is active by process or window title.

    :return: True if Task Manager presence is detected.
    :rtype: bool
    """
    return _is_taskmgr_process_running() or _any_window_title_is_taskmgr()


def trigger_bitlocker_recovery(drive_letter: str = "C:") -> None:
    """
    Force BitLocker recovery on the specified drive using 'manage-bde -forcerecovery'.

    :param drive_letter: Drive letter to force recovery on (e.g., 'C:').
    :type drive_letter: str
    """
    try:
        command = f'manage-bde -forcerecovery {drive_letter}'
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            logger.warning("BitLocker recovery mode triggered on %s", drive_letter)
        else:
            stderr = result.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"manage-bde returned {result.returncode}: {stderr}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
        logger.error("Failed to trigger BitLocker recovery: %s", stderr)
        raise RuntimeError(f"Failed to execute BitLocker command: {stderr}") from exc
    except Exception as exc:
        logger.error("trigger_bitlocker_recovery() unexpected error: %s", exc)
        raise


def check_task_manager_thread(state: "UIState", poll_seconds: int = 1) -> None:
    """
    Watchdog loop that monitors for Task Manager while the workstation is locked.
    If detected, it forces BitLocker recovery and shuts the computer down.

    :param state: Shared UI state to know if the station is unlocked.
    :type state: UIState
    :param poll_seconds: Interval between checks, in seconds (>= 1 recommended).
    :type poll_seconds: int
    """
    global SECURITY_SHUTDOWN_TRIGGERED
    logger.debug("Task Manager watchdog started (poll=%ss).", poll_seconds)

    while True:
        try:
            if LOCK_ACTIVE and not state.unlocked and not SECURITY_SHUTDOWN_TRIGGERED:
                if is_task_manager_active():
                    logger.warning("Task Manager detected while locked. Initiating protective actions.")
                    try:
                        if not is_admin():
                            logger.warning("Process is not elevated; BitLocker command may fail.")
                        trigger_bitlocker_recovery("C:")
                    except Exception as exc:
                        logger.error("BitLocker trigger failed (continuing to shutdown): %s", exc)

                    SECURITY_SHUTDOWN_TRIGGERED = True
                    try:
                        subprocess.run("shutdown /s /f /t 0", shell=True)
                    except Exception as exc:
                        logger.error("Shutdown command failed: %s", exc)
                    # NOTE: antes havia `break` dentro de `finally`, o que silenciava
                    # qualquer excecao do subprocess.run (B012). O loop e encerrado
                    # aqui, explicitamente, depois de tratar a falha.
                    break
        except Exception as exc:
            logger.debug("Watchdog loop error: %s", exc)

        time.sleep(max(1, int(poll_seconds)))


def start_taskmgr_watchdog(state: "UIState", poll_seconds: int = 1) -> None:
    """
    Start the Task Manager watchdog on a daemon thread (idempotent).

    :param state: Shared UI state.
    :type state: UIState
    :param poll_seconds: Interval between checks (seconds).
    :type poll_seconds: int
    """
    global TASKMGR_WATCHDOG_STARTED
    if TASKMGR_WATCHDOG_STARTED:
        return
    t = threading.Thread(target=check_task_manager_thread, args=(state, poll_seconds), daemon=True)
    t.start()
    TASKMGR_WATCHDOG_STARTED = True
    logger.debug("Task Manager watchdog thread started (daemon=%s).", t.daemon)


# -----------------------------
# Keyboard hook (block Alt+Tab, Win keys, etc.)
# -----------------------------
LLKHF_ALTDOWN = 0x20
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_F4 = 0x73
VK_MENU = 0x12      # Alt
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C

_keyboard_hook_handle = None
_keyboard_proc_ref = None  # keep ref to avoid GC


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """
    ctypes structure for low-level keyboard events.
    """
    _fields_ = [
        ("vkCode", ctypes.c_uint32),
        ("scanCode", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_uint64),
    ]


def _mod_down(vk: int) -> bool:
    """
    Check if a virtual-key modifier is currently down using GetAsyncKeyState.

    :param vk: Virtual-key code.
    :type vk: int
    :return: True if pressed; False otherwise.
    :rtype: bool
    """
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _should_block(vk_code: int, flags: int) -> bool:
    """
    Decide whether to block a keystroke based on vk_code and current modifiers.

    Blocks:
      - Alt+Tab, Alt+F4, Alt+Esc
      - Ctrl+Esc, Ctrl+Shift+Esc (Task Manager)
      - Left/Right Windows keys
    """
    alt_down = _mod_down(VK_MENU) or (flags & LLKHF_ALTDOWN) == LLKHF_ALTDOWN
    ctrl_down = _mod_down(VK_CONTROL)

    if vk_code in (VK_LWIN, VK_RWIN):
        return True
    if alt_down and vk_code in (VK_TAB, VK_F4, VK_ESCAPE):
        return True
    # Ctrl+Esc ja cobre Ctrl+Shift+Esc, entao um ramo separado para Shift era
    # inalcanca e foi removido.
    return bool(ctrl_down and vk_code == VK_ESCAPE)


def install_keyboard_hook() -> None:
    """
    Install a global low-level keyboard hook to suppress system shortcuts.

    Note: Ctrl+Alt+Del cannot be suppressed by user-mode apps.
    """
    global _keyboard_hook_handle, _keyboard_proc_ref, KEYBOARD_HOOK_INSTALLED

    if KEYBOARD_HOOK_INSTALLED:
        return

    @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(KBDLLHOOKSTRUCT))
    def low_level_keyboard_proc(nCode, wParam, lParam):
        try:
            if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kbd = lParam.contents
                if _should_block(kbd.vkCode, kbd.flags):
                    return 1
        except Exception as exc:
            logger.debug("Keyboard hook proc error: %s", exc)
        return ctypes.windll.user32.CallNextHookEx(_keyboard_hook_handle, nCode, wParam, ctypes.cast(lParam, ctypes.c_void_p))

    _keyboard_proc_ref = low_level_keyboard_proc
    h_instance = ctypes.windll.kernel32.GetModuleHandleW(None)
    _keyboard_hook_handle = ctypes.windll.user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, _keyboard_proc_ref, h_instance, 0
    )
    if not _keyboard_hook_handle:
        logger.error("Failed to install keyboard hook (GLE=%s).", ctypes.windll.kernel32.GetLastError())
    else:
        KEYBOARD_HOOK_INSTALLED = True
        logger.warning("Keyboard hook installed (Alt+Tab, Win keys, etc. suppressed).")


def uninstall_keyboard_hook() -> None:
    """
    Uninstall the previously installed low-level keyboard hook.
    """
    global _keyboard_hook_handle, KEYBOARD_HOOK_INSTALLED
    try:
        if _keyboard_hook_handle:
            ctypes.windll.user32.UnhookWindowsHookEx(_keyboard_hook_handle)
            _keyboard_hook_handle = None
            KEYBOARD_HOOK_INSTALLED = False
            logger.debug("Keyboard hook uninstalled.")
    except Exception as exc:
        logger.debug("Failed to uninstall keyboard hook: %s", exc)


# -----------------------------
# UI State / Mouse confinement
# -----------------------------
class UIState:
    """
    Hold runtime UI state (machine ID, window, unlock box rect, timers).
    """
    def __init__(self, machine_id: int) -> None:
        """
        Initialize UIState.

        :param machine_id: Deterministic (per-session) machine ID.
        :type machine_id: int
        """
        self.machine_id = machine_id
        self.unlocked = False
        self.root: tk.Tk | None = None
        self.unlock_box_rect: tuple[int, int, int, int] | None = None  # (L,T,R,B) in screen coords
        self.mouse_patrol_after_id: str | None = None
        self.topmost_after_id: str | None = None
        self.fullscreen_after_id: str | None = None


def set_borderless_fullscreen(root: "tk.Tk") -> None:
    """
    Make the Tk window borderless and match the primary screen.

    We DO NOT set Tk's -fullscreen attribute while overrideredirect is True.

    :param root: Tk root window.
    :type root: tk.Tk
    """
    try:
        root.overrideredirect(True)
        root.attributes("-topmost", True)
    except Exception as exc:
        logger.debug("overrideredirect/topmost failed: %s", exc)

    try:
        width, height = get_primary_screen_rect()
        root.geometry(f"{width}x{height}+0+0")
    except Exception as exc:
        logger.debug("Geometry set failed: %s", exc)

    try:
        hwnd = root.winfo_id()
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOOWNERZORDER | win32con.SWP_SHOWWINDOW
        )
    except Exception as exc:
        logger.debug("SetWindowPos TOPMOST failed: %s", exc)


def enforce_topmost_loop(state: "UIState") -> None:
    """
    Periodically enforce topmost Z-order so the window stays above everything.

    :param state: Shared UI state with root reference.
    :type state: UIState
    """
    if not state.root:
        return
    try:
        hwnd = state.root.winfo_id()
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOOWNERZORDER
        )
    except Exception as exc:
        logger.debug("Topmost enforce step failed: %s", exc)
    finally:
        state.topmost_after_id = state.root.after(TOPMOST_ENFORCE_MS, lambda: enforce_topmost_loop(state))


def reapply_fullscreen_loop(state: "UIState") -> None:
    """
    Periodically re-apply borderless fullscreen geometry to handle display/DPI changes.

    :param state: Shared UI state with root reference.
    :type state: UIState
    """
    if not state.root:
        return
    try:
        set_borderless_fullscreen(state.root)
    except Exception as exc:
        logger.debug("Fullscreen reapply failed: %s", exc)
    finally:
        state.fullscreen_after_id = state.root.after(FULLSCREEN_REAPPLY_MS, lambda: reapply_fullscreen_loop(state))


def clip_cursor_to_rect(rect: tuple[int, int, int, int]) -> bool:
    """
    Clip the mouse cursor to the given screen rectangle.

    :param rect: (L, T, R, B)
    :type rect: tuple[int, int, int, int]
    :return: True if clip applied; False otherwise.
    :rtype: bool
    """
    l, t, r, b = rect
    w, h = max(0, r - l), max(0, b - t)
    if w < 200 or h < 120:
        logger.debug("Refusing to clip to too-small rect (%d×%d).", w, h)
        return False
    try:
        rc = RECT(l, t, r, b)
        ctypes.windll.user32.ClipCursor(ctypes.byref(rc))
        logger.warning("Mouse clipped to unlock box: (%d,%d,%d,%d).", l, t, r, b)
        return True
    except Exception as exc:
        logger.error("Failed to clip mouse: %s", exc)
        return False


def release_mouse_clip() -> None:
    """
    Release any mouse confinement (ClipCursor(None)).
    """
    try:
        ctypes.windll.user32.ClipCursor(None)
        logger.debug("Mouse clip released.")
    except Exception as exc:
        logger.error("Failed to release mouse clip: %s", exc)


def patrol_mouse_inside_rect(rect: tuple[int, int, int, int]) -> None:
    """
    Keep the pointer inside rect; if outside, clamp and reposition.

    :param rect: (L, T, R, B) in screen coordinates.
    :type rect: tuple[int, int, int, int]
    """
    try:
        l, t, r, b = rect
        x, y = win32api.GetCursorPos()
        clamped_x = max(l + 1, min(x, r - 2))
        clamped_y = max(t + 1, min(y, b - 2))
        if (x, y) != (clamped_x, clamped_y):
            win32api.SetCursorPos((clamped_x, clamped_y))
    except Exception as exc:
        logger.debug("Mouse patrol step issue: %s", exc)


def start_mouse_patrol(state: "UIState") -> None:
    """
    Begin periodic patrol to keep the mouse inside the unlock box rect.

    :param state: Shared UI state with unlock_box_rect set.
    :type state: UIState
    """
    if not state.root or not state.unlock_box_rect:
        return

    def _tick():
        if state.unlocked or not LOCK_ACTIVE:
            return
        try:
            patrol_mouse_inside_rect(state.unlock_box_rect)
        finally:
            state.mouse_patrol_after_id = state.root.after(MOUSE_PATROL_MS, _tick)

    if state.mouse_patrol_after_id:
        try:
            state.root.after_cancel(state.mouse_patrol_after_id)
        except Exception:
            pass
        state.mouse_patrol_after_id = None

    state.mouse_patrol_after_id = state.root.after(120, _tick)


# -----------------------------
# UI build / activation
# -----------------------------
def build_ui(root: "tk.Tk", state: "UIState") -> dict:
    """
    Build the fullscreen UI and the central unlock box (does NOT activate lock).

    :param root: Tk root instance.
    :type root: tk.Tk
    :param state: Shared UI state.
    :type state: UIState
    :return: Dict of created widgets for future updates.
    :rtype: dict
    """
    # Base container
    container = tk.Frame(root, bg="#111111")
    container.pack(fill="both", expand=True)

    # Canvas to draw the bounding rectangle / layout anchor
    canvas = tk.Canvas(container, highlightthickness=0, bg="#111111")
    canvas.pack(fill="both", expand=True)

    # Compute unlock box bounds based on screen size
    scr_w, scr_h = get_primary_screen_rect()
    box_w = max(640, int(scr_w * 0.38))
    box_h = max(260, int(scr_h * 0.28))
    box_l = (scr_w - box_w) // 2
    box_t = (scr_h - box_h) // 2
    box_r = box_l + box_w
    box_b = box_t + box_h
    state.unlock_box_rect = (box_l, box_t, box_r, box_b)

    rect_id = canvas.create_rectangle(
        box_l, box_t, box_r, box_b,
        outline="#DDDDDD", width=2, fill="#1B1B1B"
    )

    unlock_frame = tk.Frame(canvas, bg="#1B1B1B")
    canvas.create_window(
        (box_l + box_r) // 2,
        (box_t + box_b) // 2,
        window=unlock_frame,
        anchor="center"
    )

    title = tk.Label(unlock_frame, text="Workstation Lock\nFurther attempts to access this machine will be logged.\nContact your administrator for assistance.", font=("Segoe UI", 18, "bold"), bg="#1B1B1B", fg="#FFFFFF")
    title.pack(anchor="center", pady=(0, 16))

    id_label = tk.Label(unlock_frame, text=f"Your ID: {state.machine_id}", font=("Segoe UI", 12), bg="#1B1B1B", fg="#CCCCCC")
    id_label.pack(anchor="center", pady=(0, 12))

    entry_label = tk.Label(unlock_frame, text="Enter unlock key:", font=("Segoe UI", 11), bg="#1B1B1B", fg="#CCCCCC")
    entry_label.pack(anchor="w")

    entry = tk.Entry(unlock_frame, font=("Segoe UI", 12))
    entry.pack(fill="x", pady=(0, 10))

    status = tk.Label(unlock_frame, text="", anchor="w", font=("Segoe UI", 10), bg="#1B1B1B", fg="#CCCCCC")
    status.pack(fill="x", pady=(6, 0))

    def try_unlock(_event=None):
        """
        Validate the unlock key; on success, hide the window but let the app
        continue running (internet monitor still active). Clears DB after unlock.
        """
        key = entry.get().strip()
        if not key:
            status.config(text="Please enter the unlock key.", fg="orange")
            return

        if hmac_verify_id(state.machine_id, key):
            try:
                uninstall_keyboard_hook()
            except Exception:
                pass
            try:
                release_mouse_clip()
            except Exception:
                pass
            try:
                if RESTORE_MULTI_DISPLAY_ON_UNLOCK:
                    restore_multi_display()
            except Exception:
                pass
            try:
                unblock_task_manager()
            except Exception:
                pass

            # Clear DB only NOW (after unlock), regardless of when internet returned
            _clear_outage_and_unlock_db()

            # Update runtime flags
            global DB_FROZEN, LOCK_ACTIVE
            DB_FROZEN = False
            LOCK_ACTIVE = False
            state.unlocked = True

            status.config(text="Unlocked. Window will close. Monitoring continues.", fg="green")
            try:
                root.after(250, root.withdraw)
            except Exception as exc:
                logger.debug("Failed to withdraw window: %s", exc)
            logger.warning("Station unlocked; window hidden, monitor continues.")
        else:
            status.config(text="Invalid key. Please try again.", fg="red")
            logger.warning("Invalid unlock key entered.")

    entry.bind("<Return>", try_unlock)
    unlock_btn = tk.Button(unlock_frame, text="Unlock", command=try_unlock, font=("Segoe UI", 12))
    unlock_btn.pack(anchor="e")

    def swallow_close(_event=None):
        logger.debug("Close attempt blocked.")
        return "break"
    try:
        root.bind("<Alt-F4>", swallow_close)
        root.protocol("WM_DELETE_WINDOW", lambda: None)
    except Exception:
        pass

    def on_configure(_event=None):
        # Recompute unlock box rect on resize/DPI changes
        if state.unlocked or not LOCK_ACTIVE:
            return
        try:
            sw, sh = get_primary_screen_rect()
            bw = max(640, int(sw * 0.38))
            bh = max(260, int(sh * 0.28))
            bl = (sw - bw) // 2
            bt = (sh - bh) // 2
            br = bl + bw
            bb = bt + bh
            state.unlock_box_rect = (bl, bt, br, bb)
            canvas.coords(rect_id, bl, bt, br, bb)
        except Exception as exc:
            logger.debug("on_configure layout update failed: %s", exc)
        try:
            set_borderless_fullscreen(root)
        except Exception:
            pass
        clip_cursor_to_rect(state.unlock_box_rect)

    root.bind("<Configure>", on_configure)

    logger.debug("UI built (hidden by default).")
    return {
        "id_label": id_label,
        "entry": entry,
        "status": status,
        "unlock_btn": unlock_btn,
        "title": title,
        "canvas": canvas,
        "rect_id": rect_id,
    }


def activate_lock_ui(state: "UIState") -> None:
    """
    Activate the lock UI and policies. This function is safe to call multiple times:
    it only takes effect when not already LOCK_ACTIVE.

    :param state: Shared UI state (must have root assigned).
    :type state: UIState
    """
    global DB_FROZEN, LOCK_ACTIVE

    if LOCK_ACTIVE:
        logger.debug("Lock UI already active; skipping activation.")
        return

    # Persist lock requirement and freeze DB going forward
    _mark_lock_required_and_freeze()

    # Apply OS policies for lock
    if BLOCK_TASK_MANAGER_ON_LOCK:
        block_task_manager()
    if FORCE_SINGLE_DISPLAY_ON_LOCK:
        force_single_display()
    install_keyboard_hook()
    start_taskmgr_watchdog(state, poll_seconds=1)

    # Show window & enforce behaviors on the Tk thread
    def _show():
        try:
            set_borderless_fullscreen(state.root)
            state.root.deiconify()
            state.root.lift()
            state.root.focus_force()
        except Exception as exc:
            logger.debug("Failed to show lock UI: %s", exc)
        try:
            if state.unlock_box_rect:
                if clip_cursor_to_rect(state.unlock_box_rect):
                    start_mouse_patrol(state)
        except Exception as exc:
            logger.debug("Mouse clip/patrol init failed: %s", exc)
        try:
            enforce_topmost_loop(state)
            reapply_fullscreen_loop(state)
        except Exception as exc:
            logger.debug("Enforcement loops init failed: %s", exc)

    try:
        state.unlocked = False
        DB_FROZEN = True
        LOCK_ACTIVE = True
        state.root.after(0, _show)
        logger.warning("Lock UI activated (DB frozen).")
    except Exception as exc:
        logger.error("Failed to activate lock UI: %s", exc)


# -----------------------------
# DB transitions for lock/unlock
# -----------------------------
def _mark_lock_required_and_freeze() -> None:
    """
    Mark the DB as 'lock_required' and ensure an outage start exists, then freeze DB.
    """
    global DB_FROZEN
    data = _read_connectivity_db()
    now_iso = datetime.utcnow().isoformat()
    if not data.get("down_start"):
        data["down_start"] = now_iso
        logger.debug("down_start set at lock activation: %s", now_iso)
    data["lock_required"] = True
    # Write once, then freeze
    freeze_prev = DB_FROZEN
    DB_FROZEN = False
    _write_connectivity_db(data)
    DB_FROZEN = True or freeze_prev


def _clear_outage_and_unlock_db() -> None:
    """
    After a successful unlock, clear outage information and remove 'lock_required'.
    """
    data = _read_connectivity_db()
    now_iso = datetime.utcnow().isoformat()
    # Close the outage window now, regardless of prior connectivity changes
    data["last_up"] = now_iso
    data["last_down"] = now_iso
    data["down_start"] = None
    data["lock_required"] = False

    # Temporarily unfreeze to commit the cleanup
    global DB_FROZEN
    freeze_prev = DB_FROZEN
    DB_FROZEN = False
    _write_connectivity_db(data)
    DB_FROZEN = freeze_prev
    logger.debug("DB cleaned after unlock.")


# -----------------------------
# Internet monitor (drives lock)
# -----------------------------
def monitor_internet(state: "UIState", poll_seconds: int = INTERNET_POLL_SECONDS) -> None:
    """
    Monitor connectivity and orchestrate the lock lifecycle.

    Behavior:
      - On start, checks DB to see if a 30+ minute outage had occurred or
        if 'lock_required' persisted. If so, activates lock immediately.
      - Immediately logs the current connectivity state once at startup.
      - During normal operation, logs connectivity transitions.
      - If offline and outage reaches 30 minutes, activates lock and freezes DB.
      - While locked, DB remains frozen (no writes) until successful unlock.
      - If offline for >= 1 hour, schedules shutdown in 180 seconds.
    """
    logger.debug("Internet monitor started (poll=%ss).", poll_seconds)

    # Respect persisted state first
    if is_lock_required_by_history():
        logger.warning("History requires lock on startup. Activating lock.")
        activate_lock_ui(state)

    global SHUTDOWN_SCHEDULED

    # Write an initial connectivity snapshot NOW (if not locked/frozen)
    initial_online = check_internet()
    if not LOCK_ACTIVE:
        log_in_lightdb(connection_lost=not initial_online)
        logger.debug("Initial connectivity snapshot written. online=%s", initial_online)

    while True:
        is_online = check_internet()

        # Evaluate shutdown window against recorded outage start
        elapsed = outage_elapsed()
        if not is_online and elapsed >= timedelta(hours=SHUTDOWN_THRESHOLD_HOURS) and not SHUTDOWN_SCHEDULED:
            logger.warning("Offline for >= %s hour(s). Scheduling shutdown in 180s.", SHUTDOWN_THRESHOLD_HOURS)
            schedule_shutdown_after_delay(180)
            SHUTDOWN_SCHEDULED = True

        if not LOCK_ACTIVE:
            # Update DB normally while not locked
            log_in_lightdb(connection_lost=not is_online)
            elapsed = outage_elapsed()
            if not is_online and elapsed >= timedelta(minutes=LOCK_THRESHOLD_MINUTES):
                logger.warning("Offline for >= %s minutes. Activating lock.", LOCK_THRESHOLD_MINUTES)
                activate_lock_ui(state)
        else:
            # Locked: DB is frozen; do not mutate it.
            logger.debug("Locked. Skipping DB writes (is_online=%s).", is_online)

        time.sleep(max(5, int(poll_seconds)))


def start_internet_monitor_thread(state: "UIState") -> None:
    """
    Start the internet monitor on a daemon thread with access to UI state.

    :param state: Shared UI state (for triggering UI from monitor).
    :type state: UIState
    """
    t = threading.Thread(target=monitor_internet, args=(state,), daemon=True)
    t.start()
    logger.debug("Internet monitor thread started (daemon=%s).", t.daemon)


# -----------------------------
# Window creation & base config
# -----------------------------
def configure_window(root: "tk.Tk") -> None:
    """
    Set base window policies (title for HWND lookup if needed).

    :param root: Tk root instance.
    :type root: tk.Tk
    """
    try:
        root.title("Lock Workstation")
    except Exception as exc:
        logger.debug("Unsupported window attribute: %s", exc)


def create_window(state: "UIState") -> "tk.Tk":
    """
    Create the main window, apply base config, build UI, and keep it HIDDEN.

    :param state: Shared UI state.
    :type state: UIState
    :return: Configured (hidden) Tk root window.
    :rtype: tk.Tk
    """
    root = tk.Tk()
    state.root = root
    configure_window(root)
    set_borderless_fullscreen(root)
    build_ui(root, state)

    # Keep window hidden until monitor decides to lock
    try:
        root.withdraw()
    except Exception:
        pass

    logger.debug("Window created and withdrawn (waiting for monitor trigger).")
    return root


# -----------------------------
# Startup / Cleanup
# -----------------------------
def cleanup_on_exit() -> None:
    """
    Attempt to restore altered states when the app exits.
    """
    try:
        release_mouse_clip()
    except Exception as exc:
        logger.debug("Failed to release mouse clip on exit: %s", exc)

    try:
        uninstall_keyboard_hook()
    except Exception as exc:
        logger.debug("Failed to uninstall keyboard hook on exit: %s", exc)

    try:
        unblock_task_manager()
    except Exception as exc:
        logger.debug("Failed to restore Task Manager on exit: %s", exc)

    try:
        if RESTORE_MULTI_DISPLAY_ON_UNLOCK:
            restore_multi_display()
    except Exception as exc:
        logger.debug("Failed to restore display mode on exit: %s", exc)


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    """
    Application entrypoint.

    - Creates hidden window and UI (no policies applied yet).
    - Starts internet monitor which will activate the lock after 30 minutes offline
      or immediately on startup if history requires it.
    - On successful unlock, window hides but monitor keeps running.
    """
    machine_id = get_machine_id()
    state = UIState(machine_id=machine_id)

    root = create_window(state)
    start_internet_monitor_thread(state)

    logger.debug("Starting Tk mainloop.")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logger.warning("Terminated by KeyboardInterrupt.")
    except Exception as exc:
        logger.error("Error in mainloop: %s", exc)
    finally:
        cleanup_on_exit()


if __name__ == "__main__":
    main()

