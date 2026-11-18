# Cutcraft · 剪辑配方库

从剪辑教程提炼可复刻的效果，使用自己的素材生成视频和可继续修改的工程。每个公开的 Skill 都带有预览、完整制作说明和一段可直接复制给 AI Agent 的中文提示词。

**[打开剪辑配方库](https://qianqiu-max.github.io/cutcraft-skills/)** · [下载全部已发布 Skill](https://qianqiu-max.github.io/cutcraft-skills/downloads/cutcraft-skills.zip)

## 怎样用

1. 在展示页选一个效果，播放示例，查看需要提供的素材。
2. 点击「复制提示词」，发给能读取文件、运行脚本的 AI Agent，再附上自己的视频、图片或本地素材目录。通用教程复刻还需要原教程或参考效果。
3. 提示词自带完整包和源码地址。Agent 按 `SKILL.md` 读取脚本、确认依赖、用你的素材制作。无法访问网络的环境可以先下载并解压相应技能包，再把文件夹交给 Agent。
4. 用首帧、运动中段和结尾对照预览，检查成片和可编辑工程。复杂效果受输入构图、字体、遮罩和目标软件版本影响。

| Skill | 适用场景 |
| --- | --- |
| [唱片转场](skills/vinyl-record-transition/) | 从自己的封面或素材生成旋转黑胶、封面及遮挡转场，保留可编辑的 Blender 工程。 |
| [漂浮文字](skills/floating-text-video/) | 将文案分层漂移，按主体蒙版控制文字和主体的前后关系。 |
| [教程复刻](skills/tutorial-video-recreation/) | 把新教程拆成时间码、图层、关键帧及验收点，再换成自己的素材重做。页面演示的是拆解过程。 |
| [纸飞机拉幕开场](skills/airplane-curtain-reveal/) | 黑场先从片名笔画透出风景，折纸飞机斜飞拉开弧形幕。可换图片、视频或片名，并保留可重渲工程。 |
| [文字穿越开场](skills/text-flythrough-opening/) | 让视频透过标题显现，沿一笔推近到全屏。可换片名、调整入场节奏，并保留底片的运动和声音。 |

Skill 遵循公开目录格式，可以直接下载。实际执行需要对应的 Python、FFmpeg、Blender 或剪辑软件，依赖见各自的说明。每次制作只准备所选 Skill 需要的工具。[Agent Skills 格式](https://agentskills.io/specification)

黑胶样片通过 Blender 分层工程渲染，漂浮文字样片由独立文字和主体蒙版合成，通用教程页用同一组素材演示拆解流程。纸飞机样片用独立的字形和弧形蒙版揭开原创风景，再用同一脚本输出，制作方法随技能一起下载。

## 收录下一条教程

新作品放在 `skills/<英文短名>/`。展示页、搜索、分类、复制提示词与 ZIP 均从这些目录生成。无需改首页列表。草稿可以先入库，完成样片和验收后再公开展示。[新增指南](docs/adding-a-skill.md) · [工具选型](docs/tools.md)

## 本地预览

需要 Python 3.10 或更高版本。网站构建只用 Python 标准库。

```sh
python -m unittest discover -s tests
python scripts/build.py
python -m http.server 8000 --directory dist
```

打开 `http://localhost:8000`。推送到 `main` 后，GitHub Actions 会运行测试、构建静态站并发布到 Pages。展示页只播放公共样片和复制文本，用户素材在实际执行制作的 Agent 或编辑器里处理。
