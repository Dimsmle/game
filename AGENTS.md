# AGENTS.md — Character Studio v0.14.1 P1.5

Latest dialogue/index work: read docs/CG_NARRATION_AND_SHI_INDEX.md.
Keep narration kind through stream/ReplyTurn/history; no mouth/TTS/action for narration.
CG groups are disabled drafts until user-supplied titles/conditions; never infer story.
Run node tests/test_gameplay_ui.js too. One paid CG/narration enter check is recorded;
do not repeat it. 19 shi entries are an index, not full playback certification.

## Current user override: dialogue-directed CG, no approval gate

Work on main unless the user asks for another branch. Read docs/CG_DIALOGUE_EVENTS.md.
The user removed CG approval and choice-card requirements. User-configured CG
IDs may enter/exit from validated LLM decisions after ReplyTurn completion.
These media-only sessions never write stat effects. Keep file integrity,
scene/model gates, preloading, ABA/version checks and SQLite idempotency.
bg05 is explicitly user-labeled beach; aa is morning, ab time is not known.
Touch geometry still needs calibration, but no separate approval checkbox.
Older approval text below and in prior reports is historical for CG sessions.

## Current development: v0.15 integrated gameplay

The user has authorized P2–P5 integration on feat/v015-integrated-gameplay.
Read docs/V0.15_INTEGRATION_REPORT.md and docs/API_TEST_POLICY.md first.
CG sample progress: docs/CG_SHI_C04_POC.md. cg_sequence is manual diff scene
playback, NOT full original animation. No auto-review/unlock on test preview.
The older instruction below to not start P2–P5 is superseded by this request.
Keep the existing GameStore, ReplyTurn, credentials, RP Composer and renderer.
gameplay_core.director is a pure reference model, NOT the authoritative commit path.
The separate v0.15.2 preview workbench/PreviewStore is deliberately not installed.
Run node tests/test_gameplay_stage.js and node tests/test_touch_geometry.js too.
Do not repeat paid DeepSeek tests already recorded in API_TEST_POLICY.md.
Normal unit tests must remain offline; no bulk live chats or hidden retries.
Real scene/CG/touch approvals are user decisions, never inferred from filenames.

Credentials: read `docs/SETTINGS_AND_SECRETS.md`. Use studio.credentials.get_api_key,
never set a literal key in app.py or merge private credentials into public settings.
Development local_secrets.json is ignored and excluded from source releases.
Environment overrides the private file; tests must explicitly isolate that file.

P0/P1 prerequisites for v0.13 are implemented. Read `docs/V0.12_P0_P1_REPORT.md`,
`docs/GAME_STATE_SCHEMA.md` and `docs/AI_EVENT_SYSTEM.md` before further work.
P1.5 is now integrated as studio/roleplay_plus: cards, separate player Persona,
six presets, conditional Lorebook and PromptComposer. Read docs/ROLEPLAY_ENGINE.md
and docs/V0.14.1_MERGE_REPORT.md. Legacy settings.persona migrates only once;
the active RP card owns identity, while the main GameStore owns all gameplay state.
RP HTTP mutations must hold CHAT_LOCK/LOCK with ReplyTurn acceptance/activation.
Do not repeat P1/P1.5 or jump to background/CG/touch/event execution.

GameState uses the existing history.sqlite3, user_version=1, with SQLite backup
before migration. Existing messages/memories belong to profile 'default'; all
new queries/writes must be profile-scoped. ReplyTurn snapshots bind to persistent
profile generation and state revision; do not drop the ABA guard. No model output
can call GameStore.commit_effect, and there is no public stat-delta endpoint.
AI scene suggestions are disabled pending a verified player-choice commit engine.
Default entry is free chat; authored scenes remain in developer regression tools.
Also run `node tests/test_game_state_hud.js` in the required JS regressions.

