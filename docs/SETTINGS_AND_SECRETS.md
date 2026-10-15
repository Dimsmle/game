# 设置与私有 API 密钥

## 为什么改 DEFAULT_SETTINGS，界面没有变？

正常 Windows 桌面入口 main_desktop.py 将用户数据放在：

`C:\Users\xiao\AppData\Local\CharacterLab\settings.json`

读取顺序：app.py 的 DEFAULT_SETTINGS → settings.json 覆盖同名字段 → 启动后的内存设置。
界面从 `/api/state` 获取这份生效设置，打开设置窗口时填入内存值，不从 Python 源码
实时读描述。DEFAULT_SETTINGS 只给初次启动或没有保存过的字段提供默认值。

推荐在界面修改后保存，立即更新后端内存和该文件；若直接修改 settings.json，先关闭
旧程序，修改并保存后重新启动。不要删除整个设置文件，以免丢失模型、素材路径等。
开发直接运行 studio.app 与桌面主入口的数据目录可能不同；不要混用启动方式。

## 私有密钥位置

源码开发：`G:\开发游戏\CharacterStudio\local_secrets.json`。
未来 frozen EXE：`%LOCALAPPDATA%\CharacterLab\local_secrets.json`，不写在安装目录。

```json
{
  "DEEPSEEK_API_KEY": "在这里填写你自己的新密钥",
  "LLM_API_KEY": "",
  "IMAGE_API_KEY": ""
}
```

示例模板 local_secrets.example.json 可以提交；实际 local_secrets.json 不提交。
不要把真实值填进 example 文件、角色卡、普通 settings.json、人设或聊天里。
本机文件是明文，不是加密保险库；有读取该文件权限的本机程序可以看到它。

优先级：同名进程环境变量 → 本机私有文件。空字符串视为没有配置。
如果设置了系统/IDE 环境变量，修改文件不会覆盖它；要改环境变量或移除该变量。
旧程序若曾执行源码 os.environ 赋值，必须先完全关闭再重启，清掉旧进程中的密钥。
新代码每次请求重新读文件，不把密钥注入 os.environ，也不合并进 STATE/settings。

JSON 不支持注释，字段名要加双引号，不要多逗号；允许 UTF-8 BOM，拒绝重复字段、
超大文件、非字符串和内部控制字符。错误仅返回固定脱敏提示，不输出失败文件正文。
设置页面和 provider_status 只提供是否存在、来源与固定错误摘要，不返回密钥值。

## 已完成的迁移与 Git 风险

原 app.py 中的 DEEPSEEK_API_KEY 字面量已迁入本机私有文件，赋值语句用 apply_patch 删除。
迁移过程只报告成功布尔值，没有打印真实密钥。现已确认新进程读取来源为 local_file。
.gitignore 已忽略实际文件及其备份变体；发行脚本显式排除私有密钥文件。
git check-ignore 确认实际文件被忽略，git ls-files 确认它未被跟踪。

**本机当前 HEAD 中已发现历史硬编码密钥。** 当前源码删除不等于清除历史，.gitignore
也不会删除已提交内容。应在 DeepSeek 后台撤销旧密钥、创建新密钥并更新本机文件；
特别是旧提交曾推送到 GitHub 时必须这样做。旧提交/缓存也可能仍保留副本。
没有擅自重写 Git 历史、强制推送或删除跟踪文件。历史清理需另行确认范围。

## 实际修改与验证

- studio/credentials.py：独立私有读取器、校验、环境变量优先和安全状态摘要。
- studio/app.py：移除硬编码；旧兼容接口和 provider_status 使用统一读取器。
- studio/llm.py：流式 DeepSeek / 自定义接口使用统一读取器。
- studio/web/index.html：明确设置来源与密钥读取方式。
- .gitignore、local_secrets.example.json、release_source.py：忽略与发行排除。
- tests/test_credentials.py、test_ai_providers.py：私有读取、优先级、文件修改生效、
  错误脱敏、Authorization-only、源码无赋值、发行排除及保存值覆盖默认值。

基线 88 项 Python（10.560s）；最终 94 项通过（8.915s）。
命令：`.venv\Scripts\python.exe -m unittest discover -s tests -q`；
`node --check studio/web/app.js`；动作、剧情、流式聊天、逐句、文字口型和状态 HUD
六组 JS 测试通过；`main_desktop.py --doctor` 为 0 errors / 0 warnings。
`git diff --check` 通过。本轮无真实云端调用、没有打包新 EXE/ZIP、没有改写游戏素材。
Windows 实际完成文件迁移和读取来源验证；本轮未重新做浏览器/WebView2 人工验收。

下一步最小任务：轮换曾进入 Git 历史的旧密钥，更新 local_secrets.json，关闭并重启程序。
