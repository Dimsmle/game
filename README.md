# Character Studio v0.11

自由聊天已支持逐句表情：离线模式输入“演示逐句表情”，点击“下一句”体验惊讶 → 害羞 → 开心。
LLM 也可返回逐句语义标签，播放时逐句校验和执行；停止后不把未读尾句加入历史。
详见 [v0.11 逐句回复说明](docs/V0.11_SENTENCE_REPLIES.md)。

新增舞台自由聊天、DeepSeek 官方流式适配、本地语义校验，以及可选 Qwen Base / GPT-SoVITS /
系统语音。未安装语音模型也可文字聊天；STT 默认关闭。真实云端与克隆声音尚待配置验收。
请先看 [AI 接入与验证边界](docs/V0.10_AI_FOUNDATION.md)。

Windows 本地角色游戏舞台。三段无声分支对话逐句切换真实表情，对话 AI/语音可选。

请先阅读 [v0.9 使用说明](docs/V0.9_GAME_SCENES.md)。开发工作台使用 `--studio`。

```powershell
python main_desktop.py --root "G:\开发游戏\Amakano3_AI" --model kan_10 --browser
```

无需部署 AI 即可预览角色和动作。源码发布包不含游戏素材、模型权重或用户数据。
