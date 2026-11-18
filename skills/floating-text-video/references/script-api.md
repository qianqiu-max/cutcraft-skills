# 本地脚本接口

脚本是可编辑的合成助手，可生成透明文字层交给剪辑软件，也可在已有正确人物遮罩时直接输出演示成片。它们不调用模型，不自动识别人物，不安装依赖，也不生成任何软件的原生工程。原生项目由 Agent 按软件流程另行保存。

## 环境

- Python 3.10+；`scripts/requirements.txt` 中的 NumPy、Pillow、OpenCV。
- FFmpeg 和 FFprobe。默认从 PATH 查找；`prepare.py` / `render.py` 可设置环境变量 `FFMPEG` / `FFPROBE` 为完整可执行文件路径，或传其支持的 `--ffmpeg` / `--ffprobe` 参数。`inspect_output.py` 使用 PATH 中的工具。
- 含所需字符的字体文件。优先显式 `--font`；省略时仅尝试常见 Windows 行楷/楷体、macOS PingFang、Linux Noto CJK 路径，找不到则报错。
- 自动检查常见缺字情况，但仍须查看字形预览。字体许可证没有自动核验；字体不会复制到工程或 Skill。

以下把本 Skill 根目录记作 `<SKILL>`，独立工程目录记作 `<PROJECT>`。所有路径含空格时加引号。命令示例中的占位符需替换。

## 1. 准备素材与工程

把选定文案保存为 UTF-8 文本，每行一列文字，建议每行 4–9 字，脚本上限 32 字。当前脚本做逐字竖排，适合汉字书法；英文短语横排等排版需使用原生软件或改脚本，不能误称已支持。

```sh
python "<SKILL>/scripts/prepare.py" --source "photo.png" --text-file "text.txt" --font "font.ttf" --project "<PROJECT>" --width 1920 --height 1080 --fps 30 --duration 10
```

允许的参数：

| 参数 | 含义 |
| --- | --- |
| `--source` | 不透明背景图片或视频；复制到新工程 assets/source.*，不改原件 |
| `--text-file` | UTF-8 文案文件；复制为工程 text.txt |
| `--font` | 字体文件；路径记入配置但不复制，换机器时需重新指定 |
| `--project` | 新目录或空目录；已有内容时拒绝创建 |
| `--width` / `--height` | 输出尺寸；只提供一个时按素材比例推导，省略时最长不超过 1920、画高不超过 1080；向下取偶数 |
| `--fps` | 默认 30，必须为正 |
| `--duration` | 图片默认 10 秒；视频默认不超过 10 秒且不超素材余量；向下取整到完整帧 |
| `--source-start` | 原视频入点，秒，默认 0 |
| `--mask` | 可选灰度遮罩图片或视频；输入尺寸应与背景原始显示尺寸相同 |
| `--mask-start` | 遮罩视频入点；默认与 source-start 一致；裁剪过的遮罩可设 0 |
| `--ffprobe` | FFprobe 完整路径，可选 |

素材不足会报错，不会擅自循环。视频中途起剪时，背景、遮罩和原音频必须采用一致时间范围。预处理只复制素材并建参数；没有遮罩时仍能准备工程，但合成成片会拒绝，透明字层可以正常渲染。

## 2. scene.json

工程中的相对路径均相对 scene.json 所在目录。默认配置样式：

```json
{
  "version": 1,
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "duration": 10,
  "source": {"path": "assets/source.png", "kind": "image", "start": 0},
  "mask": {"path": "assets/mask.png", "kind": "image", "start": 0},
  "font": "/path/to/font.ttf",
  "protect_subject": true,
  "allow_unprotected": false,
  "audio": "none",
  "camera_zoom": 0.035,
  "layers": [
    {"text": "清风穿过旧长街", "kind": "gold", "x": 0.1, "y": 0.1, "size": 100, "vx": 275, "phase": 0, "angle": -2}
  ]
}
```

