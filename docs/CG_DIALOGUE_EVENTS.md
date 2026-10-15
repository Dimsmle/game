# 对话驱动的全舞台 CG 事件

2026-10-15；在 main 上增量开发，不另建分支。当前用户要求优先于旧报告中的CG审核/选项卡要求。

## 当前玩法

CG无需审核。玩家配置CG组、角色素材前缀、场景和多个关键词，DeepSeek在原有逐句回复JSON中同时返回可选的 `cg_event`。
本地匹配角色与实际登记的场景；关键词作为语义线索交给AI，不是一命中就强制播放。
最后一句显示/TTS完成后，客户端预加载完整CG，提交幂等进入指令；不弹出选择卡。
CG铺满舞台（cover），聊天框与设置按钮保留；循环由本地步进时钟驱动，不阻塞后续聊天。
后续对话判断结束时输出 exit，读完本轮后移除CG，返回原背景与立绘。设置中保留“结束当前CG事件”作为手动出口。

这是一类**媒体事件**，不自动增减属性、不提交普通奖励事件，不把“模型说了”当作属性/地点写权限。
原有属性奖励事件仍走原GameStore玩家选择事务；未以此次CG需求为由开放任意数值命令。

## 已根据用户信息配置的海边事件

- ID：shi_beach；CG组：ev_shi_c04；适用素材前缀：shi。
- bg05整个家族为海边，所有变体可触发，不限制时段。
- bg05aa=早晨；bg05ab未提供具体时段，保持unknown，不猜夜间。
- 默认关键词仅“海边”；可在“设置 → 场景与CG事件”增加多个关键词、修改场景、启用/禁用和循环参数。
- 默认循环、每步停留3000毫秒；交叉淡化最多600毫秒。循环时间为本地配置，**不是原作完整动画时间轴**。
- 首次在有效素材根目录启动时，按用户指定映射登记海边并导入CG；标记初始化完成后不在每次启动覆盖用户后续改动。

正常使用：重启新版源码/EXE → 设置“切换场景”进入海边 → 与shi角色对话。
必须是当前可见舞台所对应的登记场景；仅在其他地点聊天里提到海边，不会通过本地场景门控。
普通离线demo不具备真实AI判断；浏览器验收中的确定性模拟器只在.gitignore内的.tmp测试脚本中，不进入正式程序或发行包。

## 协议与安全边界

顶层格式：segments、event_proposal、cg_event。cg_event为null，或仅包含action和event_id。
enter只能选本轮合法候选；exit只能结束当前同ID事件。未知ID、附带stats/路径等字段均丢弃，普通台词不丢失。
统一PromptComposer注入CG候选/当前事件，不新增独立模型请求；沿用DeepSeek原有流式接口。
仍检查IPT/PNG/脚本与缓存哈希、根目录约束、预加载、ReplyTurn完成、档案generation/版本/角色/素材根目录。
取消未读回复不能启动CG；换档案、换模型或改规则时旧决定失效；进入/退出通过现有SQLite新增会话表和命令去重表持久化，不重复执行。
旧媒体目录内部verified字段为兼容保留；对话CG不以它作为人工审核门槛。标签保存界面取消审核勾选。
触摸仍需实际坐标标注，不因取消审核而猜测命中区。

## 修改文件

- studio/cg_events.py：规则校验、一次性海边映射、候选、提示词、enter/exit校验、预加载检查、会话和幂等提交。
- studio/app.py、replies.py、gameplay.py：初始化、ReplyTurn快照、唯一提示词/顶层协议、完成ACK、CG接口；普通聊天保留。
- studio/web/cg_event_stage.js、cg_sequence_player.js、cg_sequence.css：非模态全舞台、循环计时器、退出/失效取消、重载恢复。
- studio/web/game.js、gameplay_stage.js、index.html：舞台与CG命令接入、模型/档案切换隔离、手动出口。
- studio/web/gameplay.html、gameplay_ui.js：场景/多关键词/循环规则表单，取消审核勾选，新增标签保存入口。
- tests/test_gameplay_integration.py、test_cg_sequence_player.js、test_cg_event_stage.js及测试批处理：新增自动事件、无审核、无属性副作用、退出、预加载、ABA、循环和海边家族回归。
- AGENTS.md、本文和API_TEST_POLICY.md：更新本地执行与费用规则。

## 实际验收

- `.venv\Scripts\python.exe -m unittest discover -s tests -v`：306项，OK，2 skipped（Windows符号链接权限）；.tmp/cg-dialogue-final.log。
- 11组Node回归通过：原10组+test_cg_event_stage.js；几何组318用例仍通过。新/修改JS语法检查通过。
- 使用computer-use技能在Windows本机浏览器验收：bg05aa背景、模拟AI触发、CG铺满窗口、实际循环画面变化、CG中继续聊天、模拟AI退出、返回海边立绘；重载后恢复有效会话；控制台无error/warn。
- 临时配置页保存多个关键词成功，页面无CG审核复选框。真实DeepSeek自然判断质量**本轮未验证**。
- 测试临时库：1次enter、1次exit；结束后cg_sessions为0；player_choice日志为0；没有自动属性奖励。
- 发现并修复浏览器setTimeout非法this绑定问题：默认计时器改为箭头包装，节点测试与真实浏览器均复验通过。
- `python build_windows.py`成功；隔离LOCALAPPDATA下源码Doctor errors=0/warnings=1，EXE --doctor退出0；不将浏览器验收冒充完整原生EXE图形验收。
- 本轮真实DeepSeek调用0，没有额外训练/下载模型。原始游戏资源未修改；缓存仍只在character_exports。
- 验收截图：.tmp/cg-dialogue-fullstage.png（含私人本机资源，不纳入Git）。

## 尚未实现

原版推镜、旋转、光效、BGM/配音同步和完整原生E-mote仍未还原。当前为合成CG差分循环。
更多CG按用户提供的“角色、CG组、场景家族、关键词”逐一配置；不从编号猜剧情或地点。
跨包覆盖/不支持的IPT仍会提示不支持，不直接执行原游戏Lua。
下一步：用户在真实DeepSeek对话中观察海边事件的进入/退出语义；需要修正时先保存脱敏案例，用mock复现，避免反复收费试聊。
