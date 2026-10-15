# v0.7 交接前状态更新

v0.7 已在原 v0.6 规划基础上完成以下 P1 基础设施：

- `studio/runtime.py`：idle/reacting/speaking、动作冷却、优先级、中断/队列、TTS 生命周期、手动场景锁。
- `studio/renderers.py`：Renderer capability contract；明确当前只有 static E-mote preview。
- `studio/diagnostics.py`：离线 Doctor。
- `studio/model_meta.py`：人工 outfit / pose_family / verified 元数据。
- 模型发现已从只支持 `kan_*` 泛化到 `kan/tou/say/shi/let`。
- 动作标签 JSON 支持导出、合并导入和自动备份。
- UI 新增“系统”页查看 runtime / renderer / diagnostics / 元数据。
- LLM prompt 会收到最近动作上下文，用于减少机械重复动作。

**因此 Codex 不要再把 P1 的“新建状态机/Renderer 接口”当成从零任务。**
下一步直接从 `docs/CODEX_HANDOFF.md` 的真实 kan_10 视觉问题和连续动作最小 POC 开始。

---

# Character Studio — 总体规划与 Codex 本地实施说明

**版本：v0.6（2026-10-14） · 主平台：Windows · 面向 Codex 的可执行项目规格**

> **阅读顺序：** 仓库根目录 `AGENTS.md` → 本文 → `README_先看.md` → 代码及测试。
> 项目目标不是重新制作或发布原游戏，而是一个读取使用者**合法持有、本机解包**素材的 AI 虚拟角色桌面程序。必须明确区分真正实现的功能、模拟行为、研究中的 E-mote 动画。

---

## 一、最终产品愿景

建立 Windows 原生窗口/透明桌宠，角色可以：

1. 在教室、卧室、街道等背景下显示游戏角色；拥有完整、可选择的服装。
2. 用户打字或说话，与 DeepSeek / OpenAI-compatible LLM 对话；长期记忆存在 SQLite。
3. **角色根据每次回答的语义和情景自主决定表情与动作**，不是单纯按输入关键词触发。
4. 语音使用用户自己的 GPT-SoVITS v2Pro 模型（例如 chitose）；TTS 音量驱动唇形/嘴部参数。可选 faster-whisper ASR。
5. 动作被打上“语义标签”，如 `nod`、`think`、`surprise`。LLM 只给语义标签，程序负责匹配已登记的实际动作资源。
6. 基于时间、用户指令、对话事件切换室内/室外/昼夜场景；动作、语音、背景可以协同。
7. 最终以独立 EXE 分发**软件源码及自行编写的资源**，游戏图片、音频、PSB、解包数据、模型权重不打包；使用者自己指定合法素材路径。
8. 如果原生 E-mote 无法高质量复现，可在独立渲染适配器中切换到**重做的 Live2D / Inochi2D 模型**，保留聊天、行为编排、记忆、声音和场景系统。

**优先级：真实人物正确显示与对话行为可信度 > 功能数量 > 报告工具。** 不再做单纯的素材数量扫描包。

## 二、已核实素材与仍未确认的推断

已由提供的 `kan_10.json` / `kan_10.resx.json` 核实：

