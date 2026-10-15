# 状态与叙事权限边界

当前交付仅 v0.12 P0/P1。v0.13 设计包已阅读；P1.5a / P1.5b 是接下来的两个独立阶段。

## 已实现

现有 DeepSeek SSE → JSON 校验 → ReplyTurn 内存令牌 → 顺序激活句子 →
保存已读前缀/提交角色表情。后续台词仍不提前写入历史；停止、换模型原有防护保留。

本轮 settings 快照增加 game_session（档案 ID+持久化 generation）与 GameState。
新档案/切换不更改模型、角色名字、人设、API Key。切换档案时取消旧生成、清空旧
ReplyTurn、重置 Runtime；切回相同档案也因 generation 不同而不能复活旧结果。
流式与兼容聊天都读取紧凑状态提示，不从回复回写属性、flags、地点或里程碑。
兼容聊天在回复完成后再次校验快照，用户与角色消息按档案在同一事务保存。

聊天与记忆按 profile_id 过滤；清空历史仅清理当前档案。记忆隐私开关保留。
旧的纯角色 persona 仍是角色资料，不是玩家 Persona，不在 P1 中重新解释它。

AI scene 字段暂时清空，防止未经玩家选择提前换场；玩家手动背景切换仍保留。
手动视觉背景不是已审核 LocationCatalog，HUD 如实显示“尚未登记”。

## 后续计划，尚未实现

P1.5a：CharacterCard / 玩家 Persona / 六种叙事预设、旧设置迁移、版本绑定和编辑 UI。
P1.5b：Lorebook 条件激活、唯一 PromptComposer、估算预算和默认脱敏 Prompt 检查器。
当前 prompt 仍在两个兼容入口中组装，P1.5b 再统一，不能宣称已有统一 Composer。

P3 才增加事件提议、PendingTurnOutcome、最后一句实际显示 ACK 和事件选择卡。
LLM 只能提出本地合格 event_id，先校验再暂存；不直接产生任何数值或媒体副作用。
用户读完并选择后，EventCommitService 才调用本地审核规则和 SQLite 事务。
拒绝不惩罚；ACK/choice 幂等。没有候选、取消、资源未验证时不执行事件。

CG、触摸、世界时间、故事目标、长期叙事摘要、完整 E-mote 和 Live2D 不属于本轮实现。
禁止把角色卡、世界书、预设或 AI 输出当作文件、SQL、网络或 API Key 操作权限来源。
