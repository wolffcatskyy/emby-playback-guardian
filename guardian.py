#!/usr/bin/env python3
"""
Emby Playback Guardian — Protects playback by pausing tasks and throttling downloads.

Monitors Emby/Jellyfin media servers and automatically:
  - Pauses library scans and metadata refreshes during active playback
  - Detects and kills stuck scheduled tasks
  - Throttles qBittorrent/SABnzbd when disk I/O is saturated
  - Restores everything when playback ends and load normalizes

https://github.com/wolffcatskyy/emby-playback-guardian
"""

import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

__version__ = "1.0.0"


def env(key, default=None):
    """Get environment variable, stripping whitespace."""
    val = os.environ.get(key, default)
    return val.strip() if isinstance(val, str) else val


def env_bool(key, default=False):
    """Get boolean environment variable."""
    val = env(key, str(default)).lower()
    return val in ("true", "1", "yes")


def env_int(key, default=0):
    """Get integer environment variable."""
    try:
        return int(env(key, str(default)))
    except (ValueError, TypeError):
        return default


EMBY_URL = env("EMBY_URL", "")
EMBY_API_KEY = env("EMBY_API_KEY", "")
SERVER_TYPE = env("SERVER_TYPE", "emby").lower()

QBIT_URL = env("QBIT_URL", "")
QBIT_USERNAME = env("QBIT_USERNAME", "admin")
QBIT_PASSWORD = env("QBIT_PASSWORD", "")

SABNZBD_URL = env("SABNZBD_URL", "")
SABNZBD_API_KEY = env("SABNZBD_API_KEY", "")
SABNZBD_THROTTLE_PCT = env_int("SABNZBD_THROTTLE_PCT", 50)

DISK_DEVICES = [d.strip() for d in env("DISK_DEVICES", "").split(",") if d.strip()]
DISK_PROC_PATH = env("DISK_PROC_PATH", "/host/proc/diskstats")
DISK_SAMPLE_SECONDS = env_int("DISK_SAMPLE_SECONDS", 2)

POLL_INTERVAL = env_int("POLL_INTERVAL", 30)
STUCK_SCAN_TIMEOUT = env_int("STUCK_SCAN_TIMEOUT", 7200)
IO_THRESHOLD = env_int("IO_THRESHOLD", 80)
DRY_RUN = env_bool("DRY_RUN", False)
LOG_LEVEL = env("LOG_LEVEL", "INFO").upper()

PAUSABLE_TASKS = [t.strip() for t in env(
    "PAUSABLE_TASKS",
    "Scan media library,Refresh Guide,Download subtitles,"
    "Video preview thumbnail extraction,Scan Metadata Folder"
).split(",") if t.strip()]


def setup_logging():
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = "[%(asctime)s] [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S",
                        stream=sys.stdout)
    return logging.getLogger("guardian")


log = setup_logging()


@dataclass
class TaskInfo:
    id: str
    name: str
    state: str
    first_seen_running: float = 0.0

    @property
    def runtime_seconds(self):
        if self.first_seen_running > 0:
            return time.time() - self.first_seen_running
        return 0


@dataclass
class GuardianState:
    tasks_we_paused: dict = field(default_factory=dict)
    downloads_throttled: bool = False
    qbit_alt_was_on: bool = False
    sab_original_speed: int = 100
    throttle_reason: str = ""
    task_run_tracker: dict = field(default_factory=dict)
    stuck_kills: list = field(default_factory=list)

    def clear_paused_tasks(self):
        self.tasks_we_paused.clear()

    def record_stuck_kill(self, task_name):
        self.stuck_kills.append({
            "task": task_name,
            "killed_at": datetime.now(timezone.utc).isoformat()
        })


