"""Pinned CG bundles: derived frames + data-only AST references, no game code."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from .cg_ipt import literal_table,reconstruct
from .gameplay_core.common import checked_file,fingerprint_file,identifier,stable_asset_id

VERSION=1
_CAMERA={'zoom','rotate','x','y','x2','y2','z2','style','alpha','ease'}


def _read(root,relative,extensions):
    data=checked_file(root,relative,allowed_extensions=extensions,max_bytes=4*1024*1024).read_bytes()
    return data.decode('utf-8-sig'),hashlib.sha256(data).hexdigest()


def _write(target,data):
    # Atomic replace avoids partial previews and never writes through a hardlink.
    with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.cg_',delete=False) as handle:
        temporary=Path(handle.name);handle.write(data)
    try:os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()


def locate(root,group):
    identifier(group,'CG组名')
    if not re.fullmatch(r'ev_[a-z]{3}_[a-z][0-9]{2}',group):raise ValueError('CG组名不在受支持的命名范围')
    root=Path(root).resolve()
    # Exact relative roots only. Do not recursively follow user-created links.
    choices=[root/'assets_pfs_004/image/ev'/group,root/'assets_pfs_003/image/ev'/group,
             root/'assets_pfs_002/image/ev'/group,root/'assets/image/ev'/group]
    folders=[p for p in choices if p.is_dir()]
    if not folders:raise ValueError('未找到此CG组')
    # POC refuses split/overlaid groups rather than guess archive precedence.
    if len(folders)>1:raise ValueError('CG组存在跨包覆盖，请先明确资源优先级')
    relative=folders[0].relative_to(root)
    names=sorted(p.stem for p in folders[0].glob('*.png'))
    if not 1<=len(names)<=32:raise ValueError('CG组图片数量不支持')
    for name in names:checked_file(root,relative/(name+'.png'),allowed_extensions={'.png'})
    return relative,names


def extract_steps(text,group,names):
    """Keep source order and transition times, NOT invented dialogue durations."""
    steps=[];unsupported=set()
    for line_no,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line.startswith('{"bg",') or 'set="'+group+'"' not in line:continue
        raw=literal_table(line[:-1] if line.endswith(',') else line)
        if raw.get(1)!='bg' or raw.get('file') not in names or raw.get('path')!=':ev/'+group+'/':raise ValueError('脚本CG引用与当前组不一致')
        time_ms=raw.get('time',0)
        if type(time_ms) is not int or not 0<=time_ms<=15000:raise ValueError('转场时间超限')
        camera=sorted(set(raw)&_CAMERA);unsupported.update(camera)
        steps.append({'frame':raw['file'],'transition_ms':time_ms,'line':line_no,'unsupported':camera})
        if len(steps)>100:raise ValueError('脚本演出步骤过多')
    return steps,sorted(unsupported)


def build(root,group):
    """Generate only disposable derived data under character_exports; no approvals."""
    root=Path(root).resolve();folder,names=locate(root,group)
    scripts=[]
    # Prefer a whole matching patch script over its base version. No execution.
    roots=[root/'assets_pfs_004/script',root/'assets_pfs_main/script']
    seen=set()
    for source in roots:
        if not source.is_dir():continue
        for p in sorted(source.glob('*.ast')):
            if p.name in seen:continue
            seen.add(p.name)
            if p.name=='pack.ast':continue
            rel=p.relative_to(root).as_posix();text,sha=_read(root,rel,{'.ast'})
            steps,unsupported=extract_steps(text,group,names)
            if steps:scripts.append((rel,steps,unsupported,sha))
    if not scripts:raise ValueError('找不到CG调用脚本；不猜测编号播放顺序')
    # Multiple contexts stay explicit. Use most complete occurrence set for POC.
    scripts.sort(key=lambda row:(-len(row[1]),row[0]))
    script,steps,unsupported,script_hash=scripts[0]
    initial={script:script_hash}
    for name in names:
        for ext in ('.png','.ipt'):
            rel=(folder/(name+ext)).as_posix()
            if (root/rel).exists():initial[rel]=fingerprint_file(checked_file(root,rel))
    dependencies={script};images={};origins={}
    for name in names:images[name],origins[name]=reconstruct(root,folder,name,dependencies)
    hashes={rel:fingerprint_file(checked_file(root,rel)) for rel in sorted(dependencies)}
    if any(initial.get(rel)!=sha for rel,sha in hashes.items()):raise ValueError('导入过程中CG素材改变，请重试')
    payload=json.dumps({'version':VERSION,'group':group,'inputs':hashes},sort_keys=True).encode()
    key=hashlib.sha256(payload).hexdigest()[:24]
    out=root/'character_exports/cg_sequences'/key
    # Only our derived namespace, never overwrite original source data.
    probe=root
    for part in out.relative_to(root).parts:
        probe=probe/part
        if probe.is_symlink() or not probe.resolve().is_relative_to(root):raise ValueError('CG缓存目录不得使用越界链接')
    out.mkdir(parents=True,exist_ok=True)
    frames=[]
    for name,image in images.items():
        target=out/(name+'.png')
        if target.is_symlink():raise ValueError('CG缓存文件不得使用符号链接')
        buffer=BytesIO();image.save(buffer,format='PNG');_write(target,buffer.getvalue())
        frames.append({'name':name,'relative_path':target.relative_to(root).as_posix(),
                       'file_hash':fingerprint_file(target),'width':image.width,'height':image.height,'origin':origins[name]})
        image.close()
    doc={'schema':VERSION,'kind':'cg_sequence','group':group,'inputs':hashes,'frames':frames,
         'steps':steps,'script':script,'other_script_count':len(scripts)-1,'manual_advance':True,
         'limitations':['手动推进；不等于原作自动时间轴','仅完整画面和交叉淡化，镜头/音效/台词未还原'],
         'unsupported':unsupported}
    target=out/'sequence.json'
    if target.is_symlink():raise ValueError('CG清单不得使用符号链接')
    _write(target,json.dumps(doc,ensure_ascii=False,sort_keys=True).encode('utf-8'))
    relative=target.relative_to(root).as_posix();sha=fingerprint_file(target)
    return {'asset_id':stable_asset_id('cgseq',relative,sha),'relative_path':relative,'file_hash':sha,
            'extension':'.cgseq','bytes':target.stat().st_size,'category':'unknown','verified':False,
            'safe_for_auto':False,'title':group+'（差分演出）','location_ids':[],'tags':[], 'group':group}


def load(root,item):
    """Review pins the manifest AND every original/derived dependency."""
    path=checked_file(root,item['relative_path'],allowed_extensions={'.json'},max_bytes=256*1024)
    if fingerprint_file(path)!=item['file_hash']:raise ValueError('CG演出清单已改变，需要重新导入审核')
    doc=json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema')!=VERSION or doc.get('kind')!='cg_sequence':raise ValueError('CG清单版本无效')
    if not 1<=len(doc.get('frames',[]))<=32 or not 1<=len(doc.get('steps',[]))<=100:raise ValueError('CG清单数量无效')
    for relative,sha in doc['inputs'].items():
        if fingerprint_file(checked_file(root,relative))!=sha:raise ValueError('CG原素材或脚本已变更，需要重新导入审核')
    for f in doc['frames']:
        if fingerprint_file(checked_file(root,f['relative_path'],allowed_extensions={'.png'}))!=f['file_hash']:raise ValueError('CG合成缓存已变更，需要重新导入审核')
    return doc


def public(root,item):
    doc=load(root,item);index={f['name']:i for i,f in enumerate(doc['frames'])}
    return {'asset_id':item['asset_id'],'group':doc['group'],'manual_advance':True,
            'limitations':doc['limitations'],'unsupported':doc['unsupported'],
            'frames':[{'name':f['name'],'width':f['width'],'height':f['height'],
                       'url':'/api/game/cg/frame/'+item['asset_id']+'/'+str(i)} for i,f in enumerate(doc['frames'])],
            'steps':[{'frame_index':index[s['frame']],'transition_ms':s['transition_ms'],'line':s['line'],'unsupported':s['unsupported']} for s in doc['steps']]}


def frame_bytes(root,item,index):
    doc=load(root,item)
    if type(index) is not int or not 0<=index<len(doc['frames']):raise ValueError('CG帧编号无效')
    f=doc['frames'][index]
    return checked_file(root,f['relative_path'],allowed_extensions={'.png'}).read_bytes()
