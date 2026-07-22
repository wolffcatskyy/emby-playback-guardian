# Changelog

All notable changes to Emby Playback Guardian are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.2] — 2026-07-21

### Added

- **AND-mode download throttling** — new `DOWNLOAD_THROTTLE_REQUIRES_PLAYBACK_AND_IO`
  environment variable that requires **both** active playback **and** high disk I/O before
  throttling downloads (previously, high disk I/O alone was sufficient). Controlled via
  `DISK_THROTTLE_CONDITION=playback_and_io`. ([#12] by [@clau-bucur])

- **Cross-platform disk I/O monitoring** — Windows and macOS now use `psutil` for disk
  I/O metrics, replacing the Linux-only `/proc/diskstats` dependency. Windows users
  benefit from `PhysicalDisk` counters via `psutil.disk_io_counters()` and throughput-based
  fallback. ([#6], [#10], [#11] by [@clau-bucur])

- **Intro scan pause support** — `Scan for episode intros` added to the default
  `PAUSABLE_TASKS` list so intro detection is paused during playback without manual
  configuration. ([#7], [#9])

### Fixed

- **Windows disk I/O always showing 0%** — added throughput-based fallback for platforms
  that don't expose disk busy time natively.
- **Disk I/O aggregation bug** — aggregation now uses `max(time_pct, bytes_pct)` per
  device instead of naive averaging, preventing under-reporting when one metric dominates.
- **Code cleanup** — removed decorative separators and redundant docstrings across the
  codebase.

### Changed

- Updated README with problem statement, better structure, and badges.
- Added GitHub Sponsors and Ko-fi funding links.
- Updated AI disclosure text.
- Added project roadmap (`ROADMAP.md`).

## [1.2.0] — 2026-02-04

### Added

- Health check endpoint (`/health`)
- Prometheus-compatible metrics endpoint (`/metrics`)
- Startup retry behavior for boot resilience
- API retry with exponential backoff

### Changed

- Improved notification system

## [1.1.0] — 2026-02-01

### Added

- Progress-based stuck detection for scheduled tasks

## [1.0.0] — 2026-01-30

### Added

- Initial release of Emby Playback Guardian
- Emby/Jellyfin task pausing during active playback
- qBittorrent and SABnzbd download throttling based on disk I/O
- Configurable via environment variables
- Docker support

[#6]: https://github.com/wolffcatskyy/emby-playback-guardian/issues/6
[#7]: https://github.com/wolffcatskyy/emby-playback-guardian/issues/7
[#9]: https://github.com/wolffcatskyy/emby-playback-guardian/pull/9
[#10]: https://github.com/wolffcatskyy/emby-playback-guardian/pull/10
[#11]: https://github.com/wolffcatskyy/emby-playback-guardian/issues/11
[#12]: https://github.com/wolffcatskyy/emby-playback-guardian/pull/12
[@clau-bucur]: https://github.com/clau-bucur
