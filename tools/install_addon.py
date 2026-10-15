#!/usr/bin/env python3
"""Guarded Character Studio v0.11 roleplay extension installer.

Dry-run by default. Never overwrites an existing add-on directory containing
different bytes, never force-patches an unfamiliar app.py, always backs up.
Target: user's LOCAL CODEX working tree (not the public GitHub repository).
"""
from __future__ import annotations
import argparse
import ast
import difflib
from datetime import datetime
from pathlib import Path
import shutil
import re
import sys
import tempfile

PACKAGE = Path(__file__).resolve().parents[1]
ADDON_REL = Path("studio/roleplay_plus")
MARKER = "from studio.roleplay_plus import bridge as roleplay_bridge"
# Only clean the narrowly recognized insecure literal assignment found in
# legacy app.py. Never echo the credential in a diff, warning or release.
EMBEDDED_KEY = re.compile(r"(?m)^os\.environ\[\s*(['\"])DEEPSEEK_API_KEY\1\s*\]\s*=\s*(['\"])[^\r\n'\"]+\2[ \t]*(?:\#[^\r\n]*)?$", re.ASCII)
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")
GITIGNORE_LINES = (".env", ".env.*", "!.env.example", "local_secrets.json", "**/local_secrets.json", ".roleplay_install_backups/", "**/__pycache__/", "*.pyc")

def scrub_embedded_key(source):
    """Remove a *literal* committed DeepSeek key before importing app.py.

    Unknown secret-bearing forms require manual review; never print the value.
    """
    count=len(EMBEDDED_KEY.findall(source))
    if count>1:raise ValueError("检测到多个硬编码 DeepSeek Key，请手动清理")
    if count==1:
        source=EMBEDDED_KEY.sub('# DeepSeek key removed: configure DEEPSEEK_API_KEY via environment or local .env',source)
    if SECRET_PATTERN.search(source):
        raise ValueError("app.py 仍存在疑似硬编码密钥，请人工移除后重试（不显示密钥）")
    return source,count

def redact_diff(diff):
    """An audit diff must never leak already published credentials."""
    return SECRET_PATTERN.sub('sk-REDACTED',diff)

def once(source,needle,replacement,label):
    count=source.count(needle)
    if count!=1:raise ValueError(
        f"{label} 无法安全合并：预期唯一定位点，实际找到 {count} 处。"
        "Codex 可能已修改该代码，请人工检查文档中的接入点，禁止强制覆盖。"
    )
    return source.replace(needle,replacement,1)

