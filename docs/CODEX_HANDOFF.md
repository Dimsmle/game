# CODEX HANDOFF — 从 v0.7 继续开发

## 当前基线

v0.7 的目标是把“可以在无用户 Windows/GPU/模型服务情况下可靠完成的架构”先补齐。
交接后，Codex 应优先处理**依赖本机真实素材和视觉验收**的问题，而不是重写基础框架。


## v0.7 额外已完成，不要重复重构

- 长期记忆是“用户显式保存”的 SQLite 条目，并有 `memory_enabled_for_llm` 隐私开关。
- TTS `speak()` 会等待音频真正播放结束，runtime 有 `speech_start/speech_end`。
- `action_token/active_behavior` 使后端队列出队能够真实驱动前端。
- reaction 完成后会回到同一 facial expression 的 expression-only 状态。
- 手动 scene lock 会阻止 AI / 定时事件 / 自动昼夜抢占。
- 表情缓存自动控制规模；不要删原游戏素材。
- `%LOCALAPPDATA%\CharacterLab\logs\app.log` 有脱敏运行日志，先看日志再猜异常。
- 当前模型高频操作采用单模型发现和 behavior catalog mtime 缓存，避免全目录重复解析。

## 第一轮必须先做

```powershell
python main_desktop.py --doctor
python -m unittest discover -s tests -v
node --check studio\web\app.js
python -u main_desktop.py --root "G:\开发游戏\Amakano3_AI" --list-models
```

把输出保存到开发记录。

## 第一优先：真实 kan_10 视觉验收

目标：解决“默认像哭脸、切表情主要只变嘴”等真实问题。

不要再改语义标签系统，先验证渲染层：

1. 在 `kan_10` 中选 8 个典型面部预设：
   - 普通
   - 微笑
   - 笑脸
   - 害羞
   - 不安
   - 悲伤
   - 愤怒
   - 惊讶
2. 每个预设单独输出透明 PNG。
3. 对比这些参数的 preset 值：
   - `face_eye_open`
   - `face_eyebrow`
   - `face_eyebrow_sp`
   - `face_eye_sp`
   - `face_hitomi_sp`
   - `face_mouth`
   - `face_mouth_sp`
   - `face_tears`
   - `face_cheek`
   - `face_eye_hi`
4. 确认错误泪水是：
   - 错误参数取样
   - sprite 离散切换
   - mesh/stencil/mask 缺失
   - Z order
   - 还是某个 preset 本身就开启 tears
5. 不要用“把泪水 PNG 永远隐藏”作为最终修复，因为哭泣表情仍要能显示泪水。

验收：普通/开心没有泪水；悲伤/哭泣按原 preset 决定；眼眉和瞳孔有明显差异。

## 第二优先：连续动作最小 POC

只挑一个动作：`うんうん`。

目标不是一次还原所有 20 个动作，而是证明：

- 0 → duration 连续采样
- 头/身体/服装不会散架
- 透明背景
- 目标 24–30 FPS
- 可中断
- TTS 期间嘴型可以叠加
- 播放完成回到同一个表情，不回 neutral

如果无法正确 mesh 渲染：
先尝试把一个动作导出成真实连续透明帧序列，接 `FrameSequenceRenderer`。
只有肉眼验收后才把该动作从 `preview_only` 改成 `playable`。

## 第三优先：服装 / pose family

用户将继续解 `kan_0..15`、`kan_30..45` 等 PSB。

使用 UI「系统 → 当前模型人工元数据」记录：

- display_name
- outfit
- pose_family
- verified
- notes

不要把区间写死。可以写一个**结构比较工具作为开发命令**，但它最终要输出人工审核候选，而不是又做一个独立统计产品。

建议比较：

- timeline label set
- object/motion key set
- parameter IDs
- chara bounds
- texture page count
- icon count
- mesh combinator structure hash

## 第四优先：真实 AI/TTS

使用用户本机：

- LLM：`http://127.0.0.1:15721/v1`
- GPT-SoVITS：通常 `http://127.0.0.1:9880/tts`

验收 30 轮对话：

- JSON 解析失败率
- emotion/action 是否自然
- 同一个显眼动作是否因 cooldown 不再每轮重复
- TTS 开始/结束 runtime phase
- 嘴型结束后是否保持原情绪
- 场景手动锁是否有效

不要把 API Key 写进源码、JSON、日志。

## 第五优先：Live2D POC

只有在确认可合法制作/使用角色素材后进行。

不是“转换 PSB”：

1. 选择一套合法角色图
2. 拆分/补绘为 PSD 图层
3. Cubism Editor rig
4. 导出 moc3/model3/motion3
5. 新增 `Live2DCubismRenderer`
6. 保持 `studio/behavior.py`、`studio/runtime.py` 不变

比较 E-mote POC 和 Live2D POC 的画质、时间成本、运行性能、维护和许可后再选长期路线。

## 不要做的事

- 不要重新做资源数量统计器。
- 不要把单帧 PNG 缩放/旋转叫“原版动画”。
- 不要直接把未知 PSB 编号写成“校服/私服/站姿”。
- 不要让 LLM 返回路径并直接读取。
- 不要提交游戏 PNG/JSON/PSB/OGG、聊天 SQLite、模型权重或 API Key。
- 不要为了“测试通过”删除能揭示真实缺陷的测试。

## 每一轮完成格式

Codex 回复应包括：

1. 变更文件
2. 解决的问题
3. 测试命令和结果
4. Windows/真实素材人工验收结果
5. 是否改写游戏素材
6. 尚未实现/风险
7. 下一步最小任务
