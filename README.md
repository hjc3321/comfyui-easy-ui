# ComfyUI Easy UI

[中文](README.md) | [English](README_EN.md)

一套让 ComfyUI 工作流更好用的易用性节点合集：界面选区的视频/音频加载器、音色参考描述、直观的分辨率选择器，以及「缺图不报错」的占位图片节点。

界面与交互全部原生融入 ComfyUI：多语言（中/英）、节点内嵌 HTML 交互界面（时间轴、裁剪框）、大文件分片上传、桌面绝对路径直接预览。

## 节点一览

| 节点 | 类名 | 说明 |
|---|---|---|
| 加载视频 (界面选区) | `LoadVideoRange` | 在节点界面上选择视频区间（秒/帧可切换）+ 画面裁剪 + 缩放，同时输出「所选视频段」与「整个视频段」 |
| 加载音频 (界面选区) | `LoadAudioRange` | 在节点界面上选择音频区间，同时输出「所选音频段」与「整个音频段」 |
| 音色参考描述 | `VoiceRefDescription` | 分析多路参考音频的音色特征（F0/亮度/质感/语速等），与用途说明拼接成提示词文本 |
| 分辨率选择器·最短边 | `ResolutionSelectorShortSide` | 按「画布比例 + 最短边像素」计算宽高，比百万像素更直观（如竖屏短视频直接填 768/1080） |
| 加载图像 (None占位) | `EasyLoadImage` | 增强版 Load Image：可选 `[None]` 占位，输出 None 而不报错，方便草稿工作流 |
| 批量图像 (跳过None) | `EasyBatchImages` | 增强版 Batch Images：端口动态扩展，None/空输入自动跳过（内置节点会直接报错） |

## 核心功能

### LoadVideoRange / LoadAudioRange

节点界面在画布上直接完成素材选取，无需来回试参数：

- **区间选择**：Time（秒）/ Frames（帧）两种显示模式一键切换，数值双向联动
- **视频裁剪**：8 向手柄 + 3×3 构图线 + 13 种比例约束（16:9、1:1、4:5 小红书……）+ 手动宽高输入
- **时间轴**：刻度尺 + 左右手柄 + 整段拖动，播放时在所选区间内循环预览
- **上传**：`choose file to upload` 按钮 + 拖拽上传；≥10MB 自动分片，同名同大小文件自动去重秒传
- **绝对路径**：桌面版/带 `file.path` 的浏览器拖入本地文件时跳过上传，直接解码原文件
- **双输出**：一次解码同时给出「所选段」与「整段」，配合下游节点做对照处理
- **容错**：空输入输出空白（不崩溃）、无音轨视频自动转静音、缺失音频文件输出 1 秒静音

视频解码采用 **ffmpeg 子进程**（rawvideo rgb24 / f32le PCM），不依赖 `av` / `opencv`，只要系统里能找到 ffmpeg 即可（自动搜索 PATH、`imageio_ffmpeg` 及常见安装目录）。

> 节点界面与交互移植自 [WhatDreamsCost-ComfyUI](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI) 的 `LoadVideoUI` / `LoadAudioUI`，感谢原作者的优秀设计。移植时补全了输出（原节点仅输出所选段，本节点同时输出「所选段 + 整段」的画面/音频），解码后端改为 ffmpeg 子进程实现，并新增绝对路径支持与上传去重。

### VoiceRefDescription

> **使用教程：用本节点解决 MiniMax H3 多角色音色参考生视频时音频不准确的问题**
> 示例工作流：[`workflows/MiniMax-H3 Multi-Role Voice Reference Fixed - 720P-V1.json`](workflows/MiniMax-H3%20Multi-Role%20Voice%20Reference%20Fixed%20-%20720P-V1.json)
> - YouTube：<https://www.youtube.com/watch?v=Zj2tX9osIIA>
> - B站：<https://www.bilibili.com/video/BV1hEaU6TEQs>

面向 TTS / 声音克隆工作流：最多 5 路参考音频，每路配一行用途说明（默认「Audio 1:」「Audio 2:」…）。自动分析音色特征（音高区间、明暗、质感、语速、响度），说明文字与音色描述（统一输出英文）直接拼接为可直接投喂大模型的提示词。描述中嵌入具体数值（F0、低频能量占比、频谱倾斜度、谐波峰值比等），确保多条参考之间高区分度，例如：

```
Audio 1: A mid-high pitch register (F0 median 231 Hz), a bright, forward tone with
strong mid-highs but a solid chest foundation (15% low-freq energy, spectral tilt
-25 dB/dec), a natural, clean voice (flatness 0.020, harmonic PAR 20x), prominent
sibilance, vocal-tract resonances F1 348 Hz / F2 926 Hz; speaks with a relaxed pace
with frequent pauses, moderate volume.

Audio 2: A high pitch register (F0 median 312 Hz), a bright, crisp tone with forward,
penetrating mids (3% low-freq energy, spectral tilt -25 dB/dec), clean harmonics and a
clear, crisp voice (flatness 0.014, harmonic PAR 15x), vocal-tract resonances F1 441
Hz / F2 1017 Hz; speaks with a fast pace, short punchy phrases, loud and energetic
delivery.
```

