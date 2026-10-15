"""Explicit local Qwen Base benchmark; never downloads weights or changes UI settings."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',required=True)
    parser.add_argument('--ref-audio',required=True)
    parser.add_argument('--ref-text-file',required=True,help='UTF-8 transcript of authorized reference audio')
    parser.add_argument('--text',default='今天能和你聊一会儿，我很开心。')
    parser.add_argument('--language',choices=('zh','ja','en'),default='zh')
    parser.add_argument('--out',required=True,help='Benchmark output directory (contains generated voice)')
    args=parser.parse_args()
    # Set before importing the optional model stack. No model download during a benchmark.
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    from studio.tts import TTSService
    settings={'tts_enabled':True,'tts_provider':'qwen3_tts','qwen_model_dir':args.model_dir,
        'tts_ref_audio':args.ref_audio,'tts_prompt_text':Path(args.ref_text_file).read_text(encoding='utf-8-sig').strip(),
        'tts_text_lang':args.language}
    folder=Path(args.out);folder.mkdir(parents=True,exist_ok=True)
    service=TTSService(lambda _:None)
    try:
        audio=service.synthesize(args.text,settings,folder)
        (folder/'sample.wav').write_bytes(audio)
        (folder/'metrics.json').write_text(json.dumps(service.last_metrics,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(service.last_metrics,ensure_ascii=False));return 0
    except Exception as exc:
        print(f'本地 TTS 验证未完成：{type(exc).__name__}: {exc}');return 2


if __name__=='__main__':raise SystemExit(main())
