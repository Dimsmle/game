"""Small, cancellable OpenAI-compatible transport. No SDK or model installation."""
from __future__ import annotations
import json
import re
import time
import urllib.error
import urllib.request
from typing import Protocol
from .credentials import get_api_key


class Cancelled(RuntimeError):
    pass


class LLMProvider(Protocol):
    def stream(self, messages, cancel): ...


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward Authorization to a redirected host.


def speech_prefix(raw):
    """Extract only the visible string from an incomplete JSON object, not labels."""
    match=re.search(r'"(?:speech|reply)"\s*:\s*"', raw)
    if not match:return ""
    text=raw[match.end():]; out=[]; index=0
    while index<len(text):
        char=text[index]
        if char=='"':break
        if char=='\\':
            length=6 if text[index:index+2]=='\\u' else 2
            if index+length>len(text):break
            try:char=json.loads('"'+text[index:index+length]+'"')
            except ValueError:break
            index+=length
        else:index+=1
        out.append(char)
    # Paired JSON surrogate escapes may arrive separately; don't send invalid UTF-8.
    return ''.join(out).encode('utf-16','surrogatepass').decode('utf-16','replace')[:900]


class OpenAICompatibleProvider:
    def __init__(self, settings):
        self.settings=dict(settings)

    def stream(self, messages, cancel):
        s=self.settings; deepseek=s['llm_mode']=='deepseek'
        base='https://api.deepseek.com' if deepseek else s['llm_url'].rstrip('/')
        url=base if base.endswith('/chat/completions') else base+'/chat/completions'
        env='DEEPSEEK_API_KEY' if deepseek else 'LLM_API_KEY'
        key=get_api_key(env)
        if deepseek and not key:raise RuntimeError('请在本机 local_secrets.json 填写 DEEPSEEK_API_KEY，或设置同名环境变量；不要把密钥发到聊天里。')
        payload={'model':s['llm_model'], 'messages':messages, 'stream':True,
                 'temperature':0.65, 'max_tokens':1600, 'response_format':{'type':'json_object'}}
        if deepseek:payload['thinking']={'type':'disabled'}
        headers={'Content-Type':'application/json','Accept':'text/event-stream'}
        if key:headers['Authorization']='Bearer '+key
        request=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False).encode(),headers=headers)
        opener=urllib.request.build_opener(NoRedirect())
        started=time.monotonic(); emitted=False
        for attempt in range(2):
            if cancel.is_set():raise Cancelled('已停止本轮对话')
            try:
                with opener.open(request,timeout=15) as response:
                    finished=False
                    for _ in range(10000):
                        if cancel.is_set():raise Cancelled('已停止本轮对话')
                        if time.monotonic()-started>90:raise RuntimeError('模型回复超过 90 秒，请重试')
                        line=response.readline(65537)
                        if len(line)>65536:raise RuntimeError('模型流数据行过大')
                        if not line:break
                        if not line.startswith(b'data:'):continue
                        value=line[5:].strip()
                        if value==b'[DONE]':finished=True;break
                        try:item=json.loads(value)
                        except ValueError:raise RuntimeError('模型流不是有效 JSON 数据') from None
                        if not isinstance(item,dict):raise RuntimeError('模型流结构无效')
                        if 'error' in item:raise RuntimeError('模型服务报告错误，请检查模型名称或额度')
                        choices=item.get('choices') or []
                        if not choices:continue
                        if not isinstance(choices,list) or not isinstance(choices[0],dict):raise RuntimeError('模型流 choices 无效')
                        choice=choices[0]
                        delta=choice.get('delta') or {}
                        if not isinstance(delta,dict):raise RuntimeError('模型流 delta 无效')
                        piece=delta.get('content')
                        if isinstance(piece,str) and piece:
                            emitted=True;yield piece
                        reason=choice.get('finish_reason')
                        if reason:
                            if reason!='stop':raise RuntimeError('模型输出被截断或过滤，请重试')
                            finished=True
                            break
                    if cancel.is_set():raise Cancelled('已停止本轮对话')
                    if not finished:raise RuntimeError('模型连接提前结束，未执行本轮行为')
                    return
            except urllib.error.HTTPError as exc:
                exc.close()
                if attempt==0 and not emitted and exc.code in (429,500,502,503,504):
                    if cancel.wait(.5):raise Cancelled('已停止本轮对话')
                    continue
                hint={401:'密钥无效',402:'余额不足',403:'无访问权限',404:'模型或接口不存在',429:'请求过于频繁'}
                raise RuntimeError(f'模型接口 HTTP {exc.code}：{hint.get(exc.code,"服务异常")}') from None
            except (urllib.error.URLError,TimeoutError,OSError) as exc:
                if attempt==0 and not emitted:
                    if cancel.wait(.5):raise Cancelled('已停止本轮对话')
                    continue
                raise RuntimeError('模型连接失败或超时，请检查网络与接口地址') from None
        raise RuntimeError('模型重试失败')
