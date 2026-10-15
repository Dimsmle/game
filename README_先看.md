# Character Studio v0.7

Windows 本地 AI 虚拟角色桌面程序。当前工程基线已经把**对话、语义表情/动作、PSB 静态近似预览、多造型、背景、TTS/ASR 接口、运行状态机和未来 Renderer 接口**整合到一个项目中。

> 这不是原版 E-mote 播放器。当前 E-mote 路线只能从 PsbDecompile 的 JSON/纹理生成近似静态帧，并采样一部分动作变量。完整 mesh、mask、physics、连续动画仍未实现。

## 先运行

建议 Windows + Conda Python 3.11：

```powershell
conda create -n character-studio python=3.11 -y
conda activate character-studio
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main_desktop.py --doctor
python main_desktop.py --root "G:\开发游戏\Amakano3_AI" --list-models
python main_desktop.py --root "G:\开发游戏\Amakano3_AI" --model kan_10
```

PyCharm 运行配置：

- Script path：`main_desktop.py`
- Working directory：项目根目录
- Interpreter：同一个 Conda 环境
- Parameters：可留空；默认素材根目录为 `G:\开发游戏\Amakano3_AI`

## v0.7 已完成的工程能力

### 对话 → 表情/动作

LLM 不直接指定 PSB、文件路径或命令，只返回受限语义：

```json
{
  "speech": "嗯，我也觉得可以试试看。",
  "emotion": "happy",
  "action_tag": "nod",
  "scene": "",
  "intensity": 0.6
}
```

本地程序再把 `happy → 笑顔Ａ`、`nod → うんうん` 等映射到当前模型实际存在的时间轴。映射可在 UI 中人工修正，保存在：

`%LOCALAPPDATA%\CharacterLab\animation_tags.json`

### 运行状态机

`studio/runtime.py` 管理：

- `idle / reacting / speaking`
- 动作冷却，避免每句话重复点头/惊讶
- 高优先级动作中断、低优先级排队
- TTS 开始/结束生命周期
- 当前情绪保持
- 手动场景 30 分钟锁定，避免自动昼夜立即抢回
- 运行历史与可诊断快照

### Renderer 契约

`studio/renderers.py` 明确区分：

- `static_emote_preview`：当前真正可用；静态采样
- `frame_sequence_target`：规划中的透明帧连续播放
- `live2d_cubism_target`：规划中的 Live2D 后端

UI「系统」页会直接显示当前后端到底支持什么，不会把单帧预览写成“原版动画”。

### 角色 / 服装 / 动作家族

已支持模型代码：

`kan / tou / say / shi / let`

模型编号不再默认等于服装或动作。`studio/model_meta.py` 提供人工元数据：

- 显示名：例如“校服”
- `outfit`：例如 `school_uniform`
- `pose_family`：例如 `standing_a`
- `verified`：是否已经人工看过
- 备注

保存到：

`%LOCALAPPDATA%\CharacterLab\model_metadata.json`

因此以后可以验证“0–15 是同动作不同衣服、30–45 是另一个动作家族”的猜想，但**不会按编号硬编码**。

### 背景

- 自动发现本机 `image/bg`、`assets/image/bg` 等背景目录
- PNG/JPG/WEBP 导入
- 白天/傍晚/夜晚 + 自定义地点
- Cover / Contain
- 自动昼夜
- AI 可请求已登记场景
- 手动选择优先，并由运行状态机临时锁定

### AI / 语音

已保留：

- OpenAI-compatible / DeepSeek 代理接口
- GPT-SoVITS `/tts`
- 可选 faster-whisper + FFmpeg
- SQLite 最近聊天历史
- 可选 Images API 场景生成

真实模型和 TTS 服务必须在用户 Windows 本机联调；本项目测试不会假装已经连接成功。

### 本机长期记忆

系统页可以手工保存用户希望角色长期记住的内容。记忆存入同一个本机 SQLite，
可以逐条停用或删除。当前版本**不会自动从聊天永久提取事实**，避免模型误记。

