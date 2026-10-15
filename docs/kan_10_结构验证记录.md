# kan_10 结构验证记录（基于用户提供的主 JSON / resx）

> 本文只记录结构事实与开发结论，不包含原始游戏 JSON、纹理或语音。

## 已验证结构

使用 v0.7 的 `PoseModel` 读取用户提供的 `kan_10.json` 与 `kan_10.resx.json`：

- 时间轴预设：**128**
- 面部预设：**108**
- 动作预设：**20**
- 图集 source：`tex`
- 图块数量：**211**
- `resx.Resources`：`0 → kan_10/tex-texture.png`

因此 `kan_10` 本身是**单纹理页模型**。项目仍保留多纹理页代码，因为其他 PSB 可以是
`tex#000 / tex#001 / ...`，但不能把其它模型的两张图强行拼给 `kan_10`。

## 20 个真实动作预设

1. `待機`
2. `おさんぽ`
3. `はい`
4. `うんうん`
5. `いいえ`
6. `ありがとう`
7. `首かしげ`
8. `ん？`
9. `反応`
10. `びっくり`
11. `思考`
12. `上目遣い`
13. `あまえる`
14. `にっこり`
15. `あざとい`
16. `うん強`
17. `元気`
18. `近づく`
19. `仕草`
20. `キラキラ`

当前 `studio/behavior.py` 为这些名称提供候选语义标签，但只有用户人工看过画面并保存后，
才能把候选看作可靠的动作映射。

## 108 个面部预设的规律

JSON 中可见基础组和至少两组编号变体，例如：

- `普通Ａ / 普通１Ａ / 普通２Ａ`
- `笑顔Ａ / 笑顔１Ａ / 笑顔２Ａ`
- `悲しみＡ / 悲しみ１Ａ / 悲しみ２Ａ`
- `照れＡ / 照れ１Ａ / 照れ２Ａ`

还包括：

- `怒りＡ`
- `不安Ａ`
- `きょとんＡ`
- `驚きＡ`
- `微笑みＡ`
- `イタズラ笑みＡ`
- `困り笑いＡ`
- `うっとりＡ`
- `得意げＡ`
- `ウインク笑みＡ`
- `真剣Ａ`
- `泣くＡ`
- `嬉し泣きＡ`
- `目下閉じＡ`
- `考えるＡ`
- `ジト目Ａ`
- `焦りＡ`
- `慌てるＡ`
- `もーＡ`
- `ほっぺぷくーＡ`
- `目がぐるぐるＡ`
- `感激Ａ`
- `ガーンＡ`
- `＞ワ＜Ａ`
- 以及其它更特殊的面部预设。

v0.7 的语义情绪已扩展，不再只使用 happy/sad：

`neutral, happy, gentle, shy, sleepy, surprised, sad, angry, worried, thinking, crying,
playful, confident, grateful, serious, embarrassed, flustered, annoyed, pouting, moved,
shocked, excited, happy_cry, dazed, wink, affectionate`

## 当前“总是哭脸”的开发判断

JSON 证明模型本身有 `face_tears`、眉毛、特殊眼形、瞳孔、嘴形等独立控制。
因此错误哭脸可能来自：

1. `face_tears` 等变量的参数化取样错误；
2. sprite 离散帧选择规则不完整；
3. 眼/眉/泪水图层的 Z 顺序；
4. E-mote mask/stencil 未实现；
5. meshCombinator/顶点变形未实现；
6. 特定 `Ａ/１Ａ/２Ａ` 组与当前身体/动作模型的组合关系尚未理解。

**后续 Codex 应先做逐参数和逐图层对照，不应“永久隐藏 tears 图层”作为修复。**

## 编号动作家族假设

用户观察 `kan_0–15` 与 `kan_30–45` 可能是两个动作家族、内部服装对应。

v0.7 不把此观察硬编码。请将各模型解包后，通过：

- timeline label set
- object/motion keys
- parameter IDs
- pixel bounds
- icon count / texture count
- mesh data shape
- 实际画面

生成候选家族，再在 UI 的 `pose_family` 中**人工确认**。
