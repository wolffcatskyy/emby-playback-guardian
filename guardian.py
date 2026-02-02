#!/usr/bin/env python3
"""
Emby Playback Guardian -- Protects playback by pausing tasks and throttling downloads.

Monitors Emby/Jellyfin media servers and automatically:
  - Pauses library scans and metadata refreshes during active playback
  - Detects and kills stuck scheduled tasks
  - Throttles qBittorrent/SABnzbd when disk I/O is saturated
  - Restores everything when playback ends and load normalizes

https://github.com/wolffcatskyy/emby-playback-guardian
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

__version__ = "1.2.0"


# --- Configuration ---------------------------------------------------------------

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


# Required
EMBY_URL = env("EMBY_URL", "")
EMBY_API_KEY = env("EMBY_API_KEY", "")
SERVER_TYPE = env("SERVER_TYPE", "emby").lower()

# qBittorrent (optional)
QBIT_URL = env("QBIT_URL", "")
QBIT_USERNAME = env("QBIT_USERNAME", "admin")
QBIT_PASSWORD = env("QBIT_PASSWORD", "")

# SABnzbd (optional)
SABNZBD_URL = env("SABNZBD_URL", "")
SABNZBD_API_KEY = env("SABNZBD_API_KEY", "")
SABNZBD_THROTTLE_PCT = env_int("SABNZBD_THROTTLE_PCT", 50)

# Disk I/O (optional)
DISK_DEVICES = [d.strip() for d in env("DISK_DEVICES", "").split(",") if d.strip()]
DISK_PROC_PATH = env("DISK_PROC_PATH", "/host/proc/diskstats")
DISK_SAMPLE_SECONDS = env_int("DISK_SAMPLE_SECONDS", 2)

# Behavior
POLL_INTERVAL = env_int("POLL_INTERVAL", 30)
STUCK_SCAN_TIMEOUT = env_int("STUCK_SCAN_TIMEOUT", 7200)
STUCK_STALL_MINUTES = env_int("STUCK_STALL_MINUTES", 15)
IO_THRESHOLD = env_int("IO_THRESHOLD", 80)
DRY_RUN = env_bool("DRY_RUN", False)
LOG_LEVEL = env("LOG_LEVEL", "INFO").upper()

# Tasks to protect playback from (case-insensitive substring match)
PAUSABLE_TASKS = [t.strip() for t in env(
    "PAUSABLE_TASKS",
    "Scan media library,Refresh Guide,Download subtitles,"
    "Video preview thumbnail extraction,Scan Metadata Folder"
).split(",") if t.strip()]

# Retry behavior
MAX_RETRIES = env_int("MAX_RETRIES", 3)
RETRY_BACKOFF = env_int("RETRY_BACKOFF", 2)
RETRY_BASE_DELAY = env_int("RETRY_BASE_DELAY", 1)

# Startup retry (wait for Emby to become available)
STARTUP_RETRIES = env_int("STARTUP_RETRIES", 10)
STARTUP_RETRY_DELAY = env_int("STARTUP_RETRY_DELAY", 30)

# Health check / metrics
HEALTH_PORT = env_int("HEALTH_PORT", 8095)

# Notifications (optional)
DISCORD_WEBHOOK_URL = env("DISCORD_WEBHOOK_URL", "")
WEBHOOK_URL = env("WEBHOOK_URL", "")


# --- Logging ---------------------------------------------------------------------

def setup_logging():
    """Configure structured logging."""
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = "[%(asctime)s] [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S",
                        stream=sys.stdout)
    return logging.getLogger("guardian")


log = setup_logging()


# --- Retry Helper ----------------------------------------------------------------

def retry_request(func, *args, max_retries=None, **kwargs):
    """Execute an HTTP request function with exponential backoff retry.

    Retries on: ConnectionError, Timeout, HTTP 429, HTTP 5xx.
    Does NOT retry on: HTTP 4xx (except 429).
    """
    retries = max_retries if max_retries is not None else MAX_RETRIES
    last_exception = None

    for attempt in range(retries + 1):
        try:
            resp = func(*args, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < retries:
                    delay = RETRY_BASE_DELAY * (RETRY_BACKOFF ** attempt)
                    log.debug(f"HTTP {resp.status_code} -- retrying in {delay}s "
                              f"(attempt {attempt + 1}/{retries})")
                    time.sleep(delay)
                    continue
            return resp
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_exception = e
            if attempt < retries:
                delay = RETRY_BASE_DELAY * (RETRY_BACKOFF ** attempt)
                log.debug(f"{type(e).__name__} -- retrying in {delay}s "
                          f"(attempt {attempt + 1}/{retries})")
                time.sleep(delay)
            else:
                log.warning(f"Request failed after {retries} retries: {e}")
                raise

    if last_exception:
        raise last_exception
    resp.raise_for_status()
    return resp


# --- Data Types ------------------------------------------------------------------

@dataclass
class TaskInfo:
    """Represents an Emby scheduled task."""
    id: str
    name: str
    state: str
    progress: float = 0.0
    first_seen_running: float = 0.0

    @property
    def runtime_seconds(self):
        if self.first_seen_running > 0:
            return time.time() - self.first_seen_running
        return 0


@dataclass
class GuardianState:
    """Tracks what the guardian has done so it can undo correctly."""
    tasks_we_paused: dict = field(default_factory=dict)
    downloads_throttled: bool = False
    qbit_alt_was_on: bool = False
    sab_original_speed: int = 100
    throttle_reason: str = ""
    task_run_tracker: dict = field(default_factory=dict)
    task_progress_tracker: dict = field(default_factory=dict)
    stuck_kills: list = field(default_factory=list)
    last_successful_cycle: float = 0.0
    last_cycle_error: str = ""
    emby_connected: bool = False

    def clear_paused_tasks(self):
        self.tasks_we_paused.clear()

    def update_progress(self, task_id, progress):
        """Track progress changes. Returns seconds since last progress change."""
        now = time.time()
        if task_id in self.task_progress_tracker:
            last_progress, last_change = self.task_progress_tracker[task_id]
            if progress != last_progress:
                self.task_progress_tracker[task_id] = (progress, now)
                return 0
            else:
                return now - last_change
        else:
            self.task_progress_tracker[task_id] = (progress, now)
            return 0

    def clean_progress_tracker(self, active_ids):
        """Remove entries for tasks no longer running."""
        for tid in list(self.task_progress_tracker.keys()):
            if tid not in active_ids:
                del self.task_progress_tracker[tid]

    def record_stuck_kill(self, task_name, reason=""):
        self.stuck_kills.append({
            "task": task_name,
            "reason": reason,
            "killed_at": datetime.now(timezone.utc).isoformat()
        })


@dataclass
class MetricsCollector:
    """Collects Prometheus-compatible metrics from guardian state."""
    poll_cycles_total: int = 0
    poll_errors_total: int = 0
    tasks_paused_total: int = 0
    stuck_kills_total: int = 0
    last_cycle_duration: float = 0.0
    playback_active: int = 0
    downloads_throttled: int = 0
    tasks_currently_paused: int = 0
    tasks_currently_running: int = 0
    disk_io_percent: float = 0.0

    def to_prometheus(self):
        """Render metrics in Prometheus text exposition format."""
        lines = []

        def metric(name, help_text, mtype, value):
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {mtype}")
            lines.append(f"{name} {value}")

        metric("guardian_poll_cycles_total",
               "Total number of poll cycles executed", "counter",
               self.poll_cycles_total)
        metric("guardian_poll_errors_total",
               "Total number of poll cycle errors", "counter",
               self.poll_errors_total)
        metric("guardian_tasks_paused_total",
               "Total number of tasks paused since startup", "counter",
               self.tasks_paused_total)
        metric("guardian_stuck_kills_total",
               "Total number of stuck tasks killed since startup", "counter",
               self.stuck_kills_total)
        metric("guardian_playback_active",
               "Whether playback is currently active (0 or 1)", "gauge",
               self.playback_active)
        metric("guardian_downloads_throttled",
               "Whether downloads are currently throttled (0 or 1)", "gauge",
               self.downloads_throttled)
        metric("guardian_tasks_paused_current",
               "Number of tasks currently paused by guardian", "gauge",
               self.tasks_currently_paused)
        metric("guardian_tasks_running_current",
               "Number of tasks currently running on server", "gauge",
               self.tasks_currently_running)
        metric("guardian_disk_io_percent",
               "Current disk I/O utilization percentage", "gauge",
               round(self.disk_io_percent, 1))
        metric("guardian_last_cycle_duration_seconds",
               "Duration of the last poll cycle in seconds", "gauge",
               round(self.last_cycle_duration, 3))
        metric("guardian_info",
               "Guardian version info", "gauge",
               '1{version="' + __version__ + '"}')

        return "\n".join(lines) + "\n"


# --- Emby/Jellyfin Client -------------------------------------------------------

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
        resp = retry_request(self.session.get, self._url(path), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, timeout=10):
        resp = retry_request(self.session.post, self._url(path), timeout=timeout)
        resp.raise_for_status()
        return resp

    def _delete(self, path, timeout=10):
        resp = retry_request(self.session.delete, self._url(path), timeout=timeout)
        resp.raise_for_status()
        return resp

    def get_active_sessions(self):
        """Return list of sessions with active playback."""
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
        """Check if anyone is currently playing media."""
        sessions = self.get_active_sessions()
        if sessions:
            for s in sessions:
                log.info(f"  Active: {s['user']} -> '{s['item']}' "
                         f"({s['play_method']}) on {s['device']}")
        return len(sessions) > 0

    def get_scheduled_tasks(self):
        """Return all scheduled tasks."""
        return self._get("/ScheduledTasks")

    def get_running_tasks(self, state_tracker):
        """Return list of TaskInfo for currently running tasks."""
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
                    id=tid,
                    name=t["Name"],
                    state=t["State"],
                    progress=t.get("CurrentProgressPercentage", 0) or 0,
                    first_seen_running=first_seen,
                ))

        for tid in list(state_tracker.keys()):
            if tid not in active_ids:
                del state_tracker[tid]

        return running

    def stop_task(self, task_id):
        """Stop a running scheduled task."""
        self._delete(f"/ScheduledTasks/Running/{task_id}")

    def test_connection(self):
        """Verify API connectivity."""
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


# --- qBittorrent Client ----------------------------------------------------------

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
        resp = retry_request(
            self.session.request, method, f"{self.base}{endpoint}", **kwargs
        )
        if resp.status_code == 403:
            self._login()
            resp = retry_request(
                self.session.request, method, f"{self.base}{endpoint}", **kwargs
            )
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


# --- SABnzbd Client --------------------------------------------------------------

class SABnzbdClient:
    """SABnzbd API client (stateless, uses apikey in query params)."""

    def __init__(self, url, api_key):
        self.base = url.rstrip("/")
        self.api_key = api_key

    def _api(self, mode, **params):
        params.update({"mode": mode, "apikey": self.api_key, "output": "json"})
        resp = retry_request(
            requests.get, f"{self.base}/api", params=params, timeout=10
        )
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


# --- Notification Client ---------------------------------------------------------

class NotificationClient:
    """Sends notifications via Discord webhook and/or generic webhook."""

    def __init__(self, discord_url="", webhook_url="", dry_run=False):
        self.discord_url = discord_url
        self.webhook_url = webhook_url
        self.dry_run = dry_run

    @property
    def enabled(self):
        return bool(self.discord_url or self.webhook_url)

    def notify(self, event, message, level="info"):
        """Send a notification. Non-blocking -- errors are logged, not raised."""
        if not self.enabled:
            return
        prefix = "[DRY RUN] " if self.dry_run else ""
        full_message = f"{prefix}{message}"
        if self.discord_url:
            self._send_discord(event, full_message, level)
        if self.webhook_url:
            self._send_webhook(event, full_message, level)

    def _send_discord(self, event, message, level):
        """Post to Discord webhook using embeds."""
        colors = {"info": 3447003, "warning": 16776960, "error": 15158332}
        payload = {
            "embeds": [{
                "title": f"Guardian: {event}",
                "description": message,
                "color": colors.get(level, 3447003),
                "footer": {"text": "Emby Playback Guardian"}
            }]
        }
        try:
            resp = requests.post(self.discord_url, json=payload, timeout=5)
            resp.raise_for_status()
        except Exception as e:
            log.warning(f"Discord notification failed: {e}")

    def _send_webhook(self, event, message, level):
        """POST JSON to generic webhook URL."""
        payload = {
            "event": event,
            "message": message,
            "level": level,
            "source": "emby-playback-guardian",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=5)
            resp.raise_for_status()
        except Exception as e:
            log.warning(f"Webhook notification failed: {e}")


# --- Disk I/O Monitor ------------------------------------------------------------

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
            log.warning(f"Disk stats not found at {self.proc_path} "
                        "-- disk monitoring disabled")
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
            log.warning("Disk monitoring: no configured devices found "
                        f"in {self.proc_path}")
            return False


# --- Health Check & Metrics Server -----------------------------------------------

class HealthMetricsHandler(BaseHTTPRequestHandler):
    """Serves /health as JSON and /metrics in Prometheus text format."""
    state = None
    metrics = None

    def do_GET(self):
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_health(self):
        now = time.time()
        last = self.state.last_successful_cycle if self.state else 0
        age = now - last if last > 0 else float("inf")
        max_age = POLL_INTERVAL * 3
        healthy = age < max_age and self.state and self.state.emby_connected
        status = 200 if healthy else 503
        body = {
            "status": "healthy" if healthy else "unhealthy",
            "last_successful_cycle_ago_seconds": round(age, 1),
            "emby_connected": self.state.emby_connected if self.state else False,
            "downloads_throttled": self.state.downloads_throttled if self.state else False,
            "tasks_paused": len(self.state.tasks_we_paused) if self.state else 0,
            "stuck_kills_total": len(self.state.stuck_kills) if self.state else 0,
            "version": __version__,
        }
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def _handle_metrics(self):
        body = self.metrics.to_prometheus().encode() if self.metrics else b""
        self.send_response(200)
        self.send_header("Content-Type",
                         "text/plain; version=0.0.4; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def start_health_metrics_server(port, state, metrics):
    """Start health check and metrics HTTP server in a daemon thread."""
    HealthMetricsHandler.state = state
    HealthMetricsHandler.metrics = metrics
    server = HTTPServer(("0.0.0.0", port), HealthMetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"Health/metrics endpoint: http://0.0.0.0:{port}/health "
             f"and http://0.0.0.0:{port}/metrics")
    return server


# --- Task Matching ---------------------------------------------------------------

def is_pausable_task(task_name):
    name_lower = task_name.lower()
    return any(p.lower() in name_lower for p in PAUSABLE_TASKS)


# --- Main Loop -------------------------------------------------------------------

def main():
    log.info(f"Emby Playback Guardian v{__version__}")
    if DRY_RUN:
        log.info("*** DRY RUN MODE -- no actions will be taken ***")

    if not EMBY_URL or not EMBY_API_KEY:
        log.error("EMBY_URL and EMBY_API_KEY are required")
        sys.exit(1)

    emby = EmbyClient(EMBY_URL, EMBY_API_KEY, SERVER_TYPE)

    # Startup retry: wait for Emby to become available instead of exiting
    connected = False
    for attempt in range(1, STARTUP_RETRIES + 1):
        if emby.test_connection():
            connected = True
            break
        if attempt < STARTUP_RETRIES:
            log.warning(f"Startup: Emby not available, retrying in "
                        f"{STARTUP_RETRY_DELAY}s "
                        f"(attempt {attempt}/{STARTUP_RETRIES})")
            time.sleep(STARTUP_RETRY_DELAY)
    if not connected:
        log.error(f"Failed to connect to media server after "
                  f"{STARTUP_RETRIES} attempts -- exiting")
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

    notifier = None
    if DISCORD_WEBHOOK_URL or WEBHOOK_URL:
        notifier = NotificationClient(DISCORD_WEBHOOK_URL, WEBHOOK_URL, DRY_RUN)
        log.info(f"Notifications: Discord={'yes' if DISCORD_WEBHOOK_URL else 'no'}, "
                 f"Webhook={'yes' if WEBHOOK_URL else 'no'}")
    else:
        log.info("Notifications: not configured (skipping)")

    log.info(f"Poll interval: {POLL_INTERVAL}s | "
             f"Stuck timeout: {STUCK_SCAN_TIMEOUT}s | "
             f"Stall detection: {STUCK_STALL_MINUTES}min | "
             f"I/O threshold: {IO_THRESHOLD}%")
    log.info(f"Retry config: {MAX_RETRIES} retries, "
             f"backoff={RETRY_BACKOFF}x, base_delay={RETRY_BASE_DELAY}s")
    log.info(f"Pausable tasks: {', '.join(PAUSABLE_TASKS)}")
    log.info("Guardian active -- monitoring started")

    state = GuardianState()
    state.emby_connected = True
    metrics = MetricsCollector()

    if HEALTH_PORT:
        start_health_metrics_server(HEALTH_PORT, state, metrics)
    else:
        log.info("Health/metrics: disabled (HEALTH_PORT=0)")

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        log.info(f"Received signal {signum}, shutting down...")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    cycle = 0
    while running:
        cycle += 1
        cycle_start = time.time()
        try:
            playback_active = emby.has_active_playback()
            running_tasks = emby.get_running_tasks(state.task_run_tracker)

            disk_busy = 0.0
            if disk:
                disk_busy = disk.get_utilization()

            metrics.playback_active = 1 if playback_active else 0
            metrics.tasks_currently_running = len(running_tasks)
            metrics.disk_io_percent = disk_busy

            if running_tasks:
                task_descs = [f"{t.name} ({t.progress:.0f}%)" for t in running_tasks]
                task_str = ", ".join(task_descs)
            else:
                task_str = "none"
            log.info(f"[Cycle {cycle}] Playback: "
                     f"{'YES' if playback_active else 'no'} | "
                     f"Tasks running: {len(running_tasks)} "
                     f"({task_str}) | "
                     f"Disk I/O: {disk_busy:.0f}%")

            active_task_ids = {t.id for t in running_tasks}
            state.clean_progress_tracker(active_task_ids)

            for task in running_tasks:
                runtime = task.runtime_seconds
                stall_secs = state.update_progress(task.id, task.progress)
                stall_limit = STUCK_STALL_MINUTES * 60
                is_stalled = stall_secs >= stall_limit and runtime > stall_limit
                is_absolute_timeout = runtime > STUCK_SCAN_TIMEOUT
                kill_reason = ""

                if is_stalled:
                    kill_reason = (f"progress stalled at {task.progress:.0f}% "
                                   f"for {stall_secs / 60:.0f}min")
                elif is_absolute_timeout:
                    kill_reason = (f"absolute timeout {runtime:.0f}s "
                                   f"> {STUCK_SCAN_TIMEOUT}s")

                if kill_reason:
                    log.warning(f"STUCK: '{task.name}' -- {kill_reason}")
                    if not DRY_RUN:
                        try:
                            emby.stop_task(task.id)
                            log.info(f"Killed stuck task: '{task.name}'")
                        except Exception as e:
                            log.error(f"Failed to kill '{task.name}': {e}")
                    else:
                        log.info(f"[DRY RUN] Would kill stuck task: "
                                 f"'{task.name}'")
                    state.record_stuck_kill(task.name, kill_reason)
                    metrics.stuck_kills_total += 1
                    if notifier:
                        notifier.notify("Stuck Task Killed",
                                        f"Killed '{task.name}' -- {kill_reason}",
                                        level="warning")
                elif stall_secs > 60:
                    log.debug(f"Task '{task.name}' at {task.progress:.0f}% "
                              f"-- no progress for {stall_secs / 60:.1f}min")

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
                        metrics.tasks_paused_total += 1
                        if notifier:
                            notifier.notify("Task Paused",
                                            f"Paused '{task.name}' -- playback active")
            else:
                if state.tasks_we_paused:
                    names = list(state.tasks_we_paused.values())
                    log.info(f"Playback ended. Clearing paused state for: "
                             f"{', '.join(names)}")
                    state.clear_paused_tasks()

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
                if notifier:
                    notifier.notify("Downloads Throttled",
                                    f"Throttling downloads ({reason})")

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

                if notifier:
                    notifier.notify("Downloads Restored",
                                    f"Restored downloads (was: {state.throttle_reason})")
                state.downloads_throttled = False
                state.throttle_reason = ""

            metrics.downloads_throttled = 1 if state.downloads_throttled else 0
            metrics.tasks_currently_paused = len(state.tasks_we_paused)

            state.last_successful_cycle = time.time()
            state.emby_connected = True
            state.last_cycle_error = ""
            metrics.poll_cycles_total += 1
            metrics.last_cycle_duration = time.time() - cycle_start

        except requests.exceptions.ConnectionError as e:
            log.error(f"Connection error (will retry): {e}")
            state.emby_connected = False
            state.last_cycle_error = str(e)
            metrics.poll_errors_total += 1
        except requests.exceptions.Timeout as e:
            log.error(f"Request timeout (will retry): {e}")
            state.last_cycle_error = str(e)
            metrics.poll_errors_total += 1
        except Exception as e:
            log.error(f"Unexpected error in poll cycle: {e}", exc_info=True)
            state.last_cycle_error = str(e)
            metrics.poll_errors_total += 1

        for _ in range(POLL_INTERVAL):
            if not running:
                break
            time.sleep(1)

    log.info("Guardian stopped")


if __name__ == "__main__":
    main()
