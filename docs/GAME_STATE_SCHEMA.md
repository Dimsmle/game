# GameState schema 1 — v0.12 P1

沿用 `%LOCALAPPDATA%\CharacterLab\history.sqlite3`，不另建正式数据库。
旧库 user_version=0 → 1：先用 SQLite backup API 生成完整一致快照，再在
BEGIN IMMEDIATE 中创建表、增加 profile_id、建立索引并更新版本。任一步失败回滚
DDL 和数据；较新数据库版本拒绝打开。第二次启动不重复迁移或备份。
正式库可能被旧进程使用，建议退出旧窗口再运行新版。

新增 game_profiles、game_state、game_session、game_journal。
event_instances/event_choices 仅为未来迁移脚手架，没有 P3 事件执行功能。
已有 messages/memories 的原字段、主键和正文不变，新增 profile_id 默认 default。
创建“原有存档”，保留所有旧记录与记忆启用状态；新档案为空白历史/记忆。

状态字段：

| 字段 | 规则 |
| --- | --- |
| schema | 严格整数 1 |
| profile_id / character_id | 1–80 位字母、数字、下划线或连字符；不是文件路径 |
| revision | 非负整数；更新需核对预期版本 |
| affection / trust / energy | 严格整数 0–100，初值 25/30/80 |
| mood | 严格整数 -100–100，初值 15 |
| relationship_stage | acquaintance / familiar / close / intimate / committed |
| milestones | 本地白名单；阈值与前置里程碑都满足才升级，不因短期波动撤销已得阶段 |
| flags | 最多 100 个安全 ID；值为布尔或受限整数；本轮无公共写入口 |
| scene | 初始 unknown / unknown / false；不猜测现有背景的地点、时间语义 |
| event / clock_mode / toggles | 本轮只允许 idle / manual / 主动事件和触摸均 false |

单次增减上限：好感/信任 ±5、心情/精力 ±20。正向每日预算：5/5/30/40。
这是一组 P1 明示的初始本地规则，不是已接入的事件奖励，也不是模型可设置的参数。
接收的合法增量还会按全局上下限和每日剩余额度 clamp；拒绝 bool、float、未知键和
超大单次增量。仅同日已提交日志计入预算，负向变化不返还正向额度。
没有未登录惩罚，也不因普通聊天自动加减属性。

`GameStore.commit_effect()` 只给后续本地审核规则使用，P1 没有 HTTP/LLM 调用路径。
一个事务核对 revision、检查幂等键/请求一致性、计算额度、更新状态、写 before/after
日志后提交。重复相同请求返回第一次结果，不重复写日志；相同 key 不同效果拒绝。

API：

- GET `/api/game/state`：当前档案的安全状态，不返回配置、密钥或绝对路径。
- GET `/api/game/profiles`：列表、当前档案和切换代次。
- POST `/api/game/profile`：仅 create 的 id/display_name，或 select 的 id；拒绝额外字段。
- POST `/api/game/backup`：空对象，备份整个本机 DB；只返回不透明 backup_id。

备份包含全部存档的私人聊天，保存在同数据目录 backups，不通过静态文件路由下载。
本轮没有图形恢复/回档入口；失败迁移自身会事务回滚，并保留迁移前完整备份。
HUD 显示/隐藏当前只在窗口会话内有效。多窗口共享一个活动档案，前端最多 10 秒
轮询同步，服务器对旧 ReplyTurn 立即拒绝；不是每窗口独立会话。

character_id 暂为 legacy_character，不把媒体代码 shi/kan 推断为原作人物身份；
后续 P1.5a 用版本化角色卡显式绑定，不因换衣服自动复制/改写关系状态。