def patch_app_legacy(src,native_credentials=False):
    if MARKER in src:raise ValueError("这个 app.py 已经接入 Roleplay Plus；请勿重复安装")
    ast.parse(src)
    text,_=scrub_embedded_key(src)
    text=once(text,
      "from studio import replies\n",
      "from studio import replies\n"+MARKER+"\n"+
      ("" if native_credentials else "roleplay_bridge.load_project_env(Path(__file__).resolve().parents[1])\n"),
      "添加桥接 import")
    text=once(text,
      "    return STATE\n\n@contextmanager\ndef connect_db():",
      "    roleplay_bridge.initialize(DB_FILE, settings)\n    return STATE\n\n@contextmanager\ndef connect_db():",
      "初始化扩展 SQLite")
    text=once(text,
      '        query=urllib.parse.parse_qs(route.query)\n        try:\n            if path=="/":',
      '        query=urllib.parse.parse_qs(route.query)\n        try:\n'
      '            if roleplay_bridge.try_get(self,path,query):return\n'
      '            if path=="/":',
      "增加 Roleplay GET 页面和 API")
    text=once(text,
      '            if not isinstance(obj,dict):\n                raise ValueError("请求体必须是对象")\n            if path=="/api/settings":',
      '            if not isinstance(obj,dict):\n                raise ValueError("请求体必须是对象")\n'
      '            if roleplay_bridge.try_post(self,path,obj):return\n'
      '            if path=="/api/settings":',
      "增加 Roleplay POST API")
    text=once(text,
      '    else:\n        if not settings["llm_model"].strip():',
      '    else:\n        rp_legacy_epoch=roleplay_bridge.epoch()\n'
      '        if not settings["llm_model"].strip():',
      "同步兼容模式的配置版本保护")
    text=once(text,
      '        output=planned_reply(message)\n        origin="openai-compatible"',
      '        if roleplay_bridge.epoch()!=rp_legacy_epoch:\n'
      '            raise RuntimeError("角色卡、世界书或属性已变更，请重新发送")\n'
      '        output=planned_reply(message)\n        origin="openai-compatible"',
      "同步兼容模式防止旧响应落地")
    text=once(text,
      '        conversation=[{"role":"system","content":prompt}]',
      '        prompt=roleplay_bridge.extend_prompt(prompt,settings,user_text,history(6))\n'
      '        conversation=[{"role":"system","content":prompt}]',
      "使旧 OpenAI-compatible 路径使用角色卡")
    text=once(text,
      '    settings=dict(STATE["settings"]); began=time.monotonic(); first=None',
      '    settings=dict(STATE["settings"]); began=time.monotonic(); first=None\n'
      '    rp_epoch=roleplay_bridge.epoch()',
      "流式回复快照保护")
    text=once(text,
      '            messages=[{"role":"system","content":prompt}]',
      '            prompt=roleplay_bridge.extend_prompt(prompt,settings,user_text,history(6))\n'
      '            messages=[{"role":"system","content":prompt}]',
      "DeepSeek 流式路径实际注入 Prompt")
    text=once(text,
      '            if settings!=STATE["settings"]:raise Cancelled("配置或角色已变化，请重新发送")',
      '            if settings!=STATE["settings"]:raise Cancelled("配置或角色已变化，请重新发送")\n'
      '            if roleplay_bridge.epoch()!=rp_epoch:raise Cancelled("角色卡、世界书或游戏属性已变化，请重新发送")',
      "配置/属性变化后取消旧 LLM 结果")
    ast.parse(text)
    return text

def patch_app_p1(src,native_credentials=False):
    """Integrate with the *current* P1 GameStore/profile-aware v0.11 layout.

    Keep game_db as the only writable gameplay authority. The rp_* demo state
    is not allowed to modify or compete with the main game's relationship data.
    """
    if MARKER in src:raise ValueError("这个 app.py 已经接入 Roleplay Plus；请勿重复安装")
    ast.parse(src)
    text,_=scrub_embedded_key(src)
    text=once(text, "from studio import replies\n",
        "from studio import replies\n"+MARKER+"\n"+
        ("" if native_credentials else "roleplay_bridge.load_project_env(Path(__file__).resolve().parents[1])\n"),
        "P1: 导入新桥接模块与私有 .env")
    text=once(text,
        "    from .game_db import migrate\n    migrate(DB_FILE)\n    return STATE",
        "    from .game_db import migrate\n    migrate(DB_FILE)\n"+
        "    roleplay_bridge.initialize(DB_FILE, settings, use_existing_game_state=True)\n    return STATE",
        "P1: 在现有 GameStore 迁移后初始化角色卡")
    text=once(text,
        "    return dict(STATE['settings'],_game_session=session,_game_state=state)",
        "    return dict(STATE['settings'],_game_session=session,_game_state=state,\n"+
        "                _roleplay_epoch=roleplay_bridge.epoch())",
        "P1: 将角色卡版本绑定现有 ReplyTurn 快照保护")
    # The existing character description must no longer compete with the
    # newly selected roleplay card. This does not change the underlying user
    # settings and deliberately preserves the authoritative state prompt.
    old="+persona_context(settings)"
    if text.count(old)!=2:
        raise ValueError("P1 人物描述构造点不是预期的两处，拒绝冒险覆盖")
    text=text.replace(old,'+"\\n【人物核心以当前 Roleplay 角色卡为准；遵守原有输出协议。】"')
    text=once(text,
        '        conversation=[{"role":"system","content":prompt}]',
        '        prompt=roleplay_bridge.extend_prompt(prompt,settings,user_text,history(6,profile_id))\n'+
        '        conversation=[{"role":"system","content":prompt}]',
        "P1: 同步模型请求使用角色卡与世界书")
    text=once(text,
        '            messages=[{"role":"system","content":prompt}]',
        '            prompt=roleplay_bridge.extend_prompt(prompt,settings,user_text,history(6,settings["_game_session"]["profile_id"]))\n'+
        '            messages=[{"role":"system","content":prompt}]',
        "P1: 流式 DeepSeek 使用角色卡与世界书")
    text=once(text,
        '        query=urllib.parse.parse_qs(route.query)\n        try:\n            if path=="/":',
        '        query=urllib.parse.parse_qs(route.query)\n        try:\n'+
        '            if roleplay_bridge.try_get(self,path,query):return\n'+
        '            if path=="/":',
        "P1: 安装角色工作台页面/API")
    text=once(text,
        '            if not isinstance(obj,dict):\n                raise ValueError("请求体必须是对象")\n',
        '            if not isinstance(obj,dict):\n                raise ValueError("请求体必须是对象")\n'+
        '            if roleplay_bridge.try_post(self,path,obj):return\n',
        "P1: 将角色 CRUD 路由接入现有安全 POST Handler")
    ast.parse(text)
    return text

