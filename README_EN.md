# ComfyUI Easy UI

English | [中文](README.md)

A collection of usability nodes that make ComfyUI workflows smoother: video/audio loaders with in-node range selection, a voice reference description node, an intuitive resolution selector, and placeholder image nodes that never error on missing inputs.

All UI and interactions integrate natively into ComfyUI: multilingual (EN/中文), interactive HTML embedded inside nodes (timeline, crop box), chunked upload for large files, and direct preview of local absolute paths on desktop.

## Nodes

| Node | Class | Description |
|---|---|---|
| Load Video (UI Range) | `LoadVideoRange` | Select a video range in the node UI (seconds/frames toggle) + crop + resize; outputs both the selected segment and the full video |
| Load Audio (UI Range) | `LoadAudioRange` | Select an audio range in the node UI; outputs both the selected segment and the full audio |
| Voice Reference Description | `VoiceRefDescription` | Analyzes timbre features of multiple reference audios (F0/brightness/texture/pace, etc.) and concatenates them with usage notes into prompt text |
| Resolution Selector · Short Side | `ResolutionSelectorShortSide` | Computes width/height from "aspect ratio + short-side pixels" — more intuitive than megapixels (e.g. just enter 768/1080 for vertical short videos) |
| Load Image (None placeholder) | `EasyLoadImage` | Enhanced Load Image: optional `[None]` placeholder outputs None without errors — handy for draft workflows |
| Batch Images (skip None) | `EasyBatchImages` | Enhanced Batch Images: dynamically extendable ports; None/empty inputs are skipped automatically (the built-in node errors out) |

## Key Features

### LoadVideoRange / LoadAudioRange

Pick your media directly on the node UI in the canvas — no more parameter ping-pong:

- **Range selection**: Time (seconds) / Frames display modes with one-click toggle; values stay in sync both ways
- **Video crop**: 8-handle crop box + 3×3 composition guides + 13 aspect-ratio constraints (16:9, 1:1, 4:5, ...) + manual width/height input
- **Timeline**: ruler + left/right handles + whole-range dragging; playback loops within the selected range for preview
- **Upload**: `choose file to upload` button + drag & drop; files ≥10MB are automatically chunked; files with the same name and size are deduplicated (instant upload)
- **Absolute paths**: when you drop local files from the desktop / a browser that provides `file.path`, uploading is skipped and the original file is decoded directly
- **Dual outputs**: a single decode yields both "selected segment" and "full segment" for downstream comparison processing
- **Fault tolerance**: empty inputs produce blank output (no crash); videos without an audio track become silent; missing audio files produce 1 second of silence

Video decoding uses an **ffmpeg subprocess** (rawvideo rgb24 / f32le PCM) — no dependency on `av` / `opencv`; any ffmpeg the system can find will do (PATH, `imageio_ffmpeg`, and common install directories are searched automatically).

> The node UI and interactions are ported from `LoadVideoUI` / `LoadAudioUI` in [WhatDreamsCost-ComfyUI](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI) — many thanks to the original author for the excellent design. The port completes the outputs (the original node only outputs the selected segment; this node outputs both "selected + full" video and audio), switches the decode backend to an ffmpeg subprocess, and adds absolute-path support and upload deduplication.

### VoiceRefDescription

Built for TTS / voice-clone workflows: up to 5 reference audios, each paired with a one-line usage note (defaults to "Audio 1:", "Audio 2:", ...). Timbre features (pitch register, brightness, texture, pace, loudness) are analyzed automatically, and the note is concatenated directly with the timbre description (always output in English) into a prompt ready to feed an LLM. Descriptions embed concrete numbers (F0, low-frequency energy %, spectral tilt, harmonic PAR, etc.) so that even similar-sounding references produce clearly distinct text:

```
Audio 1: male voice, a mid-high pitch register (F0 median 231 Hz), a bright, forward
tone with strong mid-highs but a solid chest foundation (15% low-freq energy, spectral
tilt -25 dB/dec), a natural, clean voice (flatness 0.020, harmonic PAR 20x), prominent
sibilance, vocal-tract resonances F1 348 Hz / F2 926 Hz; speaks with a relaxed pace with
frequent pauses, moderate volume.

Audio 2: female voice, a high pitch register (F0 median 312 Hz), a bright, crisp tone
with forward, penetrating mids (3% low-freq energy, spectral tilt -25 dB/dec), clean
harmonics and a clear, crisp voice (flatness 0.014, harmonic PAR 15x), vocal-tract
resonances F1 441 Hz / F2 1017 Hz; speaks with a fast pace, short punchy phrases,
loud and energetic delivery.
```

