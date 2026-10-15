# 对话CG修正、旁白与shi事件目录

2026-10-15，基于 main / a157c62 增量修改，没有另建分支。

## 本机排查结论

只读检查正式配置/数据库与脱敏日志：角色shi_37、地点bg05/morning、ev_shi_c04已导入，关键词包含用户配置项；cg_commands和cg_sessions均为0。最近对话的turn/complete为200，但没有cg/prepare或cg/apply记录。

因此没有证据表明是图片解码失败。旧日志没有保存模型cg_event，无法追溯区分模型返回null、遗漏字段或返回非法决定；不把推测当作确定根因。代码检查发现角色资料通用说明对“不能宣称播放CG”的要求过宽，容易与新的媒体事件导演冲突，同时导演未强调“答应活动必须同步决定”。本轮明确区分媒体CG与属性奖励邀请，强化肯定/否定/回忆语义，补充cg.decision脱敏诊断（候选ID、匹配ID、状态、action，不保存对话和密钥）。

关键词仍然是语义线索，不强制播放；只有当前角色/场景合法、模型决定合法、完整读完、预加载成功、版本未变时才执行。匹配但模型未决定/决定无效会在舞台底部文字提示，不新增弹窗。不增加第二次模型请求。

## 本轮实现

- 逐句协议新增kind=dialogue/narration，旧回复默认dialogue。仍使用speech存文本，不破坏ReplyTurn。
- 旁白楷体、对白原字体、括号动作弱化斜体；DOM textContent创建节点，不插入模型HTML。
- 流式预览也传kind，旁白不动嘴、不合成语音、不提交表情动作；对白保持原逐句机制。仅已激活前缀入历史，旁白以【旁白】标记保存并还原给后续模型。
- 设置→场景与CG事件→目录中新增“CG事件”，列表和编辑表单同页；移除海边专用导入按钮与舞台单样例预览入口，改为每项可预览。
- 自动索引本机19组：ev_shi_c01～c11、ev_shi_h12～h19。只补缺项；现有shi_beach标题、关键词和条件不覆盖。其余18项空标题/条件、禁用草稿，等待用户填写，不根据编号猜剧情。
- 新增索引前SQLite备份；重复扫描无变更时不写版本。首次--root解析后也补索引，避免仅app.init时尚无素材目录。
- 草稿可仅改名字保存，不解析图片。启用前需完整条件，界面先成功导入完整差分CG再启用；失败会报告，不偷偷留下启用的坏规则。

## 验收

- `.venv\Scripts\python.exe -m unittest discover -s tests -v`：310项，OK，2 skipped（Windows符号链接权限），39.016秒；日志.tmp/cg-narration-final.log。集成测试需回环网络权限，受限沙箱的WinError10013不是应用故障。
- 12组Node测试通过（原11组+test_gameplay_ui.js）；JS语法检查通过。新增旁白/历史前缀/无动作副作用、CG空决定诊断、草稿索引幂等和目录编辑测试。
- 首轮发现小预算下预设名称被CG说明挤掉；压缩说明后预算回归与最终完整回归通过。
- Windows浏览器（computer-use技能）隔离数据库+真实素材+模拟AI：海边背景、楷体旁白、括号动作、读完后全舞台CG、19项事件目录、草稿命名保存均实测通过；控制台error/warn为0。没有改正式存档来做UI测试。
- **真实DeepSeek仅1次新协议验收**：公开测试成年角色、合成素材/地点、无私人历史/卡片；单请求限制、输出上限650token。返回narration+dialogue，cg_event=enter/shi_beach，first_text_ms=813、total_ms=1547。此为新协议证据，不代表所有自然对话均必触发，不重复此前21次验收。
- `python build_windows.py`成功，dist/CharacterStudio/CharacterStudio.exe已更新。隔离LOCALAPPDATA下源码Doctor errors=0/warnings=1（未选角色），EXE --doctor退出0；没有把浏览器验证冒充完整原生EXE交互验收。
- 截图.tmp/narration-stage.png（本机素材，不入Git）。没有改动原始游戏资源，没有安装模型或语音识别，没有提交密钥、私人数据库和游戏CG。

## 边界与下一步

19项是事件草稿索引，**不是19组全量播放认证**。启用/预览时才按现有安全解析器合成。ev_shi_c08实际51张图，超过当前32帧安全上限，暂不能播放；其他新组未逐一验收IPT/AST兼容性。仍是CG差分循环，不是原版推镜、旋转、光效和音频完整还原。

请关闭旧进程、启动新版源码或整个dist/CharacterStudio目录；首次启动会备份并补齐草稿。用户可在目录中逐项添加标题、场景与多个关键词，再启用。下一最小技术任务为大组CG按需帧加载及具体导入失败适配；不靠提高内存上限冒充已完成。

## 修改文件

main_desktop.py；studio/app.py、cg_events.py、gameplay.py、replies.py、roleplay_plus/composer.py；studio/web/chat_stream.js、reply_player.js、game.js、game.css、gameplay.html、gameplay_ui.js、gameplay_stage.js；tests/test_reply_robustness.py、test_gameplay_integration.py、test_reply_player.js、test_game_text.js、test_gameplay_ui.js；05_自动运行项目测试.bat、AGENTS.md、本文与API_TEST_POLICY.md。