class EmbyClient:
    """Emby/Jellyfin REST API client for sessions and task management."""

    def __init__(self, url, api_key, server_type="emby"):
        self.base = url.rstrip("/")
        self.api_key = api_key
        self.server_type = server_type
        self.session = requests.Session()
        self.session.headers["X-Emby-Token"] = api_key
        self.prefix = "/emby" if server_type == "emby" else ""

    def _url(self, path):
        return f"{self.base}{self.prefix}{path}"

    def _get(self, path, timeout=10):
        resp = self.session.get(self._url(path), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, timeout=10):
        resp = self.session.post(self._url(path), timeout=timeout)
        resp.raise_for_status()
        return resp

    def _delete(self, path, timeout=10):
        resp = self.session.delete(self._url(path), timeout=timeout)
        resp.raise_for_status()
        return resp

    def get_active_sessions(self):
        sessions = self._get("/Sessions")
        active = []
        for s in sessions:
            now_playing = s.get("NowPlayingItem")
            if now_playing:
                active.append({
                    "user": s.get("UserName", "unknown"),
                    "client": s.get("Client", "unknown"),
                    "device": s.get("DeviceName", "unknown"),
                    "item": now_playing.get("Name", "unknown"),
                    "type": now_playing.get("Type", "unknown"),
                    "play_method": s.get("PlayState", {}).get("PlayMethod", "unknown"),
                })
        return active

    def has_active_playback(self):
        sessions = self.get_active_sessions()
        if sessions:
            for s in sessions:
                log.info(f"  Active: {s['user']} -> '{s['item']}' "
                         f"({s['play_method']}) on {s['device']}")
        return len(sessions) > 0

    def get_scheduled_tasks(self):
        return self._get("/ScheduledTasks")

    def get_running_tasks(self, state_tracker):
        tasks = self.get_scheduled_tasks()
        running = []
        now = time.time()
        active_ids = set()

        for t in tasks:
            if t.get("State") == "Running":
                tid = t["Id"]
                active_ids.add(tid)
                first_seen = state_tracker.get(tid, now)
                if tid not in state_tracker:
                    state_tracker[tid] = first_seen
                running.append(TaskInfo(
                    id=tid, name=t["Name"], state=t["State"],
                    first_seen_running=first_seen,
                ))

        for tid in list(state_tracker.keys()):
            if tid not in active_ids:
                del state_tracker[tid]

        return running

    def stop_task(self, task_id):
        self._delete(f"/ScheduledTasks/Running/{task_id}")

    def test_connection(self):
        try:
            info = self._get("/System/Info/Public")
            name = info.get("ServerName", "Unknown")
            version = info.get("Version", "Unknown")
            log.info(f"Connected to {self.server_type.title()}: "
                     f"{name} v{version} at {self.base}")
            return True
        except Exception as e:
            log.error(f"Cannot connect to {self.server_type.title()} "
                      f"at {self.base}: {e}")
            return False


class QBitClient:
    """qBittorrent Web API client with session cookie management."""

    def __init__(self, url, username, password):
        self.base = url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._authenticated = False

    def _login(self):
        resp = self.session.post(
            f"{self.base}/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
            timeout=10
        )
        if resp.text.strip() == "Ok.":
            self._authenticated = True
            log.debug("qBittorrent: authenticated")
        else:
            raise ConnectionError(f"qBittorrent auth failed: {resp.text}")

    def _request(self, method, endpoint, **kwargs):
        if not self._authenticated:
            self._login()
        kwargs.setdefault("timeout", 10)
        resp = self.session.request(method, f"{self.base}{endpoint}", **kwargs)
        if resp.status_code == 403:
            self._login()
            resp = self.session.request(method, f"{self.base}{endpoint}", **kwargs)
        resp.raise_for_status()
        return resp

    def is_alt_speed_enabled(self):
        resp = self._request("GET", "/api/v2/transfer/speedLimitsMode")
        return resp.text.strip() == "1"

    def toggle_alt_speed(self):
        self._request("POST", "/api/v2/transfer/toggleSpeedLimitsMode")

    def enable_alt_speed(self):
        if not self.is_alt_speed_enabled():
            self.toggle_alt_speed()
            log.info("qBittorrent: enabled alternative speed limits")
            return True
        return False

    def disable_alt_speed(self):
        if self.is_alt_speed_enabled():
            self.toggle_alt_speed()
            log.info("qBittorrent: disabled alternative speed limits")
            return True
        return False

    def test_connection(self):
        try:
            self._login()
            mode = "alt" if self.is_alt_speed_enabled() else "normal"
            log.info(f"Connected to qBittorrent at {self.base} "
                     f"(speed mode: {mode})")
            return True
        except Exception as e:
            log.error(f"Cannot connect to qBittorrent at {self.base}: {e}")
            return False