描述不包含性别判断，仅基于客观声学特征（音高、共振、频谱、节奏等）。

- 未接入 / 为 None 的通路自动跳过
- 短于 0.3s 直接报错提示更换；超过 15s 在界面上弹窗告警
- 两种输出模式（`output_mode` 选项）：
  - **natural description**：节点内直接转换为自然语言音色描述（默认）
  - **DSP acoustic features**：跳过自然语言转换，仅输出原始 DSP 声学特征数值（F0 分位数、低频能量、频谱质心/倾斜/平坦度、谐波峰值比、共振峰 F1/F2/F3、语速、响度等），并在末尾附英文说明，要求 LLM 根据这些特征为每路音频生成自然语言音色描述（明确要求不识别、不推断说话人性别）
- 优先使用 **librosa**（YIN 基频 + LPC 共振峰 F1/F2/F3）；未安装 librosa 时自动回退到纯 numpy 实现（无共振峰特征），无需额外模型

DSP 模式输出示例：

```
Audio 1:
DSP acoustic features extracted from this reference audio (analysis backend: librosa):
- duration 13.8 s, voiced-frame ratio 0.71
- F0 pitch: median 221 Hz, p10 171 Hz, p90 296 Hz, range 9.5 semitones, jitter 0.036
- low-frequency energy below 250 Hz: 15.4% of total
- spectrum: centroid 920 Hz, tilt -25 dB/decade, flatness 0.0201, harmonic PAR 20x
- vocal-tract formants: F1 348 Hz, F2 926 Hz, F3 1805 Hz
- rhythm: 2.7 transitions/s, longest voiced run 1.78 s
- loudness: mean -30.1 dBFS

Convert the DSP acoustic features listed above into one concise natural-language
timbre description per labeled audio ... (do not state or infer the speaker's gender),
and use those descriptions in the downstream TTS / voice-cloning prompt.
```

### ResolutionSelectorShortSide

内置的 Resolution Selector 用「百万像素」描述分辨率，短剧/短视频场景下不如「最短边」直观。本节点改为：

```
画布比例（9:16 竖屏） + 最短边（1080） + 对齐（64） → 1080 × 1920
```

支持 12 种常见比例预设、5 档对齐倍数（64/32/16/8/1）与宽高交换。

## 安装

### 方式一：ComfyUI Manager（推荐）

在 Manager 的 `Install Custom Nodes` 中搜索 `comfyui-easy-ui` 安装，重启 ComfyUI。

### 方式二：手动克隆

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/hjc3321/comfyui-easy-ui.git
```

重启 ComfyUI 后，在节点列表搜索 `LoadVideoRange` / `LoadAudioRange` / `音色参考` 等即可。

## 依赖

- **ffmpeg**（仅 LoadVideoRange / LoadAudioRange 需要）：程序会依次尝试环境变量 `FFMPEG_PATH` → 系统 PATH → `imageio_ffmpeg` → 常见安装目录。音色分析等其它节点无 ffmpeg 也能用。
- **librosa**（VoiceRefDescription 使用，已在 `requirements.txt` 声明）：提供 YIN 基频跟踪与 LPC 共振峰分析，显著提升音色区分度。ComfyUI Manager 会自动安装；节点首次加载时若检测到缺失也会自动 pip 安装。安装失败则自动回退到纯 numpy 后端（无共振峰特征）。
- Python 包 `numpy` / `torch` / `Pillow`（ComfyUI 环境自带）。
- 支持多语言界面（内置中/英 `locales`），跟随 ComfyUI 语言设置自动切换。

## 附带的 HTTP 路由

| 路由 | 作用 |
|---|---|
| `GET /easyui/view?filename=...` | 节点内预览任意媒体绝对路径（ComfyUI 自带 `/view` 只服务 input/output/temp） |
| `POST /easyui/upload_chunk` | 大文件分片上传，绕开 413 Payload Too Large |
| `GET /easyui/check_file?filename=...&size=...` | 同名同大小文件去重查询，避免重复上传 |

所有路由均做了目录穿越防护与媒体后缀白名单校验。

## 目录结构

```
comfyui-easy-ui/
├── __init__.py               # 节点注册入口（自动安装缺失依赖）
├── requirements.txt          # pip 依赖（librosa）
├── video_audio_ui_node.py    # LoadVideoRange / LoadAudioRange
├── ffmpeg_utils.py           # ffmpeg/ffprobe 定位与执行
├── voice_ref_node.py         # VoiceRefDescription
├── voice_analysis.py         # 声学分析（VAD/F0/LTAS）
├── timbre_map.py             # 声学指标 → 音色描述文本
├── resolution_node.py        # ResolutionSelectorShortSide
├── image_node.py             # EasyLoadImage / EasyBatchImages
├── api_routes.py             # /easyui/* HTTP 路由
├── locales/                  # zh / en 多语言
├── workflows/                # 示例工作流（MiniMax H3 多角色音色参考）
└── web/js/                   # 前端交互（时间轴、裁剪框、动态端口等）
```

## 许可证

MIT License

## 致谢

- [WhatDreamsCost-ComfyUI](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI) — LoadVideoRange / LoadAudioRange 的节点界面与交互设计（原节点 `LoadVideoUI` / `LoadAudioUI`）