Latest fixes: read `docs/V0.11_DIALOGUE_AND_SHI_FIXES.md`. Assets are organized
under `characters/<code>/<model>_decompiled`; recursive discovery remains supported.
Face suffixes A/B/C (full-width) are actual preset labels, NOT outfit-number rules.
Keep opacity mask bit 0x400: opa=0 suppresses the whole referenced pupil subtree.
Add `node tests/test_game_text.js` to the required JS regressions.

Current dialogue work: read `docs/V0.11_SENTENCE_REPLIES.md` first. Free chat now
supports semantic segments and ordered activation. Future sentences are never
submitted to runtime in advance. History stores only the activated prefix, not
the unread tail. Keep cancel/model/config/expiry guards and idempotent retries.

Read `docs/V0.10_AI_FOUNDATION.md` for current AI provider implementation and honest
validation boundaries. DeepSeek official is the preferred real provider; demo stays
available without a key. STT is off. Do not install Whisper or a local LLM.
No real cloud/TTS quality or latency acceptance has happened without credentials,
authorized reference audio, and explicit model preparation. Qwen Base is optional;
do not claim the adapter or synthetic HTTP tests prove real GPU inference works.

Read in order:

1. `README_先看.md`
2. `docs/CharacterStudio_总体规划及Codex实施.md`
3. `docs/ARCHITECTURE.md`
4. `docs/CODEX_HANDOFF.md`
5. `功能验证与未完成事项.md`

## Goal

A Windows-local AI virtual character program using user-authorized local assets.
Prioritize user-visible reliability over scanners/reports.

## Architectural rules

- LLM emits semantic `emotion/action_tag/scene/intensity`; it never selects file paths,
  PSB IDs, commands or arbitrary URLs.
- `studio/behavior.py` resolves semantic tags to vetted game presets.
- `studio/runtime.py` owns cooldown, interruption, queue, speaking state and scene lock.
- Render backends implement the `studio/renderers.py` contract.
- Current `static_emote_preview` is NOT native continuous E-mote.
- Never claim `frame_sequence_target` or `live2d_cubism_target` is implemented because
  it appears in capabilities metadata.

## Asset rules

Default local assets: `G:\开发游戏\Amakano3_AI`

Supported known model prefixes: `kan`, `tou`, `say`, `shi`, `let`.

Treat numeric PSB suffixes as opaque. Outfit/action family relationships require
human review and are stored in `model_metadata.json`.

Do not commit:
- game PNG/JPG/JSON/PSB/PFS/OGG/WAV
- generated character_exports
- user chat databases
- GPT-SoVITS/Whisper weights
- credentials/API keys
- `%LOCALAPPDATA%\CharacterLab`

## Before and after substantive edits

Run:

```powershell
python -m unittest discover -s tests -v
node --check studio\web\app.js
node tests\test_frame_sequence.js
node tests\test_dialogue_player.js
node tests\test_chat_stream.js
node tests\test_reply_player.js
python main_desktop.py --doctor
```

Windows EXE validation must run on Windows.

## Current first tasks

User priority changed: dialogue-appropriate per-sentence expressions and a game-only
product UI take precedence over more animations. Read `docs/V0.9_GAME_SCENES.md` first.
Default launch is the game stage; keep the workbench behind `--studio`/settings.
The three authored dialogue demos are silent and do not require AI or TTS.

Read `docs/V0.8_LOCAL_RELEASE.md` before continuing the older handoff.
The fade-terminator bug is fixed; experimental CPU head_UD mesh sequences and their
player are implemented. Do not repeat the old static-only diagnosis as the current result.
Full native E-mote mask/physics remains unimplemented. Keep the reviewed-sequence gate.
NativeSmoke.exe was flagged by endpoint protection: do not run, restore, whitelist,
or bundle it. Continue using the independent Python renderer.

Every completion report must state:
- changed files
- exact test results
- manual Windows/real-asset result
- whether original game assets were modified
- remaining limitations/risks
- next smallest task
