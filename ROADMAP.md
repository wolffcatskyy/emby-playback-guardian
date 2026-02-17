# Roadmap

This document outlines planned features and improvements for Emby Playback Guardian.

## Current Version

**v1.2.0** (Released February 2026)

- Health check and metrics endpoints (`/health`, `/metrics`)
- Prometheus-compatible metrics
- Startup retry behavior for boot resilience
- API retry with exponential backoff

## Next Release: v1.3.0

### Intro Scan Pause Support ([#7](https://github.com/wolffcatskyy/emby-playback-guardian/issues/7))

Add the "Scan for episode intros" task to the default pausable tasks list. This task runs intro detection (chapter markers for "Skip Intro" functionality) and can cause playback stuttering on systems with slower disks.

**Implementation:**
- Add `Scan for episode intros` to the default `PAUSABLE_TASKS` list
- No breaking changes; users who already customized `PAUSABLE_TASKS` can add it manually

**ETA:** Next patch release

## Future Releases

### v1.4.0: Windows Disk I/O Support ([#6](https://github.com/wolffcatskyy/emby-playback-guardian/issues/6))

Enable disk I/O monitoring for Windows users running Docker Desktop (WSL2 backend).

**Problem:**
The current implementation reads from `/proc/diskstats`, which is Linux-specific. Windows users cannot use disk I/O-based throttling, only playback-based throttling.

**Solution:**
Use `psutil.disk_io_counters()` to provide cross-platform disk monitoring. The guardian will detect the OS at runtime and use the appropriate method:
- **Linux:** `/proc/diskstats` (current method, unchanged)
- **Windows:** `psutil.disk_io_counters()` via WMI

**Implementation steps:**
1. Add `psutil` to `requirements.txt` (already used elsewhere in some deployments)
2. Refactor `DiskMonitor` class to abstract the I/O source
3. Add `WindowsDiskMonitor` subclass using `psutil`
4. Auto-detect platform and instantiate the correct monitor
5. Update documentation with Windows-specific examples

**Blockers:** None. Waiting for tester availability.

### v1.5.0: Enhanced Task Management

Potential improvements for more granular task control:

- **Task priorities:** Allow prioritizing which tasks to pause first
- **Task resume:** Optionally re-trigger paused tasks after playback ends
- **Task scheduling awareness:** Avoid pausing tasks during their scheduled windows

### Backlog (No Timeline)

These items are under consideration but not yet prioritized:

- **Jellyfin-specific optimizations:** Test and tune for Jellyfin API differences
- **Multiple server support:** Monitor multiple Emby/Jellyfin instances
- **Home Assistant integration:** Native integration via MQTT or REST
- **Plex support:** Extend monitoring to Plex Media Server (significant effort)
- **Web dashboard:** Simple UI for real-time status and configuration

## Contributing

Have a feature request? [Open an issue](https://github.com/wolffcatskyy/emby-playback-guardian/issues/new?template=feature_request.yml) with the "feature request" template.

All issues are structured for AI-assisted development with full context and implementation guides.
