"""P1 game-state schema and pure rules. No model output is an effect."""
from copy import deepcopy
import re

ID=re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
RANGES={'affection':(0,100),'trust':(0,100),'mood':(-100,100),'energy':(0,100)}
SINGLE_LIMIT={'affection':5,'trust':5,'mood':20,'energy':20}
DAILY_GAIN={'affection':5,'trust':5,'mood':30,'energy':40}
# Minimum affinity AND explicit milestones, never a numeric automatic level-up.
STAGES=(('acquaintance',0,None),('familiar',20,'introduced'),
        ('close',45,'shared_activity'),('intimate',70,'mutual_commitment'),
        ('committed',90,'lasting_bond'))


def identifier(value):
    if not isinstance(value,str) or not ID.fullmatch(value):raise ValueError('游戏标识无效')
    return value


def integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('游戏数值必须为合法整数')
    return value


def new_state(profile_id='default',character_id='legacy_character'):
    return {'schema':1,'profile_id':identifier(profile_id),'character_id':identifier(character_id),
            'revision':0,'stats':{'affection':25,'trust':30,'mood':15,'energy':80},
            'relationship_stage':'acquaintance','milestones':[],'flags':{},
            'scene':{'location_id':'unknown','time_of_day':'unknown','lock':False},
            'event':{'instance_id':None,'status':'idle'},'clock_mode':'manual',
            'toggles':{'proactive_events':False,'touch_interaction':False}}


def validate_state(value):
    if not isinstance(value,dict) or set(value)!=set(new_state()):raise ValueError('游戏存档字段无效')
    if type(value['schema']) is not int or value['schema']!=1:raise ValueError('未知存档版本')
    identifier(value['profile_id']);identifier(value['character_id']);integer(value['revision'],0,2**53-1)
    stats=value['stats']
    if not isinstance(stats,dict) or set(stats)!=set(RANGES):raise ValueError('属性字段无效')
    for key,(low,high) in RANGES.items():integer(stats[key],low,high)
    if not isinstance(value['relationship_stage'],str) or value['relationship_stage'] not in {x[0] for x in STAGES}:raise ValueError('关系阶段无效')
    milestones=value['milestones']
    allowed={x[2] for x in STAGES if x[2]}
    if not isinstance(milestones,list) or len(milestones)>len(allowed) or any(type(x) is not str or x not in allowed for x in milestones) or len(set(milestones))!=len(milestones):raise ValueError('里程碑无效')
    flags=value['flags']
    if not isinstance(flags,dict) or len(flags)>100:raise ValueError('状态标记无效')
    for key,flag in flags.items():
        identifier(key)
        if type(flag) not in (bool,int) or (type(flag) is int and abs(flag)>1000000):raise ValueError('状态标记值无效')
    scene=value['scene']
    if not isinstance(scene,dict) or set(scene)!={'location_id','time_of_day','lock'}:raise ValueError('地点字段无效')
    identifier(scene['location_id'])
    if scene['time_of_day'] not in ('unknown','morning','day','evening','night') or type(scene['lock']) is not bool:raise ValueError('地点状态无效')
    if value['event']!={'instance_id':None,'status':'idle'}:raise ValueError('P1 尚未开放事件')
    if value['clock_mode'] not in ('manual','system','game','off'):raise ValueError('时钟模式无效')
    if not isinstance(value['toggles'],dict) or set(value['toggles'])!={'proactive_events','touch_interaction'} or any(type(item) is not bool for item in value['toggles'].values()):raise ValueError('互动开关无效')
    return deepcopy(value)


def validate_delta(delta,milestone=None):
    if not isinstance(delta,dict) or set(delta)-set(RANGES):raise ValueError('未知属性增量')
    for key,amount in delta.items():integer(amount,-SINGLE_LIMIT[key],SINGLE_LIMIT[key])
    if milestone is not None and (not isinstance(milestone,str) or milestone not in {x[2] for x in STAGES if x[2]}):raise ValueError('未知里程碑')


def apply_delta(state,delta,used=None,milestone=None):
    """Trusted local rule only; caller supplies authoritative per-day usage."""
    value=validate_state(state);used=used or {}
    validate_delta(delta,milestone)
    before=dict(value['stats'])
    for key,amount in delta.items():
        if amount>0:amount=min(amount,max(0,DAILY_GAIN[key]-used.get(key,0)))
        low,high=RANGES[key];value['stats'][key]=max(low,min(high,before[key]+amount))
    if milestone and milestone not in value['milestones']:value['milestones'].append(milestone)
    stage='acquaintance'
    for name,threshold,required in STAGES:
        if value['stats']['affection']<threshold or (required and required not in value['milestones']):break
        stage=name
    # Once earned, a milestone relationship is not erased by transient numbers.
    names=[x[0] for x in STAGES]
    value['relationship_stage']=names[max(names.index(stage),names.index(value['relationship_stage']))]
    value['revision']+=1
    return validate_state(value),{key:value['stats'][key]-before[key] for key in delta}


def prompt_context(state):
    """Small trusted facts only; do not claim an unreviewed location or event."""
    import json
    value=validate_state(state)
    return ('\n可信游戏存档（仅供语气参考，不报数值，不覆盖人物核心，不代表现实关系）：'
            +json.dumps({key:value[key] for key in ('stats','relationship_stage','scene','flags')},ensure_ascii=False)
            +'。只有本机已确认事件日志可作为共同经历；不得自行声称未确认的事件、地点移动或关系里程碑已经发生。'
            '禁止用回复修改数值、存档或文件。\n')
