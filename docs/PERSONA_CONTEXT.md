# 人设上下文接入记录

2026-10-15。使用 docx 技能按 ZIP/XML 读取用户指定的 Word，未改写原文件。

## 已实现

- `studio/persona.py`：统一人设上下文，姓名和完整角色资料以角色卡数据加入 system 消息。
- `studio/app.py`：流式聊天及兼容聊天入口共用角色卡。从第一轮起，每轮都会附带，
  不依赖最近聊天历史是否已裁剪。去掉原来的 1000 字截断，上限改为 12000 字并校验。
- `studio/web/index.html`：完整人设输入框扩大并标明上限、发送范围及云端隐私提示。
- `tests/test_ai_providers.py`：验证首轮和后续轮次都含超过 1000 字的人设尾部、姓名和
  JSON 协议；超过 12000 字拒绝保存。测试不调用真实云端服务。

文档中的角色身份、关系、日常性格和说话风格整理为“雪野”日常版，已保存到本机
`%LOCALAPPDATA%\CharacterLab\settings.json` 的 role_name/persona。未导入露骨性描写要求。
原文末尾的场景 UI 格式不采用，继续使用程序统一的 JSON segments 协议。
这不是原文全文导入，也不会自动同步之后修改的 Word。

保存前在同一数据目录的 backups 中备份了原 settings，文件名以
`settings_before_daily_persona_` 开头。仅改变姓名和人设，保留当前 shi_15、AI、语音及其余设置。
本机临时应用脚本 `.tmp/apply_daily_persona.py` 不属于发行内容。

## 使用

关闭并重新启动程序。在“设置 → 连接与角色设置 → 完整人设”可查看、修改并保存。
无需把人设手动粘贴到第一条聊天里；每次实际 AI 请求都会携带它。启动本身不单独请求
AI、不产生额外的“初始化聊天”。离线 demo 仍是固定示例，不会推理人设。
下一次使用 DeepSeek 等云端服务聊天时，该日常角色资料会随请求发送给所选服务。

## 验证与边界

基线 71 项 Python 通过；最终 `.venv\Scripts\python.exe -m unittest discover -s tests -q`
为 72 项通过（6.127 秒）。`node --check studio/web/app.js` 及动作、剧情、流式聊天、
逐句播放器、文字口型共五组 JS 测试通过。Doctor：0 errors / 0 warnings；git diff --check 通过。

Windows 已实际读取 Word、备份并保存正式设置；本轮未再次进行浏览器或 EXE 人工验收，
未将人设发送到真实云端做质量测试。协议优先级提示并非对模型遵从性的绝对保证。
游戏原始素材、Word、聊天数据库未改写，未改 API 密钥或安装模型。

下一步最小任务：重启后聊一两轮日常话题，观察人物语气是否符合预期，再调整人设。