class SABnzbdClient:
    """SABnzbd API client (stateless, uses apikey in query params)."""

    def __init__(self, url, api_key):
        self.base = url.rstrip("/")
        self.api_key = api_key

    def _api(self, mode, **params):
        params.update({"mode": mode, "apikey": self.api_key, "output": "json"})
        resp = requests.get(f"{self.base}/api", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_speed_limit(self):
        result = self._api("queue")
        return int(result.get("queue", {}).get("speedlimit", "100") or "100")

    def set_speed_limit(self, pct):
        self._api("config", name="speedlimit", value=str(pct))
        log.info(f"SABnzbd: speed limit set to {pct}%")

    def test_connection(self):
        try:
            result = self._api("queue")
            speed = result.get("queue", {}).get("speed", "?")
            limit = result.get("queue", {}).get("speedlimit", "100")
            log.info(f"Connected to SABnzbd at {self.base} "
                     f"(speed: {speed}, limit: {limit}%)")
            return True
        except Exception as e:
            log.error(f"Cannot connect to SABnzbd at {self.base}: {e}")
            return False


class DiskMonitor:
    """Parse /proc/diskstats to calculate disk busy percentage."""

    def __init__(self, devices, proc_path="/host/proc/diskstats",
                 sample_seconds=2):
        self.devices = devices
        self.proc_path = proc_path
        self.sample_seconds = sample_seconds

    def _read_io_ticks(self):
        result = {}
        try:
            with open(self.proc_path, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 13:
                        dev_name = parts[2]
                        if dev_name in self.devices:
                            result[dev_name] = int(parts[12])
        except FileNotFoundError:
            log.warning(f"Disk stats not found at {self.proc_path}")
        except Exception as e:
            log.warning(f"Error reading disk stats: {e}")
        return result

    def get_utilization(self):
        before = self._read_io_ticks()
        if not before:
            return 0.0

        time.sleep(self.sample_seconds)
        after = self._read_io_ticks()

        interval_ms = self.sample_seconds * 1000
        max_busy = 0.0

        for dev in self.devices:
            if dev in before and dev in after:
                delta = after[dev] - before[dev]
                busy_pct = min((delta / interval_ms) * 100, 100.0)
                if busy_pct > max_busy:
                    max_busy = busy_pct
                log.debug(f"  Disk {dev}: {busy_pct:.1f}% busy")

        return max_busy

    def test(self):
        ticks = self._read_io_ticks()
        if ticks:
            log.info(f"Disk monitoring: {len(ticks)} device(s) found "
                     f"({', '.join(ticks.keys())})")
            return True
        else:
            log.warning(f"Disk monitoring: no configured devices found "
                        f"in {self.proc_path}")
            return False


def is_pausable_task(task_name):
    name_lower = task_name.lower()
    return any(p.lower() in name_lower for p in PAUSABLE_TASKS)


def main():
    log.info(f"Emby Playback Guardian v{__version__}")
    if DRY_RUN:
        log.info("*** DRY RUN MODE -- no actions will be taken ***")

    if not EMBY_URL or not EMBY_API_KEY:
        log.error("EMBY_URL and EMBY_API_KEY are required")
        sys.exit(1)

    emby = EmbyClient(EMBY_URL, EMBY_API_KEY, SERVER_TYPE)
    if not emby.test_connection():
        log.error("Failed to connect to media server -- exiting")
        sys.exit(1)

    qbit = None
    if QBIT_URL:
        qbit = QBitClient(QBIT_URL, QBIT_USERNAME, QBIT_PASSWORD)
        qbit.test_connection()
    else:
        log.info("qBittorrent: not configured (skipping)")

    sab = None
    if SABNZBD_URL and SABNZBD_API_KEY:
        sab = SABnzbdClient(SABNZBD_URL, SABNZBD_API_KEY)
        sab.test_connection()
    else:
        log.info("SABnzbd: not configured (skipping)")

    disk = None
    if DISK_DEVICES:
        disk = DiskMonitor(DISK_DEVICES, DISK_PROC_PATH, DISK_SAMPLE_SECONDS)
        disk.test()
    else:
        log.info("Disk I/O monitoring: not configured (skipping)")

    log.info(f"Poll interval: {POLL_INTERVAL}s | "
             f"Stuck timeout: {STUCK_SCAN_TIMEOUT}s | "
             f"I/O threshold: {IO_THRESHOLD}%")
    log.info(f"Pausable tasks: {', '.join(PAUSABLE_TASKS)}")
    log.info("Guardian active -- monitoring started")

    state = GuardianState()
    is_running = True

    def handle_signal(signum, frame):
        nonlocal is_running
        log.info(f"Received signal {signum}, shutting down...")
        is_running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    cycle = 0
    while is_running:
        cycle += 1
        try:
            playback_active = emby.has_active_playback()
            running_tasks = emby.get_running_tasks(state.task_run_tracker)

            disk_busy = 0.0
            if disk:
                disk_busy = disk.get_utilization()

            task_names = [t.name for t in running_tasks]
            log.info(f"[Cycle {cycle}] Playback: "
                     f"{'YES' if playback_active else 'no'} | "
                     f"Tasks running: {len(running_tasks)} "
                     f"({', '.join(task_names) if task_names else 'none'}) | "
                     f"Disk I/O: {disk_busy:.0f}%")

            # Stuck scan detection
            for task in running_tasks:
                runtime = task.runtime_seconds
                if runtime > STUCK_SCAN_TIMEOUT:
                    log.warning(f"STUCK: '{task.name}' running for "
                                f"{runtime:.0f}s (threshold: "
                                f"{STUCK_SCAN_TIMEOUT}s)")
                    if not DRY_RUN:
                        try:
                            emby.stop_task(task.id)
                            log.info(f"Killed stuck task: '{task.name}'")
                        except Exception as e:
                            log.error(f"Failed to kill '{task.name}': {e}")
                    else:
                        log.info(f"[DRY RUN] Would kill stuck task: "
                                 f"'{task.name}'")
                    state.record_stuck_kill(task.name)

            # Playback protection
            if playback_active:
                for task in running_tasks:
                    if (task.id not in state.tasks_we_paused
                            and is_pausable_task(task.name)):
                        if not DRY_RUN:
                            try:
                                emby.stop_task(task.id)
                                log.info(f"Paused task: '{task.name}' "
                                         f"(playback active)")
                            except Exception as e:
                                log.error(f"Failed to pause "
                                          f"'{task.name}': {e}")
                        else:
                            log.info(f"[DRY RUN] Would pause: "
                                     f"'{task.name}'")
                        state.tasks_we_paused[task.id] = task.name
            else:
                if state.tasks_we_paused:
                    names = list(state.tasks_we_paused.values())
                    log.info(f"Playback ended. Clearing paused state for: "
                             f"{', '.join(names)}")
                    state.clear_paused_tasks()

            # Download throttling
            io_saturated = disk_busy > IO_THRESHOLD
            should_throttle = playback_active or io_saturated

            if should_throttle and not state.downloads_throttled:
                reasons = []
                if playback_active:
                    reasons.append("playback active")
                if io_saturated:
                    reasons.append(f"disk I/O {disk_busy:.0f}%")
                reason = ", ".join(reasons)
                log.info(f"Throttling downloads ({reason})")

                if qbit:
                    if not DRY_RUN:
                        try:
                            state.qbit_alt_was_on = qbit.is_alt_speed_enabled()
                            if not state.qbit_alt_was_on:
                                qbit.enable_alt_speed()
                        except Exception as e:
                            log.error(f"qBittorrent throttle failed: {e}")
                    else:
                        log.info("[DRY RUN] Would enable qBit alt speed")

                if sab:
                    if not DRY_RUN:
                        try:
                            state.sab_original_speed = sab.get_speed_limit()
                            sab.set_speed_limit(SABNZBD_THROTTLE_PCT)
                        except Exception as e:
                            log.error(f"SABnzbd throttle failed: {e}")
                    else:
                        log.info(f"[DRY RUN] Would set SABnzbd to "
                                 f"{SABNZBD_THROTTLE_PCT}%")

                state.downloads_throttled = True
                state.throttle_reason = reason

            elif not should_throttle and state.downloads_throttled:
                log.info(f"Restoring downloads (was: {state.throttle_reason})")

                if qbit:
                    if not DRY_RUN:
                        try:
                            if not state.qbit_alt_was_on:
                                qbit.disable_alt_speed()
                            else:
                                log.debug("qBit alt speed was already on "
                                          "-- leaving as-is")
                        except Exception as e:
                            log.error(f"qBittorrent restore failed: {e}")
                    else:
                        log.info("[DRY RUN] Would disable qBit alt speed")

                if sab:
                    if not DRY_RUN:
                        try:
                            sab.set_speed_limit(state.sab_original_speed)
                        except Exception as e:
                            log.error(f"SABnzbd restore failed: {e}")
                    else:
                        log.info(f"[DRY RUN] Would restore SABnzbd to "
                                 f"{state.sab_original_speed}%")

                state.downloads_throttled = False
                state.throttle_reason = ""

        except requests.exceptions.ConnectionError as e:
            log.error(f"Connection error (will retry): {e}")
        except requests.exceptions.Timeout as e:
            log.error(f"Request timeout (will retry): {e}")
        except Exception as e:
            log.error(f"Unexpected error in poll cycle: {e}", exc_info=True)

        for _ in range(POLL_INTERVAL):
            if not is_running:
                break
            time.sleep(1)

    log.info("Guardian stopped")


if __name__ == "__main__":
    main()
