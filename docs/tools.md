# 教程复刻的工具怎么选

优先依据教程需要复刻的动作选引擎，再确定要交源码、剪辑时间线还是原生工程。以下工具都可以参与 AI 剪辑流程，调用入口和产物各不相同。

| 任务 | 工具与接入方式 | 可复用的产物与边界 |
| --- | --- | --- |
| 看懂教程 | 本地 faster-whisper 做带时间转写，PySceneDetect 找镜头变化，FFmpeg 在关键区间密集取帧。需要用多模态 API 解读长教程时可选 Gemini。 | 输出时间码、转写、代表帧和分镜说明。遮挡方向和短闪光要回到原始帧判断。[faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [PySceneDetect](https://www.scenedetect.com/docs/latest/cli.html) · [Gemini](https://ai.google.dev/gemini-api/docs/video-understanding) |
| 口播粗剪与基础合成 | auto-editor 适合按音量或运动阈值剪去长空段。FFmpeg / ffprobe 负责滤镜、裁切、叠加、混音和解码检查。 | 输出剪辑序列、命令参数和影片。重录取舍需结合语义。做 `xfade` 需统一两端的帧率、时间基、分辨率和像素格式。[auto-editor](https://github.com/WyattBlue/auto-editor) · [FFmpeg](https://ffmpeg.org/ffmpeg-filters.html#xfade) |
| 动态字幕、卡片、界面或图解 | HyperFrames 写 HTML/CSS 与可定位的动画。React 项目可用 Remotion，CLI 接收每条视频的参数，并有官方 Agent Skills。 | 网页或组件工程、素材清单、参数和 MP4。适合换文案、配色、排版。[HyperFrames](https://github.com/heygen-com/hyperframes) · [Remotion](https://www.remotion.dev/docs/ai/skills) |
| 复杂遮罩、多轨或立体运镜 | Blender 后台调用 Python，生成 `.blend`。普通多轨工程也可用 MLT XML、melt CLI 和 Shotcut。 | 可保留遮罩、关键帧、分轨和素材引用。在目标版本复开，检查每层是否仍可改。[Blender](https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html) · [MLT](https://www.mltframework.org/docs/mltxml/) · [Shotcut](https://shotcut.org/FAQ/) |
| 在国内剪映里接着剪 | 社区 Python 库 pyJianYingDraft 可生成含轨道、关键帧和字幕的剪映草稿。国际版 CapCut 使用单独的项目。 | 草稿生成、模板读取、自动导出分别受剪映版本限制。先用一份小工程验证目标版本。[剪映草稿库](https://github.com/GuanYixuan/pyJianYingDraft) · [pyCapCut](https://github.com/GuanYixuan/pyCapCut) |
| 想看现成的 Agent 剪辑工具 | OpenFilm 提供 Agent 与人共享的编辑界面。browser-use/video-use 把口播整理、波形复核、动画叠加和渲染做成了工作流。 | 前者方便人接手修改。后者的默认转写流程依赖 ElevenLabs 密钥，Windows 运行条件需另验。[OpenFilm](https://github.com/openfilm/openfilm) · [video-use](https://github.com/browser-use/video-use) |
| 云端协作或批量生产 | Descript 提供转写、字幕与粗剪接口。Shotstack 接收 JSON 时间线并云渲染。 | 适合可上传素材且已有服务账号的项目。精确特效还需确定性的参数和渲染工具。[Descript](https://www.descript.com/api) · [Shotstack](https://shotstack.io/docs/api/) |