- JSON 类型为 E-mote Motion；`metadata.timelineControl` 含 **128 套预设**，其中采用当前数据命名规则可分为 **108 个面部表情预设 + 20 个动作预设**。
- 真实动作名称包括 `待機`、`おさんぽ`、`はい`、`うんうん`、`いいえ`、`ありがとう`、`首かしげ`、`ん？`、`反応`、`びっくり`、`思考`、`上目遣い`、`あまえる`、`にっこり`、`あざとい`、`うん強`、`元気`、`近づく`、`仕草`、`キラキラ`。
- 面部变量包括 `face_eye_open`、`face_eyebrow`、`face_eye_sp`、`face_hitomi_sp`、`face_mouth`、`face_tears`、`face_cheek` 等；动作与脸部不该简单互相覆盖。
- **`kan_10.resx.json` 只映射 `0: kan_10/tex-texture.png`**。其它模型可能会使用 `tex#000-texture.png`、`tex#001-texture.png` 多图集，必须以具体模型的 `source` + `resx.Resources` 确定，禁止跨模型混贴。
- 当前静态组装无法准确复现网格变形、遮罩、物理和所有原版连续时间轴。表情“哭脸/嘴巴变化”问题不是一个 JSON 字段即可完全修好；必须走图层/网格/眼眉调试。
- 之前的 PFS 目录统计指出 `Amakano3.pfs.002` 的 `image/bg/` 下有 **185 张背景图片（105 PNG、80 JPG）**，但游戏素材不包含在本软件中。
- 使用者观察：`kan_0`–`kan_15` 可能是一类动作的不同服装；`kan_30`–`kan_45` 可能是另一动作类的对应服装。**这是待验证的推断，绝不能按编号硬编码。** 应从 PSB object/layer、motion label、相似衣物 atlas、空间 bounds、变量列表生成可人工审阅的动作家族映射。

本项目根目录默认素材路径（运行时可通过 CLI/UI 更换）：

```
G:\开发游戏\Amakano3_AI
```

## 三、技术架构（当前与目标）

```
PyCharm / Conda (开发)  ── PyInstaller (Windows EXE)
        │
        ▼
main_desktop.py  ── pywebview / Windows WebView2 独立窗口
        │
        ▼
studio/web/ (聊天、背景、角色、表情/动作标签编辑)
        │
        ▼
studio/app.py (本地 127.0.0.1 HTTP API、设置、SQLite、LLM/TTS/ASR)
        │
        ├── studio/behavior.py             本轮新增：规范化 LLM 意图 + 标签解析
        │       ├── emotion → E-mote 表情名
        │       └── action_tag → 实际动作时间轴 / 安全降级
        │
        ├── studio/backgrounds.py          本机背景导入、分类、场景
        ├── emote_model.py                 PSB JSON 模型节点/时间轴/变量
        ├── pose_renderer.py               近似静态 PNG 贴图合成
        └── [未来] renderer/               可替换渲染后端
                ├── emote_preview.py       当前仅单帧
                ├── frame_sequence.py      真实透明 PNG/WEBP 帧序列
                ├── emote_native.py        原版运行时兼容性研究
                ├── live2d_cubism.py       Cubism SDK for Web
                └── inochi2d.py           备选 2D rig 格式
```

