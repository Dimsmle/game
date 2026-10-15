# Character Studio v0.11 — 架构说明

v0.11 在流式回复与原状态机之间增加 `studio/replies.py`（白名单句子列表、内存播放令牌）与
`web/reply_player.js`（逐句准备/展示/语音/中断）。最终回复只准备计划，不提交全部动作；
`/api/chat_segment` 按序激活当前句并保存已推进的文本前缀。见 `V0.11_SENTENCE_REPLIES.md`。

v0.10 在既有模块边界内新增 `studio/llm.py` → `app.stream_chat` → `web/chat_stream.js`，
以及 `studio/tts.py` / `tts_benchmark.py` 可选语音路径。舞台聊天的文字是暂定预览；完整 JSON
校验和版本/取消检查通过才提交到原 `behavior` / `runtime` / SQLite。
实施与真实验收边界见 `V0.10_AI_FOUNDATION.md`。不重写 Renderer 或记忆系统。

v0.8 在原架构上新增 `emote_mesh.py` → `studio/frame_sequence.py` →
`studio/web/frame_sequence.js` 的实验 CPU 点头链路。默认静态后端保留，已验收的
模型/表情序列由 Renderer 适配器优先用于对话；完整原生 E-mote 仍未实现。
具体实现、API、验收和边界见 `V0.8_LOCAL_RELEASE.md`。下文中的 v0.7 说明是原基线。

## 1. 核心原则

本项目把“角色想表达什么”与“底层如何画出来”分离。

```text
User text / ASR
      │
      ▼
LLM (speech + emotion + action_tag + scene + intensity)
      │  untrusted JSON
      ▼
studio.behavior
  - 枚举白名单
  - semantic emotion → actual expression preset
  - semantic action → reviewed PSB motion tag
      │
      ▼
studio.runtime
  - cooldown
  - priority
  - queue / interruption
  - speaking lifecycle
  - manual scene lock
      │
      ▼
Renderer contract (studio.renderers)
      │
      ├─ current: static_emote_preview
      ├─ future: frame_sequence
      └─ future: live2d_cubism
```

LLM 不允许直接选择文件、PSB 路径、系统命令、任意 URL 或模型资源 ID。

## 2. 当前真正的 Renderer

`static_emote_preview`

- `expressions = true`
- `motion_preview = true`
- `continuous_motion = false`
- `mesh_deformation = false`
- `masks = false`
- `physics = false`
- `lip_sync = three_state_png`

当前 `/api/expression_apply` 会：

1. 用选定面部预设产生完整静态帧。
2. 如果动作存在，从动作时间轴采样一部分 `move_ / head_ / body_ / act_ / arm_ / hair_ / quake_` 参数。
3. 叠加到面部预设上。
4. 分别生成 `normal / blink / talk` 三张缓存 PNG。

这避免“动作把面部重置成普通脸”，但**不解决 E-mote mesh/mask/physics**。

## 3. Runtime 状态机

`studio/runtime.py`

主要状态：

- `idle`
- `reacting`
- `speaking`

输入来源按优先级：

- `manual = 100`
- `event = 60`
- `ai = 40`
- `idle = 0`

每个动作标签有 cooldown，例如点头约 3 秒、挥手约 8 秒、靠近约 12 秒。
重复动作在 cooldown 内被抑制时，**表情仍可变化**。

低优先级动作在高优先级 reaction 期间进入最多 6 条的队列。
TTS 调用 `speech_start / speech_end`，不会把当前情绪重置为 neutral。

## 4. 场景优先级

v0.7 当前策略：

```text
手动场景（默认锁 30 分钟）
    > 定时事件 / AI 明确场景
    > 自动昼夜
```

手动切换场景时前端调用 `/api/runtime_event` 的 `scene_lock`。
自动昼夜检测到锁存在时不切换。

后续应把“剧情事件比手动锁是否更高”做成用户可配置策略，而不是硬编码。

## 5. 角色与服装模型

支持模型前缀：

- `kan`
- `tou`
- `say`
- `shi`
- `let`

`studio/model_meta.py` 存人工确认的信息：

```json
{
  "version": 1,
  "models": {
    "kan_10": {
      "display_name": "校服",
      "outfit": "school_uniform",
      "pose_family": "standing_a",
      "verified": true,
      "notes": "人工确认"
    }
  }
}
```

**禁止从 10、30 等数字自动推断服装/动作家族。**

## 6. 本机数据目录

Windows 默认：

`%LOCALAPPDATA%\CharacterLab\`

主要内容：

- `settings.json`
- `manifest.json`
- `history.sqlite3`
- `animation_tags.json`
- `model_metadata.json`
- `backgrounds/`
- `generated/`
- `backups/`

游戏原始/解包素材默认：

`G:\开发游戏\Amakano3_AI`

除 `character_exports` 缓存外，应把游戏素材根目录视为只读。


## 6.1 本机长期记忆

v0.7 只实现**用户明确确认**的长期记忆，不自动从聊天中永久提取事实。

SQLite `memories`：

- 最多 100 条
- 单条 1–500 字
- 可启用/停用
- 可删除
- LLM 每轮最多读取最近 12 条启用记忆，并限制总字符数
- 记忆不是行为指令；prompt 明确要求不得虚构未记录事实

未来如增加“AI 建议记忆”，建议流程必须是：

`模型提出候选 → UI 展示 → 用户确认 → 写入 SQLite`

而不是后台自动积累。


## 7. API 边界

### 角色行为

- `GET /api/behavior_catalog`
- `GET /api/behavior_export`
- `POST /api/behavior_import`
- `POST /api/behavior_tags`
- `POST /api/behavior_expression`
- `POST /api/chat`

### Runtime

- `GET /api/runtime`
- `POST /api/runtime_event`
  - `speech_start`
  - `speech_end`
  - `cancel`
  - `scene_lock`
  - `scene_unlock`

### Renderer/诊断

- `GET /api/renderer_capabilities`
- `GET /api/diagnostics`
- `GET /api/health`

### 模型/背景

- `GET /api/character_models`
- `POST /api/character_model`
- `GET /api/model_metadata`
- `POST /api/model_metadata`
- `GET /api/backgrounds`
- `POST /api/background_import`

所有 HTTP 只绑定 `127.0.0.1`。POST 检查 Origin，素材路径通过 root sandbox 校验。

## 8. Codex 新建 Renderer 的方式

不要把新后端逻辑写进 `sendMessage()`。

应实现一个新 adapter，并向 `studio/renderers.py` 报告真实 capabilities。

例如 Live2D：

```text
LLM behavior
    ↓
runtime accepted motion
    ↓
Live2DCubismRenderer.play_motion("nod")
    ↓
Cubism motion3 / expression3 / lip parameter
```

Renderer 如果不支持动作，必须返回 capability=false，并让行为层降级，不允许“UI 看起来晃了一下”就宣称是原版动画。

## 9. 当前测试边界

自动测试验证代码契约、HTTP、本地模拟 JSON/PNG、状态机和安全限制。

自动测试**没有**证明：

- Windows WebView2 在用户机器一定可用
- PyInstaller EXE 已成功打包
- DeepSeek 代理真实返回正确 JSON
- GPT-SoVITS 权重真实加载
- kan_10 最终视觉没有哭脸/遮罩错误
- E-mote 连续动画已实现

这些必须保留为本机验收项。
