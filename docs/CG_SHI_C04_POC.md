# ev_shi_c04：IPT 合成与舞台差分演出 POC

2026-10-15，基于本地主工程 85e9091，开发版本标识更新为 0.15-dev（不是稳定发布）。

## 已完成与实际入口

1. 正常重启 `main_desktop.py` 或 `dist/CharacterStudio/CharacterStudio.exe`，保留整个 dist/CharacterStudio 目录。
2. 游戏设置 → 玩法与素材审核 →「导入 ev_shi_c04 差分演出样例（待审）」。这会合成图片并登记待审媒体，不会勾选人工审核。
3. 可在审核页逐步预览；也可返回角色舞台 → 设置 →「CG差分测试预览（不解锁）」查看游戏内效果。
4. 玩家亲自核对后才能保存正式审核，选择媒体类型「CG差分演出」、适用角色卡，以及是否允许本地事件调用。没有自动创建事件、猜地点或增加好感。

舞台预览采用显式玩家操作、当前档案绑定与播放租约；关闭释放租约，角色舞台和聊天入口恢复。测试预览不写事件日记或解锁。
正式事件继续走原有「完整回复 ACK → 玩家选择 → 预加载 → GameStore 事务 → 解锁/演出」链路。

## 本机样例定位

来源：`G:\开发游戏\Amakano3_AI\assets_pfs_003\image\ev\ev_shi_c04`。
8 张完整画面：普通尺寸 _01～_06 共6张，高分辨率 zev_01/zev_06 共2张；其中6张通过 IPT 差分合成。
原脚本：`assets_pfs_004/script/1_shi_04-03.ast`，选择整份同名补充包脚本优先于 main 包；不执行任一脚本。
调用行：2063、2067、2146、2180、2243、2341、2376、2435、2497、2528。
另一个脚本中的回忆调用不串进这段演出。

合成缓存：`character_exports/cg_sequences/d43d1315521035f245b484fc/`，包含8张完整 PNG 和 sequence.json。
实际目录 key 随源素材/脚本内容改变；不能把固定 key 当作角色或事件编号。
本机像素核对：普通差分正确叠加；高分辨率底图 x=-320/y=-180 是父级摆放位置，不应误作差分图片的粘贴偏移。

## 有意不宣称完成的部分

- 当前为手动点击推进和交叉淡化；没有根据台词长度猜停留时间，更不是固定 FPS 动画。
- AST 中的 zoom、x/y、x2/y2、z2、rotate、ease 已记录为未支持，不冒充已还原原版镜头。
- BGM、音效、光效层、原作台词、分支跳转、配音同步均未导入。没有把原作剧情写进玩家的游戏事实。
- 只支持审查过的数据字面量和 IPT mode=diff；anime/特殊 Lua 模式拒绝。不能称为通用 Artemis 引擎。
- CG 组跨图片包覆盖时拒绝自动拼合，避免猜资源优先级；同名 AST 采用004优先，仍需后续针对其他版本核实。
- 最终仍需玩家确认素材是否适用于当前角色卡/场景；文件中的 shi 不会自动改写人物身份。

## 安全与存档

IPT 采用独立有限字面量解析器，拒绝函数、变量、额外代码、重复字段、越界路径/坐标、循环依赖和过大输入。
源图及脚本导入前后比对哈希；PNG/JSON 只原子写入本程序的 character_exports 派生缓存，禁止越界目录链接。
目录记录绑定清单哈希，清单绑定所有原始依赖及输出图；任一内容变化，预览/事件执行拒绝，要求重新导入。
重导入同内容保留既有人工审核；内容变化生成新ID、撤销旧候选在活动目录中的可用性，不转移审核或解锁。
客户端只拿不透明素材ID、帧URL、步骤和行号，不拿磁盘路径。LLM 不获得解析/文件操作权限。
差分小 PNG 带 IPT 时不能直接审核为完整 CG，需先导入合成结果。

## 修改文件

- 新增 studio/cg_ipt.py、cg_sequence.py：安全解析、合成、脚本定位、固定依赖清单。
- studio/gameplay_catalog.py、gameplay_core/media.py、gameplay.py：待审导入、cg_sequence 类型、帧/清单服务、无解锁预览；复用现有正式事件提交。
- 新增 studio/web/cg_sequence_player.js、cg_sequence.css：预加载、手动推进、交叉淡化、退出销毁。
- studio/web/game.js、gameplay_ui.js、gameplay.html、index.html、roleplay_plus/web/style.css、studio/app.py：接入审核/舞台/静态资源及隐藏控件修复。
- tools/import_cg_sequence.py：只生成派生缓存的离线工具，不写正式数据库。
- tests/test_cg_sequence.py、test_cg_sequence_player.js、test_gameplay_integration.py：解析/合成/失效/事件/预览/ABA/重导入回归。
- 05_自动运行项目测试.bat、AGENTS.md、VERSION、main_desktop.py、相关文档：测试入口、交接与开发版标识。

## 实测

- `.venv\Scripts\python.exe -m unittest discover -s tests -v`：301项，OK，2 skipped（Windows符号链接权限）。日志 .tmp/cg-final-tests.log。
- 10组 Node 回归通过：原9组 + `node tests/test_cg_sequence_player.js`；几何组仍含318用例。
- 新增/修改脚本 node --check 通过。
- 真实8张合成图生成成功；使用 computer-use 技能在本机浏览器检查审核预览、舞台预览、1～10全步骤推进、末步按钮禁用、关闭返回角色舞台。
- 浏览器使用临时数据库和离线 demo，未触碰正式私人存档。关闭后临时库 game_unlocks/game_event_choices/game_playback 全为0。
- 截图 .tmp/cg-shi-c04-stage.png，未纳入Git（包含本机游戏画面）。
- Doctor：隔离LOCALAPPDATA，errors=0、warnings=1（无选定角色）。
- Windows PyInstaller 构建成功；frozen EXE --doctor 退出0。没有做本轮 EXE 的完整原生窗口交互验收，不能把浏览器结果当作 EXE全验收。
- DeepSeek真实调用0；没有安装/调用TTS模型。原始游戏包、IPT、脚本和PNG未改写；新增的仅为派生缓存。

下一最小任务：玩家先查看样例画面与切换效果，确认后再还原这段脚本的镜头运动，并把已审核媒体绑定到一个合适的正式事件。