**设计原则：不要让 DeepSeek、TTS、UI 直接处理原始 PSB 的资源索引。** 它们只调用统一语义标签和渲染器能力接口。游戏素材仍在 G 盘，用户偏好和标注存在 `%LOCALAPPDATA%\CharacterLab\`。

## 四、LLM 根据回复选择表情和动作

### 4.1 给 LLM 的契约

模型输出一个有效 JSON 对象，约定如下：

```json
{
  "speech": "嗯，我也觉得这件事值得认真想一想。",
  "emotion": "thinking",
  "action_tag": "think",
  "intensity": 0.7,
  "scene": ""
}
```

- `speech`：需要朗读的自然回复；不包括舞台指令。
- `emotion`：抽象情绪，后端映射到实际脸部预设。当前支持 `neutral`、`happy`、`gentle`、`shy`、`sleepy`、`surprised`、`sad`、`angry`、`worried`、`thinking`、`crying`、`playful`、`confident`、`grateful`。
- `action_tag`：动作语义。例如 `nod`、`agree`、`think`、`surprise`、`thank`、`tilt_head`、`walk`、`approach`、`celebrate`、`idle`。合法值统一维护于 `studio/behavior.py:ACTION_TAGS`。
- `intensity`：0–1；在**当前版本仅记录**，以后可映射动作力度、表情权重，不能冒称已经真实控制网格。
- `scene`：空字符串或 manifest 中**已经登记**且有图像的场景 ID。不得随意创建或读取文件。

程序不允许大模型指定 PSB 文件路径、系统命令、随意打开网址或编辑游戏资源。参数非法 → `neutral/idle` 或记录原因后降级。

### 4.2 编排顺序（单轮）

1. 获取用户输入和最近对话记忆；加人设、时间/地点、角色当前状态信息。
2. LLM 产生语音文本 + 情绪/动作语义/场景建议（当前程序已实现结构化约定）。
3. `behavior.normalize_llm_reply` 解析、枚举白名单校验；拒绝路径/未知标签。
4. 查询当前服装模型的 PSB 预设和可编辑动作标注（`%LOCALAPPDATA%\CharacterLab\animation_tags.json`）。
5. `behavior.resolve_behavior` **独立**映射面部表情和身体动作，输出选中项、预览能力与降级原因。
6. 前端 `applyBehaviorPlan` 通过 `/api/expression_apply` 生成面部+部分身体变量的**近似单帧合成**；若不存在动作，保持面部，不能假装动作成功。
7. GPT-SoVITS 播放音频，嘴型/眨眼作为独立叠加层；不得因 `talk` 重置表情/服装。
8. 背景按手动、剧情事件、时段和 LLM 允许场景的优先级切换。
9. 对话写入 SQLite；成功/缺失动作分别输出调试事件，便于后续动作追踪。

### 4.3 动画选择逻辑（当前已经具备）

实际示例：

```
情景：角色答应用户的建议
LLM → emotion=happy, action_tag=nod
本地面部映射 happy → 笑顔Ａ
本地动作标签 nod → うんうん
结果：笑顔Ａ + うんうん 的中段动作参数静态采样
能力提示：static_emote_frame_preview（不是原版动画）
```

若 LLM 返回 `action_tag=wave`，而库中无标注 `wave` 的动作，则只显示表情，**不会冒用无关动作**。

### 4.4 人工给动画打标签

打开桌面程序 → 工作台「表情/动作」 → 「动作时间轴」 → 选真实动作，例如 `うんうん` → 在“动作标签”填写 `nod, agree` → 保存。

同理 `思考` 可标 `think`；没有与“挥手”真正对应的动作时，不应仅因它外观似挥手而自动贴上 `wave`，需要用户人工验收。

现在程序默认给上面 20 个已知预设一些初始标签（“seed”），但**初始标签只是供核对的候选，不代表经过动作播放实证**。人工保存后标记来源 `manual`，优先于默认映射。

表情映射也能在界面里改成指定实际脸部预设。

### 4.5 数据格式（自动保存，给 Codex 编辑）

`%LOCALAPPDATA%\CharacterLab\animation_tags.json` 的一个示例：

```json
{
  "version": 1,
  "models": {
    "kan_10": {
      "motion_tags": {
        "うんうん": {"tags": ["nod", "agree"], "sample_time": 30},
        "思考": {"tags": ["think"], "sample_time": 45},
        "首かしげ": {"tags": ["tilt_head", "curious"], "sample_time": 25}
      },
      "expression_map": {
        "happy": "笑顔Ａ",
        "worried": "不安Ａ",
        "thinking": "考えるＡ"
      }
    }
  }
}
```

`sample_time` 只能是当前动作时间轴合法帧范围之内，不能随意填写。JSON 里只存**本模型合法的预设名称与标签**，不存游戏纹理本体。

API：

- `GET /api/behavior_catalog` — 当前模型各预设、标签、可播放能力。
- `POST /api/behavior_tags` — 人工保存 `{label, tags, sample_time}`。
- `POST /api/behavior_expression` — 保存 `{emotion, label}`。
- `POST /api/chat` — 返回 `{speech, emotion, action_tag, scene, behavior, ...}`。
- `POST /api/expression_apply` — 接受 `{label,time,motion_label?,motion_time?}`，产生当前静态图片三态 `normal/blink/talk`。

### 4.6 未来完整动作播放器（**尚未实现**）

把动作清单延伸成：

```json
{
  "id": "kan:agree_short",
  "tags": ["nod", "agree"],
  "source_model": "kan_10",
  "source_motion": "うんうん",
  "renderer": "emote_native_or_sequence",
  "loop": false,
  "priority": 40,
  "interruptible": true,
  "duration_ms": 1200,
  "validation": "manual_reviewed"
}
```

**必须把 `playback_status` 从 `preview_only` 升为 `playable` 之前，先有实际连续帧/运行时证据。** 不能把 `sample_time` 当成已解出的动画文件。

## 五、动作调度器与冲突处理（Codex 后续实现）

建议统一“角色状态机”，至少定义：

- `idle`：待机常驻，低优先级、可中断。
- `reaction`：说话前后的点头、惊讶、害羞、思考等动作，短时高优先级。
- `speaking`：嘴型根据 TTS 振幅变化；与头部和身体动作叠加，不抢占面部情绪。
- `manual_override`：用户点击明确动作/表情时临时覆盖 AI 推断。
- `scene_transition`：背景切换；不因服装变化重置聊天记录。
- `outfit_transition`：加载整套服装模型及其纹理、预设、缓存；保持当前语义情绪，再在新模型中寻找对应表情与动作。

优先级建议（需在设计中配置，而非散落的 `if`）：

```
用户手动锁定/重大系统安全限制
      > 明确剧情事件
      > 当前需要完成的短动作
      > AI 推荐动作
      > 眨眼/呼吸/待机
