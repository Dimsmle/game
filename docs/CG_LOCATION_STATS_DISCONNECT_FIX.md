# 地点空值、总览属性编辑与客户端断连修正

2026-10-16；在 main / 0d482b2 上增量修改，无新分支。

## 实际变更

- CG地点列表为空即不限制地点；非空时匹配任一场景ID/名称。移除额外开关，保留角色、好感度（默认至少50、可修改）、素材和读完回复后的执行检查。
- 兼容旧 any_location 布尔字段，但不让它覆盖非空地点列表；保存规则时去除旧字段，不清空玩家已有的地点。
- 将四项属性编辑从角色卡移至角色状态总览，紧跟属性卡片。仍通过现有绑定版本检查、SQLite备份和事务保存；服装名称编辑留在角色卡。
- Handler.reply在响应头或正文发送时遇到 ConnectionAbortedError/ConnectionResetError/BrokenPipeError，关闭本次连接，不再向同一断开的连接发送错误响应。保留其他IO、序列化和业务错误。

用户提供的10053日志证明发送响应时连接已中断，第二段异常来自err再次写同一连接；不能据此判断是哪个客户端软件或安全软件中断了连接。此修复处理断连后的重复报错，不承诺阻止连接本身被中断。

## 修改文件

studio/app.py、cg_events.py、web/gameplay_ui.js、roleplay_plus/web/main.js；tests/test_http_disconnect.py、test_gameplay_integration.py、test_gameplay_ui.js、test_roleplay_ui.js；AGENTS.md、本文、SCENES_WARDROBE_AND_TRIGGER_RULES.md、API_TEST_POLICY.md。

## 测试命令与结果

环境：Windows，项目.venv Python；TEMP/TMP指向项目.tmp。

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
$tests=@('frame_sequence','dialogue_player','chat_stream','reply_player','game_text','game_state_hud','roleplay_ui','gameplay_stage','touch_geometry','cg_sequence_player','cg_event_stage','gameplay_ui')
foreach($test in $tests){node "tests/test_$test.js"}
node --check studio/web/app.js
node --check studio/web/gameplay_ui.js
node --check studio/roleplay_plus/web/main.js
.venv\Scripts\python.exe build_windows.py
.venv\Scripts\python.exe main_desktop.py --doctor
dist\CharacterStudio\CharacterStudio.exe --doctor
```

- Python：321项，43.455秒，OK（2项因Windows符号链接权限跳过）。日志.tmp/cg-location-disconnect-tests.log。
- 12组Node测试及3项JS语法检查通过。新增覆盖空地点、不为空时旧开关不能绕过、总览编辑器挂载、三类断连发生在响应头/正文时不重复发送、其他异常不被隐藏。
- Windows浏览器使用computer-use技能、真实本机素材、隔离临时数据库和模拟AI：总览好感度25改75保存成功，属性卡同步；CG编辑器没有额外地点开关，默认门槛50，清空地点保存、刷新后仍为空。正式私人存档未修改。
- Windows EXE已重新构建；隔离LOCALAPPDATA下源码Doctor errors=0/warnings=1（未选模型），EXE Doctor退出0。未完成原生EXE所有图形交互的独立验收。
- 本轮真实DeepSeek调用0；未改写原始游戏资源、密钥或私人数据库。未处理既有8个被跟踪的Python3.11缓存修改。

## 已知限制与下一步

浏览器客户端可能仍主动取消请求；这不等于服务崩溃。CG仍是既有差分播放，不是原生完整动画。下一步最小检查：用户重启实际使用的源码服务/EXE，确认正式存档中的地点条件与属性编辑入口；无须重复收费API测试。
