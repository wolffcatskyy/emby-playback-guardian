# Emby Playback Guardian

Protects Emby/Jellyfin playback by automatically pausing library tasks and throttling downloads during active streaming.

---

### We've Reinvented Contributing

Every issue in this repo is **AI-Ready** — structured with full context, file paths, implementation guides, acceptance criteria, and a ready-to-use AI prompt at the bottom.

**Pick an issue. Copy the prompt. Paste into your AI tool. Submit a PR.**

No codebase knowledge required. No onboarding docs to read. Just pick an issue and go.

[**Browse Issues →**](https://github.com/wolffcatskyy/emby-playback-guardian/issues)

---

## Features

- **Playback Protection** — Pauses library scans and metadata refreshes while media is playing
- **Stuck Task Detection** — Kills tasks that stall (no progress change) or exceed absolute timeout
- **Download Throttling** — Throttles qBittorrent/SABnzbd when playback is active or disk I/O is saturated
- **Auto-Restore** — Restores normal operation when playback ends and system load normalizes

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
      # Disk I/O (optional — mount /proc below)
      # DISK_DEVICES: "sda"
      DRY_RUN: "true"
      TZ: "America/New_York"
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

## License

MIT