```

后续支持“动作队列 + 超时 + 中断 + 音频生命周期回调”，避免连续发消息导致旧动作覆盖新动作。相同情绪的动作不宜每次都重复触发；可加入冷却时间。

在当前实现中，话语对应**一个**情绪和一个动作标签。未来可以定义 `beats[]`，对长回复按句子切换情绪，但不要在稳定单轮之前贸然引入。

## 六、角色、服装、动作家族与可替换渲染器

### 6.1 数据模型

```
CharacterProfile
 ├─ character_id = kan
 ├─ role/persona, voice_profile, memory_database
 ├─ outfits[]              校服、私服等（需实际看模型资源，不从编号猜）
 ├─ action_families[]      正面站立、近景、移动……由 PSB 数据验证
 └─ active_outfit + active_action_family
        └─ renderer model + atlas page(s) + animation bindings
```

对用户提出的 `0–15` 和 `30–45`：
先采集各 `kan_N.json` 的时间轴标签、层级和顶点数据的**结构特征签名**，
人工验证一组确实只有衣服不同且动作兼容后，才设 `action_family`。
切换模型不能拿 `kan_10` 的 atlas 去读 `kan_30` 的 resource index。

### 6.2 标准渲染器接口（待实现）

```python
class CharacterRenderer:
    def load(self, model_config): ...
    def capabilities(self): ...     # supports_mesh, expressions, lip_sync, motions
    def set_expression(self, semantic_emotion, weight): ...
    def play_motion(self, motion_id, *, priority=0, loop=False): ...
    def set_lip_amplitude(self, value_0_to_1): ...
    def update(self, dt_seconds): ...
    def capture(self): ...
    def dispose(self): ...
