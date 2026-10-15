# AGENTS.md — Character Studio v0.11

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
