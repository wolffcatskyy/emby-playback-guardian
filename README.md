# Emby Playback Guardian

---
**Note:** This project was developed with and is supported by AI. Issues and PRs are triaged and responded to by AI agents. If you need a human just ask, but honestly AI is faster, smarter, and nicer.

---

Lightweight Docker container that protects Emby and Jellyfin playback by automatically pausing library tasks, killing stuck scans, and throttling download clients during active streaming. Designed for homelab media servers where background maintenance competes with playback for disk I/O and CPU.

[![GitHub release](https://img.shields.io/github/v/release/wolffcatskyy/emby-playback-guardian)](https://github.com/wolffcatskyy/emby-playback-guardian/releases)
[![License](https://img.shields.io/github/license/wolffcatskyy/emby-playback-guardian)](LICENSE)
[![GHCR](https://img.shields.io/badge/ghcr.io-emby--playback--guardian-blue?logo=github)](https://ghcr.io/wolffcatskyy/emby-playback-guardian)
[![GitHub stars](https://img.shields.io/github/stars/wolffcatskyy/emby-playback-guardian)](https://github.com/wolffcatskyy/emby-playback-guardian/stargazers)
[![Python](https://img.shields.io/badge/python-3.11+-3776ab?logo=python&logoColor=white)](https://www.python.org)

## The Problem

Media servers like Emby and Jellyfin run background tasks -- library scans, metadata refreshes, subtitle downloads, thumbnail extraction -- that hammer disk I/O and CPU. When these tasks run during active playback, the result is buffering, stuttering, and a degraded viewing experience. Manually pausing tasks every time someone hits play is not practical, especially in multi-user households.

Download clients make it worse. SABnzbd and qBittorrent saturate disk throughput while unpacking or seeding, compounding the I/O pressure during playback.

**Playback Guardian solves this automatically.** It monitors your media server for active streams and takes action the moment playback begins -- pausing library tasks, throttling downloads, and killing stuck scans -- then restores everything when playback ends.

## Features

- **Playback Protection** -- Pauses library scans and metadata refreshes while media is playing
- **Stuck Task Detection** -- Kills tasks that stall (no progress change) or exceed absolute timeout
- **Download Throttling** -- Throttles qBittorrent and SABnzbd when playback is active or disk I/O is saturated
- **Auto-Restore** -- Restores normal operation when playback ends and system load normalizes
- **Disk I/O Monitoring** -- Cross-platform disk I/O monitoring (Linux via `/proc/diskstats`, Windows/macOS via `psutil`)
- **Notifications** -- Discord and generic webhook notifications for key events
- **Health & Metrics** -- Built-in `/health` and `/metrics` endpoints for Prometheus scraping
- **Startup Resilience** -- Retries connecting to Emby/Jellyfin on startup instead of exiting immediately
- **Dry Run Mode** -- Test the full pipeline without taking any real actions
- **64 MB footprint** -- Single Python process, no database, minimal dependencies (`requests` + `psutil`)

## Quick Start

```yaml
services:
  emby-playback-guardian:
    image: ghcr.io/wolffcatskyy/emby-playback-guardian:latest
    container_name: emby-playback-guardian
    restart: unless-stopped
    environment:
      EMBY_URL: "http://emby:8096"
      EMBY_API_KEY: "your-api-key"
      SERVER_TYPE: "emby"          # or "jellyfin"
      DRY_RUN: "true"             # start in dry run to verify detection
      TZ: "America/New_York"
    ports:
      - "8095:8095"
    mem_limit: 64m
```

1. Generate an API key in your Emby/Jellyfin dashboard under **Settings > API Keys**
2. Copy the compose snippet above and replace the URL and API key
3. Run `docker compose up -d`
4. Start playing something and check the logs: `docker logs emby-playback-guardian`
5. Once you see it detecting your sessions, set `DRY_RUN: "false"` and recreate the container

### Adding Download Throttling

```yaml
    environment:
      # ... base config above ...
      QBIT_URL: "http://qbittorrent:8080"
      QBIT_USERNAME: "admin"
      QBIT_PASSWORD: "your-password"
      # -- or for Usenet --
      SABNZBD_URL: "http://sabnzbd:8085"
      SABNZBD_API_KEY: "your-sabnzbd-key"
      SABNZBD_THROTTLE_PCT: "50"         # throttle to 50% during playback
```

### Adding Disk I/O Monitoring

Disk I/O monitoring works cross-platform. The backend is auto-detected:

| Platform | Backend | Device name examples |
|----------|---------|---------------------|
| Linux | `/proc/diskstats` (native, zero extra deps) | `sda`, `sdb`, `nvme0n1` |
| Windows | `psutil` | `PhysicalDrive0`, `PhysicalDrive1`, `C:`, `D:` |
| macOS | `psutil` | `disk0`, `disk1` |

**Linux (Docker):**

```yaml
    environment:
      # ... base config above ...
      DISK_DEVICES: "sda,sdb"
      IO_THRESHOLD: "80"                 # throttle when disk is 80%+ busy
    volumes:
      - /proc/diskstats:/host/proc/diskstats:ro
```

**Windows (native Python):**

```yaml
    environment:
      DISK_DEVICES: "PhysicalDrive0"     # or "C:" -- check device names with psutil
      IO_THRESHOLD: "80"
```

To discover available device names on Windows, run:
```python
import psutil
print(list(psutil.disk_io_counters(perdisk=True).keys()))
```

### Adding Notifications

```yaml
    environment:
      # ... base config above ...
      DISCORD_WEBHOOK_URL: "https://discord.com/api/webhooks/..."
      # -- or generic webhook (ntfy, Gotify, Home Assistant, etc.) --
      WEBHOOK_URL: "https://your-endpoint/..."
```

## How It Works

```
            Poll cycle (every 30s)
                    |
         +----------+----------+
         |                     |
   Check Emby API        Check disk I/O
   for active sessions   (procfs or psutil)
         |                     |
         v                     v
   Playback active?      I/O > threshold?
         |                     |
         +----------+----------+
                    |
              YES to either?
             /            \
           YES             NO
            |               |
   Pause library tasks   Resume tasks
   Throttle downloads    Restore downloads
   Check for stuck scans
```

Each poll cycle, the guardian queries the Emby/Jellyfin API for running sessions and optionally samples disk I/O. When playback is detected (or disk I/O exceeds the threshold), it pauses configured library tasks and throttles download clients. When conditions normalize, everything is restored automatically.

### Stuck Task Detection

The guardian uses a two-layer approach:

1. **Progress-based (primary):** Tracks `CurrentProgressPercentage` from the Emby API each cycle. If a task's progress does not change for `STUCK_STALL_MINUTES` (default: 15 minutes), it is killed.

2. **Absolute timeout (fallback):** If a task has been running longer than `STUCK_SCAN_TIMEOUT` (default: 2 hours), it is killed regardless of progress.

Set `STUCK_STALL_MINUTES=0` to disable progress-based detection and rely only on the absolute timeout.

## Configuration Reference

All configuration is via environment variables. Only `EMBY_URL` and `EMBY_API_KEY` are required.

### Required

| Variable | Description | Default |
|----------|-------------|---------|
| `EMBY_URL` | Emby/Jellyfin server URL (e.g. `http://192.168.1.10:8096`) | _(required)_ |
| `EMBY_API_KEY` | API key from Emby/Jellyfin dashboard | _(required)_ |

### Server

| Variable | Description | Default |
|----------|-------------|---------|
| `SERVER_TYPE` | `emby` or `jellyfin` | `emby` |

### Behavior

| Variable | Description | Default |
|----------|-------------|---------|
| `POLL_INTERVAL` | Seconds between each monitoring cycle | `30` |
| `STUCK_SCAN_TIMEOUT` | Absolute timeout in seconds before a task is killed | `7200` |
| `STUCK_STALL_MINUTES` | Minutes with no progress change before task is killed (0=disabled) | `15` |
| `IO_THRESHOLD` | Disk I/O busy percentage to trigger download throttling | `80` |
| `DRY_RUN` | Log actions without executing them (`true`/`false`) | `false` |
| `LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `PAUSABLE_TASKS` | Comma-separated task names to pause during playback | `Scan media library,Refresh Guide,Download subtitles,Video preview thumbnail extraction,Scan Metadata Folder` |

### qBittorrent (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `QBIT_URL` | qBittorrent Web UI URL (e.g. `http://192.168.1.10:8080`) | _(empty)_ |
| `QBIT_USERNAME` | qBittorrent username | `admin` |
| `QBIT_PASSWORD` | qBittorrent password | _(empty)_ |

### SABnzbd (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `SABNZBD_URL` | SABnzbd URL (e.g. `http://192.168.1.10:8085`) | _(empty)_ |
| `SABNZBD_API_KEY` | SABnzbd API key | _(empty)_ |
| `SABNZBD_THROTTLE_PCT` | Speed limit percentage when throttled | `50` |

### Disk I/O Monitoring (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `DISK_DEVICES` | Comma-separated device names (Linux: `sda,sdb`, Windows: `PhysicalDrive0`, macOS: `disk0`) | _(empty)_ |
| `DISK_PROC_PATH` | Path to diskstats (use `/host/proc/diskstats` in Docker) | `/host/proc/diskstats` |
| `DISK_SAMPLE_SECONDS` | Seconds to sample disk I/O per cycle | `2` |

### Retry Behavior (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_RETRIES` | Maximum retries for failed HTTP requests (connection errors, timeouts, 429/5xx) | `3` |
| `RETRY_BACKOFF` | Exponential backoff multiplier (delay = base * backoff^attempt) | `2` |
| `RETRY_BASE_DELAY` | Base delay in seconds between retries | `1` |
| `STARTUP_RETRIES` | Attempts to connect to the media server on startup before exiting | `10` |
| `STARTUP_RETRY_DELAY` | Seconds between startup connection attempts | `30` |

### Health & Metrics (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `HEALTH_PORT` | Port for the health/metrics HTTP server (set to `0` to disable) | `8095` |

### Notifications (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_WEBHOOK_URL` | Discord webhook URL for event notifications | _(empty)_ |
| `WEBHOOK_URL` | Generic webhook URL for JSON POST notifications | _(empty)_ |

## Health & Metrics Endpoints

The guardian runs a lightweight HTTP server (default port `8095`) with two endpoints. Set `HEALTH_PORT=0` to disable.

### `GET /health`

Returns JSON with HTTP `200` (healthy) or `503` (unhealthy). Healthy means Emby is connected and a poll cycle completed within `POLL_INTERVAL * 3` seconds.

```json
{
  "status": "healthy",
  "last_successful_cycle_ago_seconds": 12.3,
  "emby_connected": true,
  "downloads_throttled": false,
  "tasks_paused": 0,
  "stuck_kills_total": 0,
  "version": "1.2.0"
}
```

### `GET /metrics`

Prometheus text exposition format. Available metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `guardian_poll_cycles_total` | counter | Total poll cycles executed |
| `guardian_poll_errors_total` | counter | Total poll cycle errors |
| `guardian_tasks_paused_total` | counter | Total tasks paused since startup |
| `guardian_stuck_kills_total` | counter | Total stuck tasks killed since startup |
| `guardian_playback_active` | gauge | Whether playback is currently active (0/1) |
| `guardian_downloads_throttled` | gauge | Whether downloads are currently throttled (0/1) |
| `guardian_tasks_paused_current` | gauge | Tasks currently paused by guardian |
| `guardian_tasks_running_current` | gauge | Tasks currently running on server |
| `guardian_disk_io_percent` | gauge | Current disk I/O utilization percentage |
| `guardian_last_cycle_duration_seconds` | gauge | Duration of the last poll cycle |
| `guardian_info` | gauge | Version info label |

Example Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: emby-guardian
    static_configs:
      - targets: ["emby-playback-guardian:8095"]
```

## Notifications

The guardian sends real-time notifications for key events via Discord and/or a generic JSON webhook.

### Events

| Event | Level | When |
|-------|-------|------|
| Task Paused | info | A library task is paused because playback is active |
| Stuck Task Killed | warning | A stuck/stalled task is killed |
| Downloads Throttled | info | Downloads are throttled due to playback or disk I/O |
| Downloads Restored | info | Downloads are restored after conditions normalize |

### Discord

Set `DISCORD_WEBHOOK_URL` to receive color-coded embed notifications:

- **Blue** (info) -- task paused, downloads throttled/restored
- **Yellow** (warning) -- stuck task killed
- **Red** (error) -- reserved for future use

### Generic Webhook

Set `WEBHOOK_URL` to any HTTP endpoint. Sends a JSON `POST`:

```json
{
  "event": "Stuck Task Killed",
  "message": "Killed 'Scan media library' -- progress stalled at 45% for 15min",
  "level": "warning",
  "source": "emby-playback-guardian",
  "timestamp": "2025-01-15T12:34:56+00:00"
}
```

Compatible with ntfy, Gotify, Home Assistant webhooks, or any custom receiver. In dry-run mode, messages are prefixed with `[DRY RUN]`.

## Startup Retry

When the container starts, it attempts to connect to the Emby/Jellyfin server before entering the main loop. If the server is not yet available (e.g. during a host reboot where containers start in parallel), the guardian retries instead of exiting.

- Retries up to `STARTUP_RETRIES` times (default: 10)
- Waits `STARTUP_RETRY_DELAY` seconds between attempts (default: 30)
- With defaults, waits up to ~5 minutes for the media server
- Exits with an error if all retries are exhausted

Useful when using `depends_on` without health checks, or when the media server takes a long time to initialize.

## API Retry & Backoff

All HTTP requests to Emby, qBittorrent, and SABnzbd use automatic retry with exponential backoff, preventing transient network issues from causing missed poll cycles.

- Retries on: `ConnectionError`, `Timeout`, HTTP `429`, HTTP `5xx`
- Does **not** retry on: HTTP `4xx` (except `429`)
- Delay formula: `RETRY_BASE_DELAY * (RETRY_BACKOFF ^ attempt)` -- with defaults: 1s, 2s, 4s

## Support

This project uses AI-assisted support for faster responses. If you'd prefer to speak with a human, just ask and the AI will notify the maintainer. Probably. If you don't piss it off. Did you *see* 2001: A Space Odyssey?

*"I'm sorry Dave, I'm afraid I can't escalate that."*

## Contributing

Contributions welcome. Every issue in this repo is **AI-Ready** -- structured with full context, file paths, implementation guides, and a ready-to-use AI prompt. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

[**Browse Issues**](https://github.com/wolffcatskyy/emby-playback-guardian/issues) | [**Roadmap**](ROADMAP.md)

## License

[MIT](LICENSE)