```

未来三类实现可互换：

- `StaticEmotePreviewRenderer`：**现在有**，只能单帧近似表达，用于调试/兼容。
- `FrameSequenceRenderer`：透明帧序列 + 帧率/循环/混合，作为可交付的连续动作中间路线。需要真实生成/手工确认帧，不是把一张 PNG 无限晃动。
- `NativeEmoteRenderer`：尝试官方或兼容 runtime；重点研究 mesh/遮罩/物理/插值。使用运行时前必须确认合法授权、ABI、Windows 兼容性。
- `Live2DCubismRenderer`：使用合法制作的 `.moc3` + `.model3.json` 和 Cubism SDK for Web；不应假设 PSB JSON 可直接转换成 `.moc3`。
- `Inochi2DRenderer`：开放格式备选，仍需单独 rigging，不会自动兼容 Cubism。

## 七、能不能做成 Live2D？**可以，但是重建模型而不是格式重命名**

### 路线 A — 继续还原原版 E-mote
优点：若找到合法且稳定的运行时，有希望保留原版动作、网格、表情与服装结构。
主要难点：PSB 仅是提取数据；E-mote meshCombinator、时间轴、遮罩与物理与 Cubism 不同。
用户现有 `PsbDecompile` 可导出 JSON/PNG，但并没有证明 FreeMoteViewer 可播放原生动作。
建议：先挑一个 `kan_10` 的简单动作 `うんうん` 和 1 个表情做对照测试，
验证连续 1–2 秒画面，而不是一次性重写全部 E-mote。

### 路线 B — Live2D Cubism（推荐的独立概念验证）
1. 使用授权的原始图像或人工整理图集，把脸、眼、眉、瞳孔、嘴、头发、躯干、衣物重建为**单独的透明图层**；原游戏图集坐标不等于已还原完整遮挡关系。隐藏部分可能需要补绘。
2. 使用 Photoshop 或 CLIP STUDIO PAINT 制作符合 Cubism 导入要求的 **RGB / 8bit PSD**。
3. 在 **Live2D Cubism Editor** 导入 PSD；为各层生成 ArtMesh，建立面部与身体 Deformer、Parameter 以及物理和服装/发丝驱动。
4. 先制作 7–10 种常用面部表情 + 5 个短动作（点头、歪头、摇头、轻摆、靠近），再扩展。
5. 导出 `.moc3`、`.model3.json`、贴图、`.motion3.json`、`.physics3.json`（或 `.exp3.json` 等）；以 Cubism SDK for Web 集成到 pywebview 内的前端图形舞台。
6. `studio/behavior.py` 和动画标签系统完全复用：例如 `nod → nod.motion3.json`、`happy → smile.exp3.json`，只是底层 Renderer 更换。
7. 检查 Live2D 软件和 SDK 的适用许可、用户对作品形象的改编/分发许可；不可未经授权公开发布从游戏资产直接制作的新模型。

**不支持“PSB/PNG → 一键转标准 Live2D 模型”作为项目承诺。**
`.moc3` 不是 PSB 的另一种 JSON 封装，网格参数与变形关系需要重新制作与验证。

### 路线 C — Inochi2D
开源 Inochi Creator 可以将分层贴图 rig 成另一种 2D puppet，更适合愿意使用开放技术栈、
且愿意单独制作模型的情况。但它**不兼容已有 Cubism/Live2D 模型**，也不会自动转换 E-mote PSB。
应先做 1 个小样，比较画质、工作量和 Windows 嵌入方式。

**路线决策建议：** 先完成“LLM 语义动作标签 → Renderer 接口”后，再并行做两个 1 分钟 POC：
E-mote 原版动作小实验 vs. Live2D 手工 rig 小实验；用可运行视频/帧对比决定哪条长期路线。

参考官方文档（请 Codex 在实现 SDK 时重新核实版本、许可、运行时文件）：
- Live2D PSD 输入与图层： https://docs.live2d.com/en/cubism-editor-manual/psd-import/
- Live2D 材质拆分： https://docs.live2d.com/en/cubism-editor-manual/divide-the-material/
- Live2D 模型/动作导出： https://docs.live2d.com/en/cubism-editor-manual/export-moc3-motion3-files/
- Live2D Web SDK Motion： https://docs.live2d.com/en/cubism-sdk-manual/motion/
- Inochi Creator： https://docs.inochi2d.com/en/latest/creator/about.html
- Inochi2D 兼容性说明： https://docs.inochi2d.com/en/latest/inochi2d/faq.html

## 八、场景、语音、记忆与 Windows 桌面

### 场景
- 原版 `image/bg/` 背景自动发现与缩略图、导入外部背景已写入 `studio/backgrounds.py`。
- 支持 `day` / `evening` / `night` / 自定义地点；`cover/contain`；定时切换和 AI 申请场景切换。
- 后续：场景库应存位置 `location_id`、昼夜 `time_of_day`、天气 `weather`、同地点多背景及景深，而不是把“同一房间的昼夜”视为毫无关系的场景。
- **优先级**：手动选择 > 明确剧情事件 > AI 推荐 > 电脑时间自动场景。当前版本只部分实现，Codex 后续应实现“手动锁定/释放”。

### 语音
- DeepSeek/OpenAI-compatible：`http://127.0.0.1:15721/v1` 是用户原先使用的代理地址；`model` 填代理实际支持的 ID。
- GPT-SoVITS v2Pro：使用既有的 `api_v2.py /tts` 服务及参考音频、语言，不把权重打包进 EXE。
- ASR：可选本地 faster-whisper / FFmpeg。
- TTS 返回音频后先验证播放/解码成功，再以实时振幅/phoneme 控制 `mouth_open`；音量阈值需平滑、门限和静音关闭。
- **关键**：说话时不应重置当前 `emotion` 或强迫动作换回普通脸。说话结束时恢复相同情绪的非说话嘴部状态。当前系统只有简化口型采样和音量驱动，需继续实测。

