# AGENTS.md — Character Studio v0.7

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
python main_desktop.py --doctor
```

Windows EXE validation must run on Windows.

## Current first tasks

Follow `docs/CODEX_HANDOFF.md`, beginning with the real kan_10 crying-face/rendering defect,
then one continuous-action POC. Do not rewrite the working behavior/runtime architecture first.

Every completion report must state:
- changed files
- exact test results
- manual Windows/real-asset result
- whether original game assets were modified
- remaining limitations/risks
- next smallest task
