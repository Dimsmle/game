# CHANGELOG

## 0.7.0

### Added
- `studio/runtime.py`: deterministic behavior state machine, action cooldowns, priorities,
  interruption/queue, TTS lifecycle and manual scene lock.
- `studio/renderers.py`: truthful renderer capability contract for static E-mote preview,
  planned frame sequence and planned Live2D Cubism backends.
- `studio/diagnostics.py`: offline Doctor / environment diagnostics.
- `studio/model_meta.py`: human-reviewed outfit and pose-family metadata.
- Model discovery generalized from `kan_*` to `kan/tou/say/shi/let`.
- Runtime / renderer / diagnostics / behavior import-export / model metadata HTTP APIs.
- System UI for runtime status, renderer capabilities, Doctor, behavior tag migration,
  model outfit/pose-family annotation.
- Behavior tag import is validated and old config is backed up automatically.
- Manual scene selection locks automatic time-of-day switching for 30 minutes.
- LLM prompt receives recent runtime action context to reduce repetitive gestures.
- User-controlled local long-term memory in SQLite; memories can be enabled/disabled/deleted,
  with an explicit setting controlling whether enabled memories enter LLM requests.
- Bounded local `logs/app.log` with rotation and System-panel log viewer; request bodies/chat text/API keys are not logged.
- Generated expression preview cache pruning (max ~360 PNG files) without touching original game assets.
- Manual scene lock is enforced against AI, timed events and automatic day/night changes.
- Queue-dequeued actions expose `action_token/active_behavior`; completed reactions settle back to the same facial expression.
- TTS chat turns now wait for audio completion, preventing overlapping speech/action turns.
- CSP / same-origin browser security headers for the loopback UI.

### Changed
- Legacy stage animation is not triggered when no real PSB motion matches the semantic tag.
- Auto-generated character layer ID is now generic `__auto_emote_character`;
  old `__auto_emote_kan` manifests remain compatible.
- Top-level documentation rewritten as one v0.7 baseline; old release notes moved to `docs/history`.

### Still not implemented
- Native continuous E-mote mesh/mask/physics playback.
- Live2D rig/model.
- Verified Windows EXE build on the user's machine.
- Verified live DeepSeek/GPT-SoVITS integration.
