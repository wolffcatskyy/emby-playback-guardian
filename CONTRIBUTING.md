# Contributing to Emby Playback Guardian

Welcome! We're thrilled you're interested in contributing. This guide is designed for **everyone** — whether you're contributing your first line of code, using AI tools to help, or simply reporting ideas. No prior open source experience required.

## Table of Contents

- [Ways to Contribute](#ways-to-contribute)
- [First-Time Contributors](#first-time-contributors)
- [Using AI to Contribute](#using-ai-to-contribute)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Submitting Pull Requests](#submitting-pull-requests)
- [Code of Conduct](#code-of-conduct)
- [Getting Help](#getting-help)

---

## Ways to Contribute

Contributions aren't limited to code. Here are ways you can help:

### Bug Reports & Issues
- Found something broken? [Open an issue](../../issues)
- Unexpected behavior with your media server? Let us know
- Playback detection not working? We want to fix it

### Documentation
- Improved installation instructions
- Clearer explanations of configuration options
- Troubleshooting guides based on your experience
- Examples for different Emby/Jellyfin setups

### Features & Enhancements
- Support for additional download clients
- Better stuck scan detection heuristics
- New media server integrations
- Notification support (webhooks, Discord, etc.)

### Testing & Quality
- Test with your Emby or Jellyfin setup
- Report edge cases or compatibility issues
- Help build an automated test suite (great first contribution!)

### Community
- Answer questions from other users
- Share your deployment stories
- Help improve this documentation

---

## First-Time Contributors

Never contributed to open source before? Perfect. This project is a great place to start.

### Step 1: Fork the Repository

Click the **Fork** button at the top of the [repository page](../../). You now have your own copy to experiment with safely.

### Step 2: Clone Your Fork

```bash
git clone https://github.com/YOUR-USERNAME/emby-playback-guardian.git
cd emby-playback-guardian
```

### Step 3: Create a Branch

```bash
git checkout -b fix/my-fix-name
# or for features:
git checkout -b feature/my-feature-name
```

**Branch naming conventions:**
- `fix/` — bug fixes (`fix/stuck-detection-false-positive`)
- `feature/` — new features (`feature/discord-notifications`)
- `docs/` — documentation (`docs/jellyfin-setup-guide`)
- `test/` — testing improvements (`test/emby-client-mock`)

### Step 4: Make Your Changes

See [Making Changes](#making-changes) below.

### Step 5: Commit and Push

```bash
git add .
git commit -m "Fix: false positive stuck detection on long library scans"
git push origin fix/my-fix-name
```

**Commit message format:**
- `Fix:` for bug fixes
- `Feature:` for new features
- `Docs:` for documentation
- `Test:` for test additions

### Step 6: Open a Pull Request

1. Go to the original repository
2. Click **Pull Requests** → **New Pull Request**
3. Select your branch
4. Fill out the PR template
5. Submit!

---

## Using AI to Contribute

We **welcome and encourage** AI-assisted contributions. AI tools (Claude, ChatGPT, GitHub Copilot, etc.) can help you generate code, write tests, improve documentation, and debug issues.

### Architecture Context for AI

Paste this into your AI assistant along with the issue you want to work on:

```
I want to contribute to emby-playback-guardian. Here's the project context:

- Single Python file: guardian.py (~680 lines)
- Only dependency: requests
- Docker: python:3.11-alpine, non-root user
- Config: all environment variables (see env(), env_bool(), env_int() helpers)
- Classes: GuardianState (tracks what we changed to undo correctly), EmbyClient (REST API: sessions + scheduled tasks), QBitClient (qBittorrent Web API: alt speed toggle), SABnzbdClient (SABnzbd API: speed limit), DiskMonitor (parse /proc/diskstats)
- Main loop polls every POLL_INTERVAL seconds
- Stuck detection: two-layer — progress stall (STUCK_STALL_MINUTES) + absolute timeout (STUCK_SCAN_TIMEOUT)
- Smart state: tracks what it changed to restore correctly (won't undo user-set speed limits)
- Emby + Jellyfin compatible (SERVER_TYPE env var switches API prefix)
- Graceful degradation: unconfigured services are skipped, not errored

The issue I want to work on is: [paste issue title and body here]
```

Then paste the contents of `guardian.py` and ask your AI to implement the fix/feature.

### Guidelines for AI-Assisted Work

**You are always responsible for your contribution.**

#### Required

1. **Review everything before submitting** — read every line, understand what it does
2. **Disclose AI assistance in your PR:**
   ```
   **AI Assistance:** Generated using [tool] with prompts focusing on [specific area]
   **Validation:** Tested in [your setup], verified [specific test cases]
   **Changes Made:** Manually reviewed and adjusted [list specific changes]
   ```
3. **Test thoroughly** — run with `DRY_RUN=true`, test error conditions
4. **Validate against project standards** — follows our code style, works with Docker setup

#### What We Won't Accept

- Unreviewed or untested AI output ("AI slop")
- Code you don't understand
- Changes that don't address a specific issue
- Low-quality generic "improvements"

### AI-Friendly Issue Template

When opening an issue, provide context that both AI tools and humans can work with:

```markdown
## Issue Title
[Clear, specific description]

## Current Behavior
[What happens now]

## Expected Behavior
[What should happen]

## Environment
- Media server: [Emby / Jellyfin, version]
- Docker version: [e.g., 24.0.2]
- OS: [e.g., Ubuntu 22.04, Synology DSM 7.3]
- Download clients: [qBittorrent / SABnzbd, versions]

## Steps to Reproduce
1. [First step]
2. [Second step]
3. [Result]

## Logs
[Relevant error messages or logs]

## Suggested Solution (optional)
[Your idea for fixing this]
```

---

## Development Setup

### Prerequisites

```bash
# Python 3.11+
python3 --version

# Install dependencies
pip install -r requirements.txt

# You'll need an Emby or Jellyfin server with an API key
```

### Local Testing

```bash
# Configure and run
export EMBY_URL="http://your-server:8096"
export EMBY_API_KEY="your-key"
export DRY_RUN=true
export LOG_LEVEL=DEBUG
python guardian.py
```

### Docker Testing

```bash
docker build -t emby-playback-guardian:dev .
docker run --env-file .env emby-playback-guardian:dev
```

---

## Making Changes

### Code Style

```python
# Use f-strings for formatting
log.info(f"Paused task: '{task.name}' (playback active)")

# Use the module-level log object (not print)
log.debug(f"Disk {dev}: {busy_pct:.1f}% busy")
log.warning(f"STUCK: '{task.name}' — {kill_reason}")

# Environment variables via project helpers
POLL_INTERVAL = env_int("POLL_INTERVAL", 30)
DRY_RUN = env_bool("DRY_RUN", False)
EMBY_URL = env("EMBY_URL", "")
```

### Key Constraints

- **Single file** — `guardian.py` should remain self-contained
- **Single dependency** — `requests` only, no new deps without discussion
- **No external state** — no database, no files, all in-memory
- **Smart state tracking** — always check `GuardianState` before restoring; only undo what we changed
- **Graceful degradation** — unconfigured services must be skipped, never error
- **Error resilience** — errors in the poll loop should be logged and retried, not crash

### Pre-Submission Checklist

- [ ] Changes work with `DRY_RUN=true`
- [ ] Tested with `LOG_LEVEL=DEBUG`
- [ ] New env vars have sensible defaults
- [ ] Graceful degradation works (unconfigured services skipped)
- [ ] Error messages are clear
- [ ] No debug code left in commits
- [ ] Documentation updated if needed

---

## Submitting Pull Requests

### PR Template

```markdown
## Description
Brief summary of what this PR does.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement

## Problem It Solves
Which issue does this address? (Link: #123)

## How Was This Tested?
- Media server: [Emby/Jellyfin, version]
- Scenarios verified: [list]
- DRY_RUN tested: [yes/no]

## Checklist
- [ ] I've tested with DRY_RUN=true
- [ ] I've updated documentation if needed
- [ ] My code follows the project style
- [ ] New env vars have sensible defaults
- [ ] No debug code or secrets in commits

## AI Assistance (if applicable)
**Tools Used:** Claude / ChatGPT / GitHub Copilot
**Scope:** Generated [specific part], reviewed and validated [changes made]
**Validation:** Tested in [environment], verified [specific test cases]
```

### Review Process

1. We'll review within a few days
2. We might request changes — this is normal and collaborative
3. Once approved, we'll merge and you'll be credited as a contributor

---

## Code of Conduct

- **Be respectful** to all contributors
- **Welcome diverse perspectives** and experiences
- **Ask questions** rather than make assumptions
- **Assume good intent** in interactions

---

## Getting Help

**"I'm not a programmer, can I still contribute?"**
Absolutely! Documentation, testing, and reporting issues are huge helps.

**"Can I use AI tools?"**
Yes! See [Using AI to Contribute](#using-ai-to-contribute). Just review and test everything.

**"How long until my PR is reviewed?"**
We aim for a few days. If it's been a week, ping us politely.

**"What if my PR is rejected?"**
That's okay! We'll explain why and suggest improvements. You can revise and resubmit.

**"I only have Jellyfin, not Emby — can I still contribute?"**
Yes! The guardian supports both. Test with `SERVER_TYPE=jellyfin` and note your setup in the PR.

---

## Recognition

Contributors are listed on the GitHub contributors page and mentioned in release notes for significant contributions.

---

**Ready to contribute? Pick an issue from the [issues page](../../issues) and get started!**