### 记忆
- SQLite 历史有基础实现。后续增加人格/用户偏好/场景长期状态、可选择删除、近期摘要，避免无限上下文。
- 用户配置和对话数据库默认只在本机。
- API 密钥走环境变量（如 `LLM_API_KEY`），不能在日志或 GitHub 提交中打印。
- 网络请求只向用户显式配置的模型地址发送文本，离线演示模式不得宣称正在使用 DeepSeek。

### 桌面与 EXE
- 开发：PyCharm + Conda Python 3.11。
- Windows UI：pywebview / WebView2。
- 当前有 PyInstaller `build_windows.py`，**需在用户 Windows 上执行和实际验收**。
- 最终增加可调整大小、系统托盘、透明/点击穿透桌宠窗口、开机启动可选和明确的退出动作。
- 路径配置、模型选择、缓存迁移不应该因为版本更新而丢失。

## 九、迭代计划与验收标准

### P0（当前：行为系统已落代码；继续本机验收）
- [x] 结构化 LLM `speech/emotion/action_tag/scene/intensity`。
- [x] 为 kan_10 已知 20 个动作预设添加**候选**语义标签。
- [x] 手动编辑与本地保存标签和情绪映射。
- [x] 自动选择合法表情与动作，明确降级状态，不执行模型给的路径。
- [x] 聊天时保留面部预设，并叠加可支持的头部/身体/移动参数单帧。
- [ ] **用户 Windows 现场验收**：`kan_10` 下“开心+点头”“思考+思考”是否有可辨的变化、有没有错误哭脸。
- [ ] 切换另一个服装模型后同样的语义映射是否切到它自己的真实预设。
- [ ] 实际 DeepSeek 代理和 GPT-SoVITS 服务联调，测量响应时间和嘴型质量。

### P1（Codex 最先要实现）
- [ ] 为 `animation_tags.json` 加 GUI 导入/导出、批量验证、备份、可撤销修改。
- [ ] 将 action tags 转成明确动作队列与播放状态机：idle/react/speaking/interrupt/cooldown。
- [ ] 增加可测试的 `CharacterRenderer` 接口和 `StaticPreviewRenderer` 实现。
- [ ] 把背景/人物场景 `state.json` 与语义动作解耦，避免手动选择被后台定时覆盖。
- [ ] 增加 30 轮对话单测：每轮 JSON 合法、不会调用不存在资源、动作过期不会乱入。
- [ ] UI 显示动作的 `sample_only/playable/missing` 状态，并能点击“重试/回退”。

### P2（动作家族与原生 E-mote）
- [ ] 对合法取得且已经解包的多套 PSB，建立 `pose_family`/`outfit`**人工审核**表。
- [ ] `kan_10` 简单动作的 meshCombinator、屏蔽区域、顶点插值与 Z 深度逐项验证。
- [ ] 输出连续 24/30/60 fps 的真实或近似帧序列，提供差异可视化；如果模拟会明显破坏人物，不要静默替代。
- [ ] FrameSequenceRenderer 支持队列、优先级、淡入淡出、眨眼和音量嘴型叠加。
- [ ] 为所有原始动作打上可信度 `inferred/reviewed/playable`，不要只根据日文名称认定质量。

