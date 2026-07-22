# Roadmap

This document outlines released and planned features for Emby Playback Guardian.

## Current Version

**v1.3.2** (Released July 2026)

- Intro scan pause support — `Scan for episode intros` added to default `PAUSABLE_TASKS` ([#7], [#9])
- Cross-platform disk I/O monitoring — Windows and macOS via `psutil` ([#6], [#10], [#11] by [@clau-bucur])
- AND-mode download throttling — `DOWNLOAD_THROTTLE_REQUIRES_PLAYBACK_AND_IO` / `DISK_THROTTLE_CONDITION=playback_and_io` ([#12] by [@clau-bucur])
- Windows PhysicalDisk monitoring with throughput-based fallback
- Disk I/O aggregation fix — uses `max(time_pct, bytes_pct)` per device
- Updated README with problem statement, structure, and badges

## Recent Releases

### v1.2.0 (Released February 2026)

- Health check and metrics endpoints (`/health`, `/metrics`)
- Prometheus-compatible metrics
- Startup retry behavior for boot resilience
- API retry with exponential backoff

## Future Releases

### v1.4.0: Enhanced Task Management

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

[#6]: https://github.com/wolffcatskyy/emby-playback-guardian/issues/6
[#7]: https://github.com/wolffcatskyy/emby-playback-guardian/issues/7
[#9]: https://github.com/wolffcatskyy/emby-playback-guardian/pull/9
[#10]: https://github.com/wolffcatskyy/emby-playback-guardian/pull/10
[#11]: https://github.com/wolffcatskyy/emby-playback-guardian/issues/11
[#12]: https://github.com/wolffcatskyy/emby-playback-guardian/pull/12
[@clau-bucur]: https://github.com/clau-bucur