def patch_app(src,native_credentials=False):
    """Native credentials.py wins; never replace Codex's private-key loader."""
    if MARKER in src:raise ValueError("这个 app.py 已经接入 Roleplay Plus；请勿重复安装")
    ast.parse(src)
    clean,_=scrub_embedded_key(src)
    if "def chat_settings():" in clean and "from .game_db import migrate" in clean:
        return patch_app_p1(clean,native_credentials=native_credentials)
    return patch_app_legacy(clean,native_credentials=native_credentials)

def target_ready(root):
    return (root/"studio"/"app.py").is_file() and (root/"studio"/"__init__.py").is_file()

def plans(root):
    if not target_ready(root):raise ValueError("目标不是包含 studio/app.py 的 Character Studio 根目录")
    app=root/"studio"/"app.py"
    raw=app.read_text(encoding="utf-8")
    # Current Codex P1 already uses studio.credentials and local_secrets.json.
    # Preserve that backend; do not add a competing .env loader.
    native_credentials=(root/"studio"/"credentials.py").is_file()
    changed=patch_app(raw,native_credentials=native_credentials)
    addon=PACKAGE/ADDON_REL
    to_copy=[]
    for source in sorted(addon.rglob("*")):
        if not source.is_file() or "__pycache__" in source.parts or source.suffix in (".pyc",".pyo"):
            continue
        dest=root/ADDON_REL/source.relative_to(addon)
        if dest.exists():
            if dest.read_bytes()!=source.read_bytes():
                raise ValueError(f"已有不同版本的扩展文件：{dest}，请先人工合并")
            continue
        to_copy.append((source,dest))
    # Include tests and local preview so the add-on can be verified inside the
    # user's actual git checkout (not only in the delivered archive).
    for rel in ("tests", "tools"):
        folder=PACKAGE/rel
        for source in sorted(folder.glob("*.py")):
            dest=root/rel/source.name
            if dest.exists():
                if dest.read_bytes()!=source.read_bytes():
                    raise ValueError(f"已有不同的测试或工具文件：{dest}，需要人工合并")
                continue
            to_copy.append((source,dest))
    html=[]
    web=root/"studio"/"web"
    if web.is_dir():
        for name in ("index.html","game.html"):
            path=web/name
            if not path.is_file():continue
            raw_html=path.read_text(encoding="utf-8")
            if '/roleplay/launcher.js' in raw_html:continue
            if raw_html.lower().count("</body>")!=1:
                raise ValueError(f"{name} 没有唯一的 </body>，不能安全插入工作台入口")
            new=raw_html.replace("</body>",'<script defer src="/roleplay/launcher.js"></script>\n</body>',1)
            html.append((path,raw_html,new))
    return raw,changed,to_copy,html

