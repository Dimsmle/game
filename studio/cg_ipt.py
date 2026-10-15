"""Data-only Artemis diff reconstruction. Never evaluates Lua or AST code."""
from io import BytesIO
from pathlib import Path
import json
import re
from PIL import Image
from .gameplay_core.common import checked_file, identifier

_TOKEN=re.compile(r'\s+|--[^\r\n]*|"(?:[^"\\]|\\["\\nrt])*"|-?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z_0-9]*|[{},=]')


def literal_table(text, assignment=False):
    """Small literal grammar, not a Lua interpreter; reject executable syntax."""
    if not isinstance(text,str) or len(text)>65536:raise ValueError('描述文件过大')
    tokens=[];at=0
    while at<len(text):
        m=_TOKEN.match(text,at)
        if not m:raise ValueError('不支持的描述语法')
        token=m.group();at=m.end()
        if not token.isspace() and not token.startswith('--'):tokens.append(token)
    i=0;nodes=0
    def value(depth=0):
        nonlocal i,nodes
        nodes+=1
        if depth>16 or nodes>4096 or i>=len(tokens):raise ValueError('描述结构无效')
        t=tokens[i];i+=1
        if t=='{':
            result={};index=1
            while i<len(tokens) and tokens[i]!='}':
                if i+1<len(tokens) and tokens[i+1]=='=':
                    key=tokens[i]
                    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',key):raise ValueError('字段名无效')
                    i+=2
                else:key=index;index+=1
                if key in result:raise ValueError('描述字段重复')
                result[key]=value(depth+1)
                if i<len(tokens) and tokens[i]==',':i+=1
                elif i>=len(tokens) or tokens[i]!='}':raise ValueError('缺少字段分隔符')
            if i>=len(tokens):raise ValueError('描述括号不完整')
            i+=1;return result
        if t.startswith('"'):return json.loads(t)
        if re.fullmatch(r'-?\d+(?:\.\d+)?',t):return float(t) if '.' in t else int(t)
        raise ValueError('描述只允许字面量，不执行函数或变量')
    if assignment:
        if tokens[:2]!=['ipt','=']:raise ValueError('不是受支持的IPT描述')
        i=2
    result=value()
    if i!=len(tokens) or not isinstance(result,dict):raise ValueError('描述包含额外代码')
    return result


def _int(v,low=-8192,high=8192):
    if type(v) is not int or not low<=v<=high:raise ValueError('图片尺寸或坐标超限')
    return v


def read_png(root,relative):
    path=checked_file(root,relative,allowed_extensions={'.png'},max_bytes=32*1024*1024)
    data=path.read_bytes()
    with Image.open(BytesIO(data)) as image:
        if image.format!='PNG' or image.width*image.height>16_000_000:raise ValueError('CG图片格式或尺寸不支持')
        image.load();return image.convert('RGBA')


def reconstruct(root,folder,stem,dependencies=None,stack=()):
    """Composite native pixels. base.x/y are parent placement, NOT patch offsets."""
    identifier(stem,'CG文件名')
    if stem in stack or len(stack)>=8:raise ValueError('CG差分依赖循环或过深')
    deps=dependencies if dependencies is not None else set()
    png=Path(folder)/(stem+'.png');ipt=Path(folder)/(stem+'.ipt')
    if not (Path(root)/ipt).exists():
        deps.add(png.as_posix());return read_png(root,png),{'x':0,'y':0}
    path=checked_file(root,ipt,allowed_extensions={'.ipt'},max_bytes=65536)
    raw=literal_table(path.read_text(encoding='utf-8-sig'),assignment=True);deps.add(ipt.as_posix())
    if set(k for k in raw if isinstance(k,str))!={'mode','base'} or raw['mode']!='diff':raise ValueError('本轮仅支持IPT diff模式')
    base=raw['base']
    if not isinstance(base,dict) or set(base)-{1,'x','y','w','h','ax','ay'} or 1 not in base:raise ValueError('IPT底图字段无效')
    image,_=reconstruct(root,folder,base[1],deps,(*stack,stem))
    w=_int(base.get('w',image.width),1);h=_int(base.get('h',image.height),1)
    if image.size!=(w,h):raise ValueError('IPT底图尺寸与文件不符')
    layers=[raw[k] for k in sorted(k for k in raw if type(k) is int)]
    if not 1<=len(layers)<=32:raise ValueError('IPT图层数量不支持')
    used=set()
    for layer in layers:
        if not isinstance(layer,dict) or set(layer)!={'id','file','x','y'}:raise ValueError('IPT差分图层字段不支持')
        layer_id=_int(layer['id'],1,1000)
        if layer_id in used:raise ValueError('IPT图层ID重复')
        used.add(layer_id);identifier(layer['file'],'差分文件名')
        relative=Path(folder)/(layer['file']+'.png');deps.add(relative.as_posix());patch=read_png(root,relative)
        x=_int(layer['x']);y=_int(layer['y'])
        if x<0 or y<0 or x+patch.width>w or y+patch.height>h:raise ValueError('差分图片越过底图边界')
        image.alpha_composite(patch,(x,y))
    return image,{'x':_int(base.get('x',0)),'y':_int(base.get('y',0))}
