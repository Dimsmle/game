# CHANGELOG

## 0.11.0

- Sentence-level LLM semantic segments, first-sentence-only provisional streaming preview.
- Ordered, expiring reply capabilities; idempotent sentence activation without preplaying future actions.
- SQLite stores only the activated prefix; interrupted/unread tails do not enter future context.
- Stage next-sentence/typewriter controls, per-sentence optional TTS and cancellation isolation.
- Image preloading before activation and stale navigation/settings guards.
- Offline three-expression test in free chat; 65 Python tests and four JS suites.

## 0.10.0

- Stage-only free chat with provisional streaming text and final-only validated behavior.
- DeepSeek official API / OpenAI-compatible provider, env-only keys, bounded retry and cancellation.
- Optional Qwen Base lazy GPU adapter, GPT-SoVITS and local system voice selection.
- Serialized playback, stop/stale result isolation, bounded WAV cache and timing metrics.
- Offline Qwen benchmark entry; no model downloads or GPU inference acceptance claimed.
- STT explicitly disabled by default; no Whisper/local LLM installed.
- 60 Python tests and three JS test suites; real kan_10 offline stage acceptance.

## 0.9.0

- Game-only default UI: character stage, dialogue box, settings and modal choices.
- Three silent authored scenes with branching replies and per-line semantic emotions,
  resolved through the existing model-specific expression mapping.
- Independent dialogue director with async cancellation/retry and on-demand face preloading.
- Scene/outfit selection in game dialogs; workbench preserved behind `--studio`.
- Dialogue demos do not call AI/TTS or enter chat history; no new EXE was built.

## 0.8.0

- Independent CPU preview for 4x4 Bezier `head_UD` cages from local resx data.
- 24 FPS nod sequences with per-frame normal/blink/talk, bounded decoded-image cache,
  cancellation, same-expression settling and runtime token checks.
- Background generation/progress API, per-model/expression/source-signature review gate,
  and renderer adapter preferring reviewed nod sequences over static same-tag motions.
- Manual body override preserves active speech; startup interactions wait for initialization.
- Fixed stage clipping; added focus view and real nod shortcut; internal caches no longer
  fill the asset browser.
- Project-local desktop environment and WebView2 load validated; 30-turn LLM/TTS adapter
  contract test uses local mock services, not real model weights.
- Source-only release builder and `.venv`-aware Windows launchers.
- Full native E-mote mask/physics, real AI/TTS and a new EXE distribution remain unverified.

## 0.7.0

### Added
- `motion_probe.py`: truthful 24–30 FPS candidate gate that samples a real PSB motion,
  checks pixel variation/transparency/talk overlay, and never marks it playable automatically.
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
- E-mote `type: 0` sprite interval terminators now clear prior fade overlays; this fixes
  kan_10 neutral/happy faces retaining water-drop overlays without disabling real tears.
- Legacy stage animation is not triggered when no real PSB motion matches the semantic tag.
- Auto-generated character layer ID is now generic `__auto_emote_character`;
  old `__auto_emote_kan` manifests remain compatible.
- Top-level documentation rewritten as one v0.7 baseline; old release notes moved to `docs/history`.

### Still not implemented
- Native continuous E-mote mesh/mask/physics playback.
- Live2D rig/model.
- Verified Windows EXE build on the user's machine.
- Verified live DeepSeek/GPT-SoVITS integration.