def execute(root,apply=False):
    root=Path(root).expanduser().resolve()
    raw,changed,to_copy,html=plans(root)
    patch=redact_diff(''.join(difflib.unified_diff(raw.splitlines(True),changed.splitlines(True),
                      fromfile="a/studio/app.py",tofile="b/studio/app.py")))
    print("目标：",root)
    _,embedded=scrub_embedded_key(raw)
    print("修改 app.py：结构识别后受保护接入；",len(patch.splitlines()),"行脱敏 diff")
    if embedded:print("安全修复：移除 1 处硬编码 DeepSeek Key。请立即撤销该旧 Key 并重建！")
    print("准备新增扩展文件：",len(to_copy))
    print("准备增添角色工作台入口：",", ".join(x[0].name for x in html) or "无（可直接访问 /roleplay/）")
    if not apply:
        print("【干运行】未修改任何文件；添加 --apply 才执行安装。")
        return patch
    backup_dir=root/".roleplay_install_backups"
    backup_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    backup=backup_dir/f"app_before_v014_{stamp}.py"
    i=1
    while backup.exists():
        backup=backup_dir/f"app_before_v014_{stamp}_{i}.py";i+=1
    shutil.copy2(root/"studio"/"app.py",backup)
    gitignore=root/".gitignore"
    existing_ignore=gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    new_ignore=existing_ignore.rstrip("\n")+"\n"
    for line in GITIGNORE_LINES:
        if line not in existing_ignore.splitlines():new_ignore+=line+"\n"
    written=[]
    try:
        for source,dest in to_copy:
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,dest)
            written.append(dest)
        for html_path,orig,new in html:
            shutil.copy2(html_path,backup_dir/(html_path.name+".before_v014"))
            html_path.write_text(new,encoding="utf-8")
        gitignore.write_text(new_ignore,encoding="utf-8")
        dest=root/"studio"/"app.py"
        temp=dest.with_name("app.py.roleplay_tmp")
        temp.write_text(changed,encoding="utf-8")
        temp.replace(dest)
    except Exception:
        # Restore overwritten project files and discard this installation's
        # newly copied files. Backups remain available for manual recovery.
        (root/"studio"/"app.py").write_text(raw,encoding="utf-8")
        for html_path,orig,_ in html:html_path.write_text(orig,encoding="utf-8")
        if existing_ignore:gitignore.write_text(existing_ignore,encoding="utf-8")
        elif gitignore.exists():gitignore.unlink()
        for dest in reversed(written):dest.unlink(missing_ok=True)
        raise
    print("已安装，原 app.py 备份：",backup)
    print("下一步请运行 python -m unittest discover -s tests -v，再启动程序打开 /roleplay/。")
    print("若 Codex 正在改 app.py，应先用 git diff 审查这些更改再合并。")
    return patch

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--target",required=True,help="本地 Character Studio 工程根目录")
    p.add_argument("--apply",action="store_true",help="实际修改；默认仅检查")
    p.add_argument("--write-diff",help="仅导出 app.py unified diff，仍不写入目标")
    args=p.parse_args()
    try:
        patch=execute(args.target,args.apply)
        if args.write_diff:
            Path(args.write_diff).write_text(patch,encoding="utf-8")
    except (ValueError,OSError,SyntaxError) as e:
        print("安全合并中止：",e,file=sys.stderr)
        sys.exit(2)

if __name__=="__main__":main()
