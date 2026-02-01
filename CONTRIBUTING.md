# Contributing to Emby Playback Guardian

Contributions welcome — from humans, AIs, or both working together.

This guide is structured so you can paste it (or a section of it) directly into your AI assistant (Claude, ChatGPT, Copilot, etc.) along with an issue, and get a useful PR out of it.

## Quick Start

```bash
git clone https://github.com/wolffcatskyy/emby-playback-guardian.git
cd emby-playback-guardian
pip install -r requirements.txt
# Configure and run locally
export EMBY_URL="http://your-server:8096"
export EMBY_API_KEY="your-key"
export DRY_RUN=true
python guardian.py
```

## Architecture Overview (for AI context)

**Single-file application** — everything is in `guardian.py` (~680 lines).

```
guardian.py
├── Configuration (env vars, helpers)
├── GuardianState (dataclass — tracks what we changed so we can undo it)
├── EmbyClient (REST API: sessions, scheduled tasks)
├── QBitClient (qBittorrent Web API: alt speed toggle)
├── SABnzbdClient (SABnzbd API: speed limit percentage)
├── DiskMonitor (parse /proc/diskstats for I/O utilization)
└── main() — polling loop:
    1. Check playback sessions
    2. Check running tasks
    3. Stuck detection (progress stall + absolute timeout)
    4. Pause tasks during playback
    5. Throttle/restore downloads based on playback + disk I/O
```

**Key design principles:**
- **Smart state tracking** — only restore what we changed (check `GuardianState`)
- **Graceful degradation** — unconfigured services are skipped, not errored
- **No external state** — no database, no files, all in-memory
- **Single dependency** — `requests` only (no psutil, no frameworks)

## How to Contribute with AI

### Step 1: Pick an issue

Browse [open issues](https://github.com/wolffcatskyy/emby-playback-guardian/issues). Issues labeled `ai-friendly` are specifically written to be solvable by AI assistants.

### Step 2: Give your AI context

Copy this into your AI assistant:

```
I want to contribute to emby-playback-guardian. Here's the project context:

- Single Python file: guardian.py (~680 lines)
- Only dependency: requests
- Docker: python:3.11-alpine, non-root user
- Config: all environment variables (see env(), env_bool(), env_int() helpers)
- Classes: GuardianState, EmbyClient, QBitClient, SABnzbdClient, DiskMonitor
- Main loop polls every POLL_INTERVAL seconds
- Smart state: tracks what it changed to restore correctly
- Emby + Jellyfin compatible (SERVER_TYPE env var switches prefix)

The issue I want to work on is: [paste issue title and body here]
```

Then paste the contents of `guardian.py` and ask your AI to implement the fix/feature.

### Step 3: Submit a PR

- Fork the repo
- Create a branch (`feat/your-feature` or `fix/your-fix`)
- Make your changes
- Test with `DRY_RUN=true` against a real Emby/Jellyfin server if possible
- Open a PR with a clear description of what changed and why

## Writing Good Issues (for maintainers)

When creating issues, structure them for AI consumption:

```markdown
## What
[One sentence describing the desired outcome]

## Why
[Context on why this matters]

## Where in the code
[File, class, method, or line range]

## Acceptance criteria
- [ ] Specific, testable requirement 1
- [ ] Specific, testable requirement 2

## Constraints
- Must not break existing env var config
- Must degrade gracefully if not configured
- Single file only (no new files)
```

## Code Style

- **Python 3.11+**, no type stubs needed
- **f-strings** for formatting
- **logging** via the module-level `log` object (not print)
- **Environment variables** for all config — use `env()`, `env_bool()`, `env_int()`
- **Error handling**: catch specific exceptions, log and continue (don't crash the loop)
- **No new dependencies** without discussion — the single-dependency constraint is intentional
- Keep it in **one file** — `guardian.py` should remain self-contained

## Testing

There's no test suite yet (good first contribution!). For now:

1. Run with `DRY_RUN=true` and verify log output
2. Check that new env vars have sensible defaults
3. Verify graceful degradation (what happens if the service isn't configured?)
4. Test the happy path and at least one error path

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