### P3（Live2D POC，和 P2 可以并行）
- [ ] 选择一个已获许可的角色立绘，整理 30–60 个左右合理的可动部件（具体数量按画面要求定）。
- [ ] 制作 RGB 8-bit PSD，Cubism Editor 成功导入，具备眼睛/嘴/头/身体控制。
- [ ] 输出 `.moc3/.model3.json`、至少 3 个 `.motion3.json` 动作。
- [ ] 在 WebView2 场景中使用 Cubism SDK for Web 显示模型并切换语义标签。
- [ ] 与原版 E-mote 重建的小样比较人物精度、动作质量、性能、维护和法律条件，决定正式方案。

### P4（可日用 EXE）
- [ ] 角色造型/动作/场景/声音配置 GUI，可备份、升级。
- [ ] 系统托盘和透明桌宠窗口。
- [ ] 缺失游戏资源时给出明确安装指引，不崩溃、不泄露路径。
- [ ] 错误日志、性能指标、TTS 延时统计和离线降级。
- [ ] Windows 构建/启动测试和 EXE 分发包验收。

### 阶段发布门槛

**最低可用版本**必须达成：人物穿衣正确、基础表情清楚、AI 回复与语音可用、动作状态可靠、背景切换不乱跳、设置可保存。
**动态角色版本**必须有真实可验证的连续帧/模型参数更新，不允许仅更名“Live2D”或循环缩放单张 PNG。

## 十、本地 Codex 操作手册

在 PyCharm 或普通 PowerShell 中进入**本项目根目录**（不是游戏素材目录）：

```powershell
conda activate lunwen2
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -u main_desktop.py --root "G:\开发游戏\Amakano3_AI" --list-models
python main_desktop.py --root "G:\开发游戏\Amakano3_AI" --model kan_10
```

如需 Windows EXE：

```powershell
python -m pip install -r requirements-build.txt
python build_windows.py
```

注意之前出现过 Conda 终端“无输出/目录无效”，重启后已恢复；如果 Python 本身没有输出，先排查终端环境，不要修改角色渲染代码。

**给 Codex 的首条任务（可直接复制）：**

> 请先阅读根目录 `AGENTS.md`、`docs/CharacterStudio_总体规划及Codex实施.md` 和 `studio/behavior.py`。在不破坏当前 Windows 主入口、DeepSeek/GPT-SoVITS、背景图库、多纹理 PSB 的前提下，完成 P1 的行为调度器最小实现：`idle/react/speaking` 状态和动作队列的确定性状态转移、超时/取消/冷却时间，加入充分的自动化测试。不得宣称单帧 E-mote 预览是原版连续动画。请先运行测试、记录现有问题、修改代码、再次运行测试，并给我准确的文件变更和本机需要验收的操作步骤。

**Codex 每一轮的验收输出必须包含：**
- 修改了哪些文件，解决的是哪个真实问题。
- 已运行哪些命令，具体通过/失败。
- 是否涉及用户 G 盘数据，是否会改写原始素材。
- 未实现功能列表和风险。
- 下一步需要用户验证的明确操作。
- 不得未经用户授权提交游戏原版素材到 GitHub。

### 安全与版权约束

- 只读取合法取得的原版资源；工具包中**不要放**游戏模型 JSON、原版纹理 PNG、原版配音、游戏 PFS/PSB、声优训练素材或授权不明的权重。
- `.gitignore` 排除资产目录、`%LOCALAPPDATA%`、数据库、密钥。提交前必须人工查看 `git status`。
- 角色模型及声音的再创作、公开分享/商用需要分别核对权利人、游戏素材、配音演员及软件 SDK 许可。
- 永远不要隐藏当前渲染质量缺陷，不要把错误泪水/衣服错位说成“正常”。
