"""Optional TTS providers. Imports of GPU dependencies happen only on explicit use."""
from __future__ import annotations
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import subprocess
import time
from typing import Protocol
import wave


class TTSProvider(Protocol):
    def synthesize(self, text, settings): ...
    def release(self): ...


def gpu_memory():
    """Whole-device snapshot, not a claim that the TTS process uses all of it."""
    try:
        result=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,memory.used,memory.free',
            '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        rows=[]
        if result.returncode==0:
            for line in result.stdout.splitlines():
                name,total,used,free=[x.strip() for x in line.split(',')]
                rows.append({'name':name,'total_mb':int(total),'used_mb':int(used),'free_mb':int(free)})
        return rows
    except (OSError,ValueError,subprocess.TimeoutExpired):return []


def validate_wav(audio):
    if len(audio)>16*1024*1024:raise RuntimeError('语音文件过大')
    try:
        with wave.open(io.BytesIO(audio),'rb') as stream:
            if not stream.getnframes() or stream.getframerate()<8000:raise ValueError()
    except (wave.Error,EOFError,ValueError):raise RuntimeError('语音接口未返回有效 PCM WAV 音频') from None
    return audio


class GPTSoVITSProvider:
    def __init__(self, synthesize):self.call=synthesize
    def synthesize(self,text,settings):return self.call(text)
    def release(self):pass  # External service owns its model lifecycle.


class Qwen3Provider:
    def __init__(self):self.model=None;self.last_metrics={}

    def synthesize(self,text,settings):
        directory=Path(settings.get('qwen_model_dir',''))
        reference=Path(settings.get('tts_ref_audio',''))
        if not settings.get('qwen_model_dir') or not (directory/'config.json').is_file():
            raise RuntimeError('Qwen3-TTS 尚未配置本地 Base 模型目录；程序不会自动下载权重')
        if not reference.is_file() or not settings.get('tts_prompt_text','').strip():
            raise RuntimeError('Qwen3-TTS 克隆需要本机参考音频及与之对应的文本')
        config=json.loads((directory/'config.json').read_text(encoding='utf-8'))
        if config.get('tts_model_type')!='base':raise RuntimeError('语音克隆必须选择 Qwen3-TTS Base 模型')
        try:
            import torch
            import soundfile as sf
            from qwen_tts import Qwen3TTSModel
        except ImportError:raise RuntimeError('未安装 Qwen3-TTS 可选依赖；文字聊天不受影响，请参阅 AI 接入说明') from None
        if not torch.cuda.is_available():raise RuntimeError('Qwen3-TTS 未检测到可用 CUDA；没有自动切换到慢速 CPU')
        began=time.monotonic();torch.cuda.reset_peak_memory_stats()
        try:
            # Use an explicitly downloaded local folder, never a Hub repository ID.
            self.model=Qwen3TTSModel.from_pretrained(str(directory.resolve()),device_map='cuda:0',
                dtype=torch.bfloat16,attn_implementation='sdpa',local_files_only=True)
            loaded=time.monotonic()
            language={'zh':'Chinese','ja':'Japanese','en':'English'}.get(settings['tts_text_lang'],'Auto')
            wavs,sr=self.model.generate_voice_clone(text=text,language=language,
                ref_audio=str(reference.resolve()),ref_text=settings['tts_prompt_text'],max_new_tokens=2048)
            out=io.BytesIO();sf.write(out,wavs[0],sr,format='WAV',subtype='PCM_16')
            self.last_metrics={'load_ms':round((loaded-began)*1000),
                'synthesis_ms':round((time.monotonic()-loaded)*1000),
                'peak_allocated_mb':round(torch.cuda.max_memory_allocated()/1024**2),
                'first_audio_ms':round((time.monotonic()-began)*1000),
                'streaming':False}
            return out.getvalue()
        finally:self.release()

    def release(self):
        self.model=None;gc.collect()
        import sys
        torch=sys.modules.get('torch')
        if torch is not None and torch.cuda.is_available():torch.cuda.empty_cache()


class TTSService:
    """One synthesis at a time; bounded local cache; no heavyweight idle residency."""
    def __init__(self,gpt_call):
        self.providers={'gpt_sovits':GPTSoVITSProvider(gpt_call),'qwen3_tts':Qwen3Provider()}
        self.lock=threading.Lock();self.last_metrics={}

    def synthesize(self,text,settings,data_dir):
        if not settings.get('tts_enabled'):raise ValueError('语音未启用')
        provider=settings.get('tts_provider','gpt_sovits')
        if provider not in self.providers:raise ValueError('系统语音由桌面 WebView 播放，不通过音频接口合成')
        if not self.lock.acquire(blocking=False):raise RuntimeError('上一段语音仍在合成，请稍后重试')
        began=time.monotonic()
        try:
            options={k:v for k,v in settings.items() if k.startswith(('tts_','qwen_'))}
            for key in ('tts_ref_audio','qwen_model_dir'):
                p=Path(str(options.get(key,'')))
                if p.exists():options[key+'_stamp']=p.stat().st_mtime_ns
            digest=hashlib.sha256(json.dumps([text,options],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            folder=Path(data_dir)/'tts_cache';folder.mkdir(exist_ok=True,parents=True)
            path=folder/(digest+'.wav');cached=path.is_file()
            if cached:audio=path.read_bytes()
            else:
                audio=validate_wav(self.providers[provider].synthesize(text,settings))
                path.write_bytes(audio)
            self.last_metrics={'provider':provider,'cached':cached,'total_ms':round((time.monotonic()-began)*1000)}
            if provider=='qwen3_tts' and not cached:self.last_metrics.update(self.providers[provider].last_metrics)
            if not cached:self.last_metrics['gpu_after_release']=gpu_memory()
            files=sorted(folder.glob('*.wav'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in files[32:]:old.unlink(missing_ok=True)
            return validate_wav(audio)
        finally:self.lock.release()