- `source.kind` / `mask.kind`：`image` 或 `video`。图片按 EXIF 转正、视频按显示旋转信息读取，遮罩必须与转正后的尺寸/方向一致。
- `mask`：默认 `null`。白色保护主体、黑色允许文字，灰色为边缘过渡。图片使用静态遮罩；视频必须使用逐时刻对应的视频遮罩，脚本拒绝给动态视频套单张静态遮罩。
- `protect_subject`：默认 true。只有明确无需保护主体的场景，才能同时设置 false 与 `allow_unprotected: true`；不得用这个开关绕过“不能遮挡人物”。
- `audio`：`source` 仅在背景为视频时保留对应入点的原音频；`none` 为静音。透明字层始终无音轨。图片默认无声。
- `camera_zoom`：总推近比例，默认 0.035，可设 0。背景和遮罩共用同一矩阵；文字合成后恢复原主体像素，不再对主体做全局模糊。
- `x` / `y`：初始中心横坐标和字列顶部纵坐标，相对画面宽高；可以位于画外。
- `size`：1080 高基准字号；`vx`：1080 高基准的每秒水平像素，必须为正，随画高等比缩放。
- `kind`：`far` 为较虚小白字、`white` 为清晰白字、`gold` 为金色发光字。图层数组顺序从后到前。
- `phase` / `angle`：轻微摆动的相位（弧度）与固定倾角（度）。主要运动始终向右，不会被正弦摆动替代。

模板生成 9 列远景、7 列白字、5 列金字，速度分别为 85、165、275 px/s。这是起始参数，按画面密度、字体和用户反馈调整，并非所有作品必须使用 21 列。

## 3. 生成与检查

```sh
python "<SKILL>/scripts/render.py" --project "<PROJECT>" --mode overlay --still 2
python "<SKILL>/scripts/render.py" --project "<PROJECT>" --mode overlay
python "<SKILL>/scripts/render.py" --project "<PROJECT>" --mode composite --still 2
python "<SKILL>/scripts/render.py" --project "<PROJECT>" --mode composite
```

- `overlay` 输出 `output/overlay.mov`：ProRes 4444，真实 alpha，只有漂浮文字和光晕，无背景和遮罩要求。默认以直通/straight alpha 送编码器；在目标软件里检查黑边/亮边并设置正确 alpha 解释。
- `composite` 输出 `output/composite.mp4`：H.264、yuv420p，背景+字层+人物保护；需要匹配遮罩。
- `--still SECONDS` 输出 PNG；overlay 为 RGBA，composite 为 RGB。取该时刻对应的前一完整输出帧；视频从入点依次解码到该帧，长素材的远端静帧可能较慢。
- `--output PATH` 可更改文件名， relative 路径相对工程；后缀必须符合模式（PNG/MOV/MP4）。
- 默认不覆盖输出。需要重写同一个成品时显式 `--overwrite`；任何模式都禁止覆盖源素材、字体、遮罩或 scene.json。
- 视频先写带 `.partial-随机值` 的临时文件，编码成功后才改为最终文件名；失败时检查旁边 `.log`，不能把 partial 文件标作成片。
- CLI 渲染成功只说明编码结束，还要做解码、视觉和音频检查。ProRes alpha 已通过文件级检查不等于所有剪辑软件版本都能正确导入，实际导入后必须验证透明度。

如果目标软件不接受该 MOV，可用本机 FFmpeg 转为 RGBA PNG 序列并按原帧率导入；这仍需要验证目标软件的图像序列支持。不要改为黑底 MP4 后声称有透明通道。

```sh
ffmpeg -i "<PROJECT>/output/overlay.mov" -pix_fmt rgba "<PROJECT>/output/overlay-%05d.png"
```

## 4. 换机器或编辑器

复制完整工程，包括原素材、蒙版和配置。把 scene.json 的 font 值重新指向目标设备上覆盖相同文字的字体，可使用相对于工程的路径；请先确认字体是否允许随工程分发。变更字体后检查字形、行距与遮挡边缘。

合成脚本负责编辑时间和已准备的前景保护。复杂运动跟踪、自动人物分割、HDR 调色与目标编辑器的 alpha 解释需要另行处理。具体核验方法见[效果检查](validation.md)。
