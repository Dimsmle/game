"""Pure P2–P5 gameplay primitives for Character Studio v0.15.

This package deliberately does NOT mutate the application's GameStore, modify
ReplyTurn, call DeepSeek, invoke renderers, or touch the user's live assets.
Codex wires the audited core to the existing game and Windows UI.
"""
__version__ = "0.15.0-core"
