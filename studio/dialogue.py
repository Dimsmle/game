"""Authored, silent dialogue scenes using the same semantic expression resolver as AI."""
from copy import deepcopy
from . import behavior


def line(id,text,emotion,next=None,choices=None,place="午后 · 客厅",scene="day"):
    value={"id":id,"speaker":"character","text":text,"emotion":emotion,
           "action_tag":"idle","scene":scene,"place":place,"next":next}
    if choices:value["choices"]=[{"text":text,"next":target} for text,target in choices]
    return value


SCENES=(
    {"id":"promise","title":"迟到的约定","description":"从担心、闹别扭到释然；你的回应会改变接下来的话。",
     "start":"waiting","nodes":[
        line("waiting","你终于来了……我刚才还以为，今天见不到你了。","worried","complaint"),
        line("complaint","说好只等一小会儿的。下次再迟到，我可真的要生气了。","pouting","reply"),
        line("reply","不过，你路上没有遇到什么事吧？","worried",choices=[
            ("对不起，让你担心了。我下次会提前告诉你。","apology"),
            ("我去买了你喜欢的点心，想给你一个惊喜。","gift")]),
        line("apology","……嗯。听你这么说，我就放心了。","gentle","honest"),
        line("gift","诶？你还记得我喜欢吃什么？","surprised","blush"),
        line("blush","突然这样，我都不知道该怎么回答了……谢谢。","shy","honest"),
        line("honest","其实，比起点心，我更想和你好好待一会儿。","affectionate","end"),
        line("end","那，今天剩下的时间，就分一点给我吧。","happy"),
     ]},
    {"id":"tired_day","title":"今天有点累","description":"她先认真倾听，再慢慢安慰你。可以选择倾诉，也可以安静陪伴。",
     "start":"notice","nodes":[
        line("notice","你今天好像比平时安静。发生什么事了吗？","serious","listen",place="傍晚 · 窗边",scene="evening"),
        line("listen","不用急着说。如果愿意的话，我会认真听。","gentle",choices=[
            ("今天做的事情都不太顺利，有点失落。","sad"),
            ("暂时不想说，能安静陪我坐一会儿吗？","quiet")],place="傍晚 · 窗边",scene="evening"),
        line("sad","努力了一天却没得到想要的结果……一定很不好受吧。","sad","think",place="傍晚 · 窗边",scene="evening"),
        line("think","让我想想……今晚先不逼自己把所有问题都解决，好不好？","thinking","rest",place="傍晚 · 窗边",scene="evening"),
        line("quiet","当然可以。你不用为了照顾我的心情，勉强自己说话。","gentle","rest",place="傍晚 · 窗边",scene="evening"),
        line("rest","天已经黑了。我们先把灯打开，再给自己一点休息的时间。","gentle","end",place="夜晚 · 客厅",scene="night"),
        line("end","今天辛苦了。明天的事情，明天再一起想吧。","happy",place="夜晚 · 客厅",scene="night"),
     ]},
    {"id":"surprise","title":"藏起来的小惊喜","description":"一个小误会：不安、惊讶、害羞，再到藏不住的开心。",
     "start":"secret","nodes":[
        line("secret","你一直把手藏在身后……是不是有什么话想对我说？","thinking","worry"),
        line("worry","等、等一下，难道是我做错了什么？","worried",choices=[
            ("没有，是想把这份小礼物送给你。","gift"),
            ("只是想认真地告诉你：和你在一起很开心。","words")]),
        line("gift","给我的？我还以为……啊，原来是这样。","surprised","shy"),
        line("words","诶……突然这么认真，我会不好意思的。","shy","shy"),
        line("shy","你先别一直看着我。我的脸现在一定很红。","embarrassed","warm"),
        line("warm","不过，能听到你这样说，我真的很开心。","happy","end"),
        line("end","那我也认真回答你：我也很珍惜和你待在一起的时间。","affectionate"),
     ]},
)


def summaries():
    return [{"id":s["id"],"title":s["title"],"description":s["description"],
             "line_count":len(s["nodes"])} for s in SCENES]


def compile_scene(scene_id,model_name,catalog,library):
    source=next((s for s in SCENES if s["id"]==scene_id),None)
    if source is None:raise ValueError("未知的预设对话场景")
    if not catalog:raise ValueError("请先在设置中选择已解包的角色")
    result=deepcopy(source)
    result["model"]=model_name
    result["silent"]=True
    for node in result["nodes"]:
        intent={"speech":node["text"],"emotion":node["emotion"],"action_tag":"idle","scene":""}
        node["behavior"]=behavior.resolve_behavior(intent,model_name,catalog,library,[])
    return result
