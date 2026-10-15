@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0project_python.bat" -m unittest discover -s tests -v
node --check studio\web\app.js
node tests\test_frame_sequence.js
node --check studio\web\game.js
node tests\test_dialogue_player.js
node --check studio\web\chat_stream.js
node tests\test_chat_stream.js
node --check studio\web\reply_player.js
node tests\test_reply_player.js
node tests\test_game_text.js
node tests\test_game_state_hud.js
node --check studio\roleplay_plus\web\main.js
node --check studio\roleplay_plus\web\launcher.js
node tests\test_roleplay_ui.js
node --check studio\web\gameplay_ui.js
node --check studio\web\gameplay_stage.js
node tests\test_gameplay_stage.js
node tests\test_gameplay_ui.js
node tests\test_touch_geometry.js
node --check studio\web\cg_sequence_player.js
node tests\test_cg_sequence_player.js
node --check studio\web\cg_event_stage.js
node tests\test_cg_event_stage.js
pause
