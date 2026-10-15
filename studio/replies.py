"""Validated per-sentence intents and an ephemeral, ordered playback capability."""
from copy import deepcopy
import json
import re
import secrets
import time

from . import behavior


def parse_reply(raw):
    """Accept only a complete JSON document, optionally a whole Markdown fence.

    Never guess missing braces or extract executable intentions from prose.
    """
    text=raw.strip().lstrip('\ufeff')
    fence=re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```',text,re.S|re.I)
    if fence:text=fence.group(1).strip()
    return json.loads(text)


def history_message(row,segmented=True):
    text=row['content']
    if row['role']=='assistant':
        # SQLite keeps read text, not raw provider JSON. Preserve the protocol
        # in model context too, without inventing historical behavior labels.
        value={'segments':[{'speech':text}]} if segmented else {'speech':text}
        text=json.dumps(value,ensure_ascii=False)
    return {'role':row['role'],'content':text}


def normalize_segments(value,scenes):
    if not isinstance(value,dict):raise ValueError('模型回复必须是 JSON 对象')
    multi='segments' in value
    entries=value.get('segments') if multi else [value]
    if not isinstance(entries,list) or not 1<=len(entries)<=6:
        raise ValueError('回复必须有 1–6 段台词')
    clean=[];total=0
    for item in entries:
        if not isinstance(item,dict):raise ValueError('每段台词必须是对象')
        text=item.get('speech',item.get('reply'))
        if not isinstance(text,str) or not text.strip():raise ValueError('每段台词必须包含非空 speech 文本')
        text=text.strip();total+=len(text)
        if len(text)>(400 if multi else 900) or total+len(entries)-1>900:
            raise ValueError('回复过长，请让模型简短回答')
        safe=behavior.normalize_llm_reply({**item,'speech':text},scenes)
        clean.append(safe)
    return clean


class ReplyTurn:
    """Single active reply; callers hold app.CHAT_LOCK for register/activate/cancel."""
    def __init__(self):self.clear()

    def clear(self):self.current=None

    def register(self,segments,settings,source,user_text=''):
        self.current={'id':secrets.token_hex(16),'segments':deepcopy(segments),'settings':dict(settings),
            'source':source,'index':-1,'result':None,'expires':time.monotonic()+1800,
            'user_text':user_text,'history_id':None}
        return self.current['id']

    def cancel(self,token):
        if self.current and self.current['id']==token:self.clear()

    def activate(self,token,index,settings,apply):
        turn=self.current
        if not turn or token!=turn['id']:raise ValueError('这段回复已停止或被新对话替代')
        if settings!=turn['settings'] or time.monotonic()>turn['expires']:
            self.clear();raise ValueError('角色、设置或回复有效期已变化，请重新发送')
        if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(turn['segments']):
            raise ValueError('台词编号无效')
        if index==turn['index']:return deepcopy(turn['result'])
        if index!=turn['index']+1:raise ValueError('请按顺序播放台词，不能跳过或重放旧动作')
        result=apply(turn['segments'][index])
        result.update(source=turn['source'],segment_index=index,segment_count=len(turn['segments']))
        turn['index']=index;turn['result']=deepcopy(result)
        return result


def instructions():
    return ('\n本轮顶层格式以下述逐句协议为准，上述字段规则应用于每个段落：'
        '只输出 {"segments":[...]}，不要顶层 speech。'
        '每段只表达一句话、一个自然的情绪，每段都有 speech/emotion/action_tag/scene/intensity/voice_style。'
        '通常 1–3 段，最多 6 段，总文本不超过 900 字，每段不超过 400 字。'
        '根据每句内容分别决定表情，不要每段机械重复动作；无合适动作就 idle。'
        '流式输出时每段先写 emotion/action_tag 等标签，最后写 speech。')


def demo_reply(text,single):
    if any(word in text for word in ('逐句','表情','演示')):
        return {'segments':[
            {'speech':'诶？你想看看我说不同的话时，会有什么表情吗？','emotion':'surprised','action_tag':'idle'},
            {'speech':'这样一直看着我，我会有点不好意思的……','emotion':'shy','action_tag':'idle'},
            {'speech':'不过，能认真听我说话，我还是很开心。','emotion':'happy','action_tag':'idle'}]}
    return single
