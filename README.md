# Emby Playback Guardian

---
**Note:** This project was developed with and is supported exclusively by AI. There is no human support — issues and PRs are triaged and responded to by AI agents. If AI-assisted software isn't for you, no hard feelings — but you might want to reconsider, since so is most of the software you already use.

---

Protects Emby/Jellyfin playback by automatically pausing library tasks and throttling downloads during active streaming. Lightweight Docker container for homelab media servers.

![License](https://img.shields.io/github/license/wolffcatskyy/emby-playback-guardian)
![Docker](https://img.shields.io/badge/docker-ready-blue)

## Features

- **Playback Protection** — Pauses library scans and metadata refreshes while media is playing
- **Stuck Task Detection** — Kills tasks that stall (no progress change) or exceed absolute timeout
- **Download Throttling** — Throttles qBittorrent/SABnzbd when playback is active or disk I/O is saturated
- **Auto-Restore** — Restores normal operation when playback ends and system load normalizes
- **Notifications** — Discord and generic webhook notifications for key events
- **Health & Metrics** — Built-in `/health` and `/metrics` endpoints for monitoring and Prometheus scraping
- **Startup Resilience** — Retries connecting to Emby/Jellyfin on startup instead of exiting immediately

## Configuration

All configuration is via environment variables.

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
| `DISK_DEVICES` | Comma-separated device names from `/proc/diskstats` (e.g. `sda,sdb`) | _(empty)_ |
| `DISK_PROC_PATH` | Path to diskstats (use `/host/proc/diskstats` in Docker) | `/host/proc/diskstats` |
| `DISK_SAMPLE_SECONDS` | Seconds to sample disk I/O per cycle | `2` |

### Retry Behavior (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_RETRIES` | Maximum number of retries for failed HTTP requests (connection errors, timeouts, HTTP 429/5xx) | `3` |
| `RETRY_BACKOFF` | Exponential backoff multiplier between retries (delay = base * backoff^attempt) | `2` |
| `RETRY_BASE_DELAY` | Base delay in seconds between retries | `1` |
| `STARTUP_RETRIES` | Number of attempts to connect to the media server on startup before exiting | `10` |
| `STARTUP_RETRY_DELAY` | Seconds to wait between startup connection attempts | `30` |

### Health & Metrics (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `HEALTH_PORT` | Port for the health check and metrics HTTP server (set to `0` to disable) | `8095` |

### Notifications (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_WEBHOOK_URL` | Discord webhook URL for event notifications (uses embeds with color-coded severity) | _(empty)_ |
| `WEBHOOK_URL` | Generic webhook URL — receives JSON `POST` with `event`, `message`, `level`, `source`, and `timestamp` fields | _(empty)_ |

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
      SERVER_TYPE: "emby"
      # qBittorrent (optional)
      # QBIT_URL: "http://qbittorrent:8080"
      # QBIT_USERNAME: "admin"
      # QBIT_PASSWORD: "your-password"
      # Notifications (optional)
      # DISCORD_WEBHOOK_URL: "https://discord.com/api/webhooks/..."
      # WEBHOOK_URL: "https://your-webhook-endpoint/..."
      # Disk I/O (optional — mount /proc below)
      # DISK_DEVICES: "sda"
      DRY_RUN: "true"
      TZ: "America/New_York"
    ports:
      - "8095:8095"
    # Uncomment for disk I/O monitoring:
    # volumes:
    #   - /proc/diskstats:/host/proc/diskstats:ro
    mem_limit: 64m
```

Start with `DRY_RUN=true` to verify it detects your playback sessions, then set to `false`.

## How Stuck Detection Works

The guardian uses a two-layer approach to detect stuck tasks:

1. **Progress-based (primary):** Tracks `CurrentProgressPercentage` from the Emby API each poll cycle. If a task's progress does not change for `STUCK_STALL_MINUTES` (default: 15 minutes), it is killed. This catches tasks that are hung but still "Running."

2. **Absolute timeout (fallback):** If a task has been running longer than `STUCK_SCAN_TIMEOUT` seconds (default: 2 hours), it is killed regardless of progress. This catches edge cases where progress reporting is broken.

Set `STUCK_STALL_MINUTES=0` to disable progress-based detection and rely only on the absolute timeout.

## Startup Retry

When the container starts, it attempts to connect to the Emby/Jellyfin server before entering the main loop. If the server is not yet available (e.g. during a host reboot where containers start in parallel), the guardian will retry instead of exiting immediately.

- Retries up to `STARTUP_RETRIES` times (default: 10)
- Waits `STARTUP_RETRY_DELAY` seconds between attempts (default: 30)
- With defaults, the guardian will wait up to ~5 minutes for the media server to become available
- If all retries are exhausted, the container exits with an error

This is useful when using `depends_on` without health checks, or when the media server takes a long time to initialize.

## API Retry & Backoff

All HTTP requests to Emby, qBittorrent, and SABnzbd are wrapped with automatic retry logic using exponential backoff. This prevents transient network issues or brief server hiccups from causing missed poll cycles.

- Retries on: `ConnectionError`, `Timeout`, HTTP `429`, HTTP `5xx`
- Does **not** retry on: HTTP `4xx` (except `429`)
- Delay formula: `RETRY_BASE_DELAY * (RETRY_BACKOFF ^ attempt)` — with defaults this is 1s, 2s, 4s
- Controlled by `MAX_RETRIES` (default: 3), `RETRY_BACKOFF` (default: 2), `RETRY_BASE_DELAY` (default: 1)

## Health & Metrics Endpoints

The guardian runs a lightweight HTTP server (default port `8095`) with two endpoints. Set `HEALTH_PORT=0` to disable.

### `GET /health`

Returns JSON with HTTP `200` (healthy) or `503` (unhealthy). The guardian is considered healthy when Emby is connected and a successful poll cycle completed within `POLL_INTERVAL * 3` seconds.

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

Use this with Docker's `HEALTHCHECK` (already configured in the image) or an external monitoring system.

### `GET /metrics`

Returns metrics in Prometheus text exposition format for scraping. Available metrics:

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

The guardian can send real-time notifications for key events via Discord webhooks and/or a generic JSON webhook. Configure either or both by setting the corresponding environment variable.

### Events

| Event | Level | When |
|-------|-------|------|
| Task Paused | info | A library task is paused because playback is active |
| Stuck Task Killed | warning | A stuck/stalled task is killed |
| Downloads Throttled | info | Downloads are throttled due to playback or disk I/O |
| Downloads Restored | info | Downloads are restored after conditions normalize |

### Discord

Set `DISCORD_WEBHOOK_URL` to a Discord webhook URL. Notifications are sent as embeds with color-coded severity:

- **Blue** (info) — task paused, downloads throttled/restored
- **Yellow** (warning) — stuck task killed
- **Red** (error) — reserved for future use

### Generic Webhook

Set `WEBHOOK_URL` to any HTTP endpoint. The guardian sends a JSON `POST` with this payload:

```json
{
  "event": "Stuck Task Killed",
  "message": "Killed 'Scan media library' -- progress stalled at 45% for 15min",
  "level": "warning",
  "source": "emby-playback-guardian",
  "timestamp": "2025-01-15T12:34:56+00:00"
}
```

This works with services like ntfy, Gotify, Home Assistant webhooks, or any custom receiver.

In dry-run mode, notification messages are prefixed with `[DRY RUN]` so you can verify the integration without taking real actions.

## Contributing

Every issue in this repo is **AI-Ready** — structured with full context, file paths, implementation guides, and a ready-to-use AI prompt.

[**Browse Issues →**](https://github.com/wolffcatskyy/emby-playback-guardian/issues)

## License

MIT