- Unconnected / None channels are skipped automatically
- Audio shorter than 0.3s raises an error asking for a replacement; longer than 15s triggers a UI warning
- Two output modes (`output_mode` option):
  - **natural description**: the node converts features into natural-language timbre text directly (default)
  - **DSP acoustic features**: skips the natural-language conversion and outputs only raw DSP metrics (F0 percentiles, low-frequency energy, spectral centroid/tilt/flatness, harmonic PAR, formants F1/F2/F3, rhythm, loudness), with a trailing instruction asking the LLM to turn them into a natural-language timbre description per audio
- Prefers **librosa** (YIN pitch tracking + LPC formants F1/F2/F3); automatically falls back to a pure-numpy implementation (no formant features) when librosa is unavailable — no extra models required

DSP-mode output example:

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
timbre description per labeled audio ..., and use those descriptions in the downstream
TTS / voice-cloning prompt.
```

### ResolutionSelectorShortSide

The built-in Resolution Selector describes resolution in "megapixels", which is less intuitive than "short side" for short-drama / short-video work. This node instead computes:

```
canvas ratio (9:16 vertical) + short side (1080) + alignment (64) → 1080 × 1920
```

It offers 12 common ratio presets, 5 alignment multiples (64/32/16/8/1), and a width/height swap.

## Installation

### Option 1: ComfyUI Manager (recommended)

Search for `comfyui-easy-ui` in Manager's `Install Custom Nodes`, then restart ComfyUI.

### Option 2: Manual clone

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/hjc3321/comfyui-easy-ui.git
```

After restarting ComfyUI, search the node list for `LoadVideoRange` / `LoadAudioRange` / `Voice Reference`, etc.

## Dependencies

- **ffmpeg** (only needed by LoadVideoRange / LoadAudioRange): the program tries, in order, the `FFMPEG_PATH` environment variable → system PATH → `imageio_ffmpeg` → common install directories. Other nodes (timbre analysis, etc.) work without ffmpeg.
- **librosa** (used by VoiceRefDescription, declared in `requirements.txt`): provides YIN pitch tracking and LPC formant analysis for much stronger timbre discrimination. ComfyUI Manager installs it automatically; the node also auto-pip-installs it on first load if missing. If installation fails, it silently falls back to the pure-numpy backend (no formant features).
- Python packages `numpy` / `torch` / `Pillow` (bundled with ComfyUI).
- Multilingual UI (built-in zh / en `locales`), switching automatically with ComfyUI's language setting.

## Bundled HTTP Routes

| Route | Purpose |
|---|---|
| `GET /easyui/view?filename=...` | Preview any media by absolute path inside nodes (ComfyUI's built-in `/view` only serves input/output/temp) |
| `POST /easyui/upload_chunk` | Chunked upload for large files, bypassing 413 Payload Too Large |
| `GET /easyui/check_file?filename=...&size=...` | Same-name same-size dedup query to avoid duplicate uploads |

All routes are guarded against directory traversal and validate media extensions against a whitelist.

## Directory Structure

```
comfyui-easy-ui/
├── __init__.py               # node registration entry (auto-installs missing deps)
├── requirements.txt          # pip dependencies (librosa)
├── video_audio_ui_node.py    # LoadVideoRange / LoadAudioRange
├── ffmpeg_utils.py           # ffmpeg/ffprobe locating & execution
├── voice_ref_node.py         # VoiceRefDescription
├── voice_analysis.py         # acoustic analysis (VAD/F0/LTAS)
├── timbre_map.py             # acoustic metrics -> timbre description text
├── resolution_node.py        # ResolutionSelectorShortSide
├── image_node.py             # EasyLoadImage / EasyBatchImages
├── api_routes.py             # /easyui/* HTTP routes
├── locales/                  # zh / en localization
└── web/js/                   # frontend interactions (timeline, crop box, dynamic ports, etc.)
```

## License

MIT License

## Acknowledgements

- [WhatDreamsCost-ComfyUI](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI) — node UI & interaction design for LoadVideoRange / LoadAudioRange (original nodes `LoadVideoUI` / `LoadAudioUI`)