启用的记忆会在真实 LLM 模式下作为少量上下文发送给你配置的模型服务；
如果该服务不是本机服务，应把这视为一次正常的模型请求数据发送。
设置窗口有独立开关，可保留本机记忆但禁止把它们加入 LLM 请求。

### 缓存与运行日志

表情/动作单帧预览缓存位于素材根目录的 `character_exports/expressions/`。
v0.7 会把这里限制在约 360 张最新 PNG；它只清理 Character Studio 自己生成的缓存，
不会删除原始 PSB/PNG/JSON。

后台运行日志：

`%LOCALAPPDATA%\CharacterLab\logs\app.log`

日志约 1MB 时自动轮转，只记录接口状态和错误摘要，不记录聊天请求正文或 API Key。
窗口「系统」页可以直接查看最近日志。

### 配置迁移和自检

系统页支持：

- 动作标签 JSON 导出
- 动作标签 JSON 合并导入
- 导入前自动备份旧文件
- 离线 Doctor
- 当前运行状态
- Renderer capabilities
- 模型服装/动作家族元数据

CLI：

```powershell
python main_desktop.py --doctor
```

Doctor 不会主动访问互联网、DeepSeek 或 TTS，只检查本机环境。

## 目录

```text
CharacterStudio/
├─ main_desktop.py            # Windows 主入口
├─ emote_model.py             # PSB JSON 时间轴/纹理结构
├─ pose_renderer.py           # 当前静态近似合成
├─ desktop.py                 # Tkinter 128 时间轴调试器
├─ build_windows.py           # PyInstaller 构建
├─ studio/
│  ├─ app.py                  # 本地 HTTP、SQLite、AI/TTS/ASR
│  ├─ behavior.py             # LLM 语义 → 游戏预设
│  ├─ runtime.py              # 状态机、冷却、队列、场景锁
│  ├─ renderers.py            # Renderer 能力契约
│  ├─ model_meta.py           # 人工服装/动作家族元数据
│  ├─ backgrounds.py
│  ├─ diagnostics.py
│  └─ web/
├─ tests/
├─ docs/
│  ├─ CharacterStudio_总体规划及Codex实施.md
│  ├─ CODEX_HANDOFF.md
│  ├─ ARCHITECTURE.md
│  └─ kan_10_动作标签候选清单.md
└─ AGENTS.md
```

## Windows EXE

```powershell
python -m pip install -r requirements-build.txt
python build_windows.py
```

输出目录：

`dist\CharacterStudio\CharacterStudio.exe`

必须在 Windows 上构建和验收；PyInstaller 不能从本环境交叉生成 Windows EXE。

## 给本地 Codex

先让 Codex 阅读：

1. `AGENTS.md`
2. `docs/CharacterStudio_总体规划及Codex实施.md`
3. `docs/CODEX_HANDOFF.md`
4. `docs/ARCHITECTURE.md`

然后跑完整测试。不要先重写 UI，也不要再次建立资源统计器。

## 最重要的未完成项

1. **原生连续 E-mote**：mesh / stencil / mask / physics / timeline interpolation。
2. **Live2D POC**：需要合法的分层 PSD 与人工 rig，PSB 不能直接变成 `.moc3`。
3. **真实 kan_10 画面验收**：错误哭脸、眼眉/泪水/遮罩必须在 Windows 实际素材上继续比对。
4. **DeepSeek + GPT-SoVITS 真实联调**。
5. **Windows EXE / WebView2 本机验收**。
6. **透明桌宠窗口、托盘、开机启动**。

## 数据与版权

源码 ZIP 不应包含：

- 游戏 PNG/JPG
- PSB/PFS
- 解出的角色 JSON / resx
- 游戏 OGG/WAV
- GPT-SoVITS 权重/参考音频
- SQLite 聊天记录
- API Key

`.gitignore` 已覆盖这些高风险目录和文件，但第一次提交 GitHub 前仍需人工查看 `git status`。
