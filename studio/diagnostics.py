# -*- coding: utf-8 -*-
"""Offline diagnostics. No external service is contacted unless a future caller asks."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile

def _item(key,label,status,detail="",severity=None):
    severity=severity or ("ok" if status else "error")
    return {"key":key,"label":label,"ok":bool(status),"severity":severity,"detail":str(detail)}

def run(data_dir,asset_root=None,settings=None,model_name=""):
    data_dir=Path(data_dir)
    settings=settings or {}
    items=[]
    items.append(_item("python","Python 3.9+",sys.version_info>=(3,9),
                       sys.version.split()[0]))
    items.append(_item("platform","Windows 目标平台",sys.platform=="win32",
                       platform.platform(),
                       "ok" if sys.platform=="win32" else "warning"))
    try:
        data_dir.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="doctor_",dir=data_dir,delete=True) as f:
            f.write(b"ok");f.flush()
        writable=True
    except OSError as exc:
        writable=False;write_detail=exc
    items.append(_item("data_writable","用户数据目录可写",writable,
                       data_dir if writable else write_detail))
    root=Path(asset_root).resolve() if asset_root and Path(asset_root).is_dir() else None
    items.append(_item("asset_root","素材根目录",root is not None,root or "未选择"))
    model_json=None
    if root is not None and model_name:
        hits=list(root.glob("**/"+model_name+".json"))
        model_json=next((x for x in hits if x.is_file() and not x.is_symlink()),None)
    items.append(_item("model","当前角色模型",bool(model_json),
                       model_json or (model_name or "未选择"),
                       "ok" if model_json else "warning"))
    items.append(_item("pillow","Pillow",importlib.util.find_spec("PIL") is not None,
                       "installed" if importlib.util.find_spec("PIL") else "missing"))
    webview=importlib.util.find_spec("webview") is not None
    items.append(_item("pywebview","pywebview Python 包",webview,
                       ("installed；Windows WebView2 Runtime 仍需本机启动验收" if webview else "missing"),
                       "ok" if webview else "warning"))
    ffmpeg=shutil.which("ffmpeg")
    stt=bool(settings.get('stt_enabled',False))
    items.append(_item("ffmpeg","FFmpeg / 可选 ASR",bool(ffmpeg) or not stt,ffmpeg or "语音识别关闭，无需安装",
                       "ok" if ffmpeg or not stt else "warning"))
    asr_path=str(settings.get("asr_model_path","")).strip()
    asr_ok=bool(asr_path and Path(asr_path).is_dir())
    items.append(_item("asr","faster-whisper 模型",asr_ok or not stt,
                       asr_path or "语音识别关闭，无需安装","ok" if asr_ok or not stt else "warning"))
    llm_mode=settings.get("llm_mode","demo")
    llm_ready=(llm_mode=="demo" or bool(str(settings.get("llm_model","")).strip()))
    items.append(_item("llm","LLM 配置",llm_ready,
                       "demo" if llm_mode=="demo" else f"{settings.get('llm_url','')} / {settings.get('llm_model','')}",
                       "ok" if llm_ready else "warning"))
    tts_enabled=bool(settings.get("tts_enabled"))
    tts_ready=(not tts_enabled) or bool(str(settings.get("tts_ref_audio","")).strip())
    if tts_enabled and settings.get('tts_provider')=='system':tts_ready=True
    if tts_enabled and settings.get('tts_provider')=='qwen3_tts':
        tts_ready=tts_ready and bool(settings.get('qwen_model_dir')) and (Path(settings['qwen_model_dir'])/'config.json').is_file()
    items.append(_item("tts","TTS 可选配置",tts_ready,
                       "未启用" if not tts_enabled else settings.get("tts_url",""),
                       "ok" if tts_ready else "warning"))
    errors=sum(x["severity"]=="error" for x in items)
    warnings=sum(x["severity"]=="warning" for x in items)
    return {"ok":errors==0,"errors":errors,"warnings":warnings,
            "items":items,"note":"诊断只检查本机配置/文件，不主动连接 DeepSeek、TTS 或互联网。"}

def format_text(report):
    marks={"ok":"OK","warning":"WARN","error":"ERROR"}
    lines=["Character Studio Doctor", "="*58]
    for item in report["items"]:
        lines.append(f"[{marks[item['severity']]}] {item['label']}: {item['detail']}")
    lines.append("-"*58)
    lines.append(f"errors={report['errors']} warnings={report['warnings']}")
    lines.append(report["note"])
    return "\n".join(lines)
