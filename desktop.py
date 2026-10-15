# -*- coding: utf-8 -*-
"""Native tkinter pose preview; does not open a browser."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
import time

try:
    from PIL import ImageTk
except ImportError:
    ImageTk=None

from emote_model import find_model, PoseModel
from pose_renderer import AtlasRenderer

DEFAULT_ROOT=Path(r"G:\开发游戏\Amakano3_AI")
DEFAULT_QUICK=("普通Ａ","笑顔Ａ","驚きＡ","悲しみＡ")

def export_poses(renderer, out_dir, names=DEFAULT_QUICK, size=(740,1250)):
    out=Path(out_dir)
    out.mkdir(parents=True,exist_ok=True)
    files=[]
    for idx,name in enumerate(names):
        img=renderer.render(name,size=size)
        path=out/("%02d_%s.png"%(idx+1,name.replace("/","_").replace("\\","_")))
        img.save(path)
        files.append(path)
    return files

def export_gif(renderer,path,preset, size=(480,810)):
    # Texture-switching demo ONLY. Mesh physics, actual E-mote curves and masks are absent.
    blink=[0,0,0,10,24,40,23,0,0,0,0,0]
    mouth=[0,0,1,3,5,2,0,0,3,5,0,0]
    frames=[]
    for eye,talk in zip(blink,mouth):
        img=renderer.render(preset,overrides={"face_eye_open":eye,"face_talk":talk},size=size)
        frame=AtlasRenderer.preview_checker(img).convert("RGB")
        frames.append(frame)
    frames[0].save(path,format="GIF",save_all=True,append_images=frames[1:],
                   duration=140,loop=0,optimize=False)
    return Path(path)

def run_gui(model,renderer,export_dir):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    if ImageTk is None:
        raise RuntimeError("缺少 Pillow：请先运行 pip install pillow")
    class App:
        def __init__(self):
            self.root=tk.Tk()
            self.root.title("Character Pose Lab v0.3 · E-mote 静态姿势自动组装预览")
            self.root.geometry("1160x870")
            self.root.minsize(930,660)
            self.root.configure(background="#151d2b")
            self.preset=tk.StringVar(value=model.presets[0].get("label","") if model.presets else "")
            self.eye=tk.DoubleVar(value=0)
            self.talk=tk.DoubleVar(value=0)
            self.auto_blink=tk.BooleanVar(value=False)
            self.auto_mouth=tk.BooleanVar(value=False)
            self.status=tk.StringVar(value="准备就绪")
            self.info=tk.StringVar(value="")
            self.hidden=set()
            self.eye_baseline=0
            self.ui_job=None
            self.photo=None
            self.last_image=None
            self.grid_rows={}
            self._init_ui()
            self.root.after(150,self.redraw)
            self.root.after(3100,self.tick)

        def _init_ui(self):
            h=ttk.Frame(self.root,padding=(16,13))
            h.pack(fill="x")
            ttk.Label(h,text="Character Pose Lab",font=("Microsoft YaHei UI",18,"bold")).pack(side="left")
            ttk.Label(h,text="真实 JSON + 纹理图集  |  静态近似渲染，不是完整 E-mote 播放",foreground="#bd7133").pack(side="left",padx=(18,0))
            content=ttk.Panedwindow(self.root,orient="horizontal")
            content.pack(fill="both",expand=True,padx=12,pady=(0,8))
            left=ttk.Frame(content)
            right=ttk.Frame(content,width=390)
            content.add(left,weight=3);content.add(right,weight=2)
            self.preview=ttk.Label(left,anchor="center",text="正在自动组装实际角色图层...")
            self.preview.pack(fill="both",expand=True,padx=4,pady=4)
            self.preview.bind("<Configure>",lambda e:self._show_image())
            self.bottom=ttk.Label(left,textvariable=self.info,anchor="w")
            self.bottom.pack(fill="x",padx=8,pady=(0,6))

            top=ttk.Frame(right,padding=(9,5))
            top.pack(fill="x")
            ttk.Label(top,text="角色表情时间轴",font=("Microsoft YaHei UI",12,"bold")).pack(anchor="w")
            choices=[p.get("label","") for p in model.presets]
            combo=ttk.Combobox(top,textvariable=self.preset,values=choices,state="readonly",width=34)
            combo.pack(fill="x",pady=8)
            combo.bind("<<ComboboxSelected>>",lambda _e:self.pick_preset(self.preset.get()))
            quick=ttk.Frame(top);quick.pack(fill="x")
            for nm in DEFAULT_QUICK:
                if nm in choices:
                    ttk.Button(quick,text=nm,command=lambda n=nm:self.pick_preset(n)).pack(side="left",padx=2)
            ttk.Separator(top).pack(fill="x",pady=12)
            ttk.Label(top,text="眼睛开合（使用 JSON 中的 face_eye_open 变量）").pack(anchor="w")
            ttk.Scale(top,from_=-10,to=50,orient="horizontal",variable=self.eye,
                      command=lambda _v:self.schedule_redraw()).pack(fill="x",pady=5)
            ttk.Label(top,text="张嘴参数（face_talk，范围 0–5）").pack(anchor="w",pady=(8,0))
            ttk.Scale(top,from_=0,to=5,orient="horizontal",variable=self.talk,
                      command=lambda _v:self.schedule_redraw()).pack(fill="x",pady=5)
            ttk.Checkbutton(top,text="自动眨眼（贴图状态演示）",variable=self.auto_blink).pack(anchor="w",pady=4)
            ttk.Checkbutton(top,text="模拟说话嘴型（未连接 TTS）",variable=self.auto_mouth).pack(anchor="w",pady=4)
            ttk.Separator(top).pack(fill="x",pady=12)

            toolbar=ttk.Frame(top)
            toolbar.pack(fill="x",pady=4)
            ttk.Button(toolbar,text="重新渲染",command=self.redraw).pack(side="left",padx=3)
            ttk.Button(toolbar,text="保存当前 PNG",command=self.save_png).pack(side="left",padx=3)
            ttk.Button(top,text="一键导出 4 个常用表情 PNG",command=self.save_bundle).pack(fill="x",pady=3)
            ttk.Button(top,text="导出演示 GIF（非原版动画）",command=self.save_demo_gif).pack(fill="x",pady=3)
            ttk.Label(top,text="导出透明 PNG 可作为 Character Lab 的人物图层",foreground="#697e9b",
                      wraplength=350).pack(anchor="w",pady=6)
            ttk.Separator(top).pack(fill="x",pady=9)
            ttk.Label(top,text="自动识别的图层（双击切换显示 / 隐藏）",
                      font=("Microsoft YaHei UI",11,"bold")).pack(anchor="w")
            ttk.Label(top,text="遇到重叠异常可隐藏单个图层再对比。",foreground="#697e9b").pack(anchor="w")
            box=ttk.Frame(top)
            box.pack(fill="both",expand=True,pady=5)
            self.tree=ttk.Treeview(box,columns=("id","z","status"),show="headings",height=12)
            self.tree.heading("id",text="图块 / 部件")
            self.tree.heading("z",text="层级")
            self.tree.heading("status",text="显示")
            self.tree.column("id",width=225,anchor="w")
            self.tree.column("z",width=53,anchor="e")
            self.tree.column("status",width=48,anchor="center")
            scroll=ttk.Scrollbar(box,orient="vertical",command=self.tree.yview)
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.pack(side="left",fill="both",expand=True)
            scroll.pack(side="right",fill="y")
            self.tree.bind("<Double-1>",lambda e:self.toggle_selected_layer())
            buttons=ttk.Frame(top);buttons.pack(fill="x")
            ttk.Button(buttons,text="显示全部",command=self.show_all_layers).pack(side="left")
            ttk.Button(buttons,text="复制诊断摘要",command=self.copy_report).pack(side="left",padx=6)

            footer=ttk.Frame(self.root,padding=(14,5))
            footer.pack(fill="x")
            ttk.Label(footer,textvariable=self.status).pack(side="left",fill="x",expand=True)
            ttk.Label(footer,text="PyCharm / Conda / Windows · 可用 PyInstaller 打包").pack(side="right")
        def pick_preset(self,preset):
            self.preset.set(preset)
            vars=model.preset_vars(preset)
            eye=vars.get("face_eye_open",0)
            talk=vars.get("face_talk",0)
            self.eye_baseline=int(eye) if isinstance(eye,(int,float)) else 0
            self.eye.set(self.eye_baseline)
            self.talk.set(float(talk) if isinstance(talk,(int,float)) else 0)
            self.schedule_redraw()
        def schedule_redraw(self):
            if self.ui_job is not None:
                self.root.after_cancel(self.ui_job)
            self.ui_job=self.root.after(140,self.redraw)
        def redraw(self):
            self.ui_job=None
            try:
                overrides={"face_eye_open":int(round(self.eye.get())),
                           "face_talk":float(self.talk.get())}
                self.last_image=renderer.render(self.preset.get(),overrides=overrides,
                       size=(700,1170),hidden_icons=self.hidden)
                self._show_image()
                self.render_tree()
                meta=model.last_summary
                self.info.set(f"可见图块 {len(renderer.draw_info)} / 当前姿势 {meta['sprites']}  "
                              f"| 层级节点 {meta['total_layers_visited']}  "
                              f"| 未解码网格 / 遮罩")
                self.status.set("自动组装完成（静态近似）；图集缩放系数："
                   f"{renderer.atlas_sx:.3f} × {renderer.atlas_sy:.3f}")
            except Exception as e:
                self.status.set("渲染失败："+str(e))
                messagebox.showerror("渲染异常",str(e))
        def _show_image(self):
            if self.last_image is None:return
            w=max(self.preview.winfo_width()-12,200)
            h=max(self.preview.winfo_height()-12,200)
            view=self.last_image.copy()
            view.thumbnail((w,h),resample=2)
            checker=AtlasRenderer.preview_checker(view)
            self.photo=ImageTk.PhotoImage(checker)
            self.preview.configure(image=self.photo,text="")
        def render_tree(self):
            for row in self.tree.get_children():
                self.tree.delete(row)
            for entry in renderer.draw_info:
                icon=entry["key"]
                self.tree.insert("", "end",iid=icon,
                    values=(f'{icon}  {entry["label"]}',int(entry["z"]),
                            "隐藏" if icon in self.hidden else "显示"))
            for icon in sorted(self.hidden):
                if not self.tree.exists(icon):
                    self.tree.insert("","end",iid=icon,values=(icon,"","隐藏"))
        def toggle_selected_layer(self):
            row=self.tree.focus()
            if not row:return
            if row in self.hidden:self.hidden.remove(row)
            else:self.hidden.add(row)
            self.schedule_redraw()
        def show_all_layers(self):
            self.hidden.clear();self.schedule_redraw()
        def tick(self):
            if self.auto_blink.get():
                self.eye.set(36)
                self.schedule_redraw()
                self.root.after(190,lambda:self._stop_blink())
            if self.auto_mouth.get():
                self.talk.set(3 if self.talk.get()<1 else 0)
                self.schedule_redraw()
            self.root.after(3100,self.tick)
        def _stop_blink(self):
            self.eye.set(self.eye_baseline);self.schedule_redraw()
        def save_png(self):
            initial=export_dir/("kan_0_"+str(model.label_to_preset.get(self.preset.get(),0))+".png")
            chosen=filedialog.asksaveasfilename(initialdir=str(export_dir),
                 initialfile=initial.name,defaultextension=".png",
                 filetypes=[("PNG 图片","*.png")])
            if not chosen:return
            try:
                image=renderer.render(self.preset.get(),
                    overrides={"face_eye_open":int(round(self.eye.get())),
                               "face_talk":float(self.talk.get())},
                    size=(1100,1830),hidden_icons=self.hidden)
                image.save(chosen)
                self.status.set("已保存 PNG："+chosen)
            except Exception as e:messagebox.showerror("保存失败",str(e))
        def save_bundle(self):
            try:
                paths=export_poses(renderer,export_dir,names=tuple(
                    name for name in DEFAULT_QUICK if name in model.label_to_preset))
                messagebox.showinfo("已导出",f"已生成 {len(paths)} 张透明 PNG：\n"+str(export_dir))
            except Exception as e:messagebox.showerror("导出失败",str(e))
        def save_demo_gif(self):
            try:
                out=export_dir/"kan_0_演示动画_非原版.gif"
                export_gif(renderer,out,self.preset.get())
                messagebox.showinfo("已保存","模拟眨眼/口型 GIF 已生成。\n"+str(out)+
                    "\n这不是原版 E-mote 动画。")
            except Exception as e:messagebox.showerror("导出失败",str(e))
        def copy_report(self):
            txt=(f"PSB JSON: {model.path}\n"
                 f"纹理组：{renderer.texture_paths}\n"
                 f"解析运动对象：{len(model.objects)}\n"
                 f"图集块：{model.icon_count}\n"
                 f"预设：{len(model.presets)}\n"
                 f"画布：{model.data.get('screenSize')}\n"
                 f"坐标范围：{model.last_summary.get('visual_bounds')}\n"
                 f"静态绘制命令：{model.last_summary.get('sprites')}\n"
                 f"未实现：顶点网格组合、模板遮罩、物理和高阶过渡。")
            self.root.clipboard_clear();self.root.clipboard_append(txt)
            self.status.set("诊断摘要已复制，可以粘贴给我。")
        def run(self):
            self.root.mainloop()
    App().run()

def main():
    ap=argparse.ArgumentParser(description="使用真实 E-mote PSB JSON 自动组装角色静态预览")
    ap.add_argument("--root",default=str(DEFAULT_ROOT),help="含解包结果的根目录")
    ap.add_argument("--json",help="主 JSON（kan_0.json）")
    ap.add_argument("--resx",help="resx JSON（kan_0.resx.json）")
    ap.add_argument("--texture",help="单张纹理的手动指定路径；多图集请使用自动发现")
    ap.add_argument("--out",help="透明 PNG/GIF 输出目录")
    ap.add_argument("--headless",action="store_true",help="仅生成 4 种表情 PNG，不打开窗口")
    ap.add_argument("--preset",default="普通Ａ",help="渲染预设名称，仅适用于 --headless --single")
    ap.add_argument("--single",action="store_true",help="只导出一张 PNG")
    args=ap.parse_args()
    root=Path(args.root)
    try:
        path=Path(args.json) if args.json else find_model(root)
        model=PoseModel(path,args.resx)
        if args.texture and len(model.icon_groups)!=1:
            raise ValueError("当前模型有多张图集，不能只用 --texture 传入其中一张")
        textures=(Path(args.texture) if args.texture else model.discover_textures(root))
        renderer=AtlasRenderer(model,textures)
        output=Path(args.out) if args.out else root/"character_exports"
        output.mkdir(parents=True,exist_ok=True)
        print("JSON：",path)
        print("已加载",len(renderer.texture_paths),"张纹理：")
        for source_name,filename in renderer.texture_paths.items():
            print(" ",source_name,":",filename)
        print("各图集图片尺寸：",{
            name:im.size for name,im in renderer.atlases.items()
        })
        print("静态姿势包含",model.last_summary["sprites"],"个独立精灵部件。")
        print("已有",len(model.presets),"种表情时间轴；当前仅静态近似渲染。")
        if args.headless:
            if args.single:
                if args.preset not in model.label_to_preset:
                    raise ValueError("找不到预设："+args.preset)
                file=output/"kan_0_pose.png"
                renderer.render(args.preset,size=(900,1510)).save(file)
                print("已输出：",file)
            else:
                files=export_poses(renderer,output,
                    tuple(v for v in DEFAULT_QUICK if v in model.label_to_preset))
                for file in files:print("已输出：",file)
        else:
            run_gui(model,renderer,output)
        return 0
    except Exception as e:
        print("错误：",type(e).__name__,str(e))
        if not args.headless:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root_ui=tk.Tk();root_ui.withdraw()
                messagebox.showerror("无法启动",str(e))
                root_ui.destroy()
            except Exception:pass
        return 1

if __name__=="__main__":
    sys.exit(main())
