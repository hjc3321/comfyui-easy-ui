"""ComfyUI nodes: LoadVideoRange / LoadAudioRange（带界面区间选择的视频/音频加载器）。

从 WhatDreamsCost-ComfyUI 的 LoadVideoUI / LoadAudioUI 移植，
节点界面与交互与原版保持一致；移植时补全了输出（原节点仅输出所选段，
本节点同时输出「所选段 + 整段」）；解码改用 ffmpeg 子进程（不依赖 av / cv2）。

LoadVideoRange (Load Video UI)
  界面上选择加载视频的范围（秒 / 帧可切换），支持画面裁剪与缩放。
  输出 9 路：images / audio（选择的视频段）
           full_images / full_audio（整个视频段）
           duration / frame_count / full_frame_count / start_frame / end_frame

LoadAudioRange (Load Audio UI)
  界面上选择音频段。
  输出 4 路：audio（选择的音频段）
           full_audio（整个音频段，新增）
           duration / full_duration
"""
import os
import tempfile

import numpy as np
import torch

import folder_paths

try:
    from .ffmpeg_utils import probe_json, run_ffmpeg
except ImportError:  # 直接以文件方式执行时
    from ffmpeg_utils import probe_json, run_ffmpeg


NODE_CATEGORY = "AIGC/音视频"

RESIZE_METHODS = ["maintain aspect ratio", "stretch to fit", "pad", "crop"]

# 单次解码的帧数安全上限（防止误接长视频把内存吃光）
FRAME_SAFETY_LIMIT = 6000


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def notify(unique_id, title, messages):
    """向 ComfyUI 前端推送界面告警（不影响返回值）。"""
    messages = [m for m in (messages or []) if m]
    if not messages:
        return
    try:
        from server import PromptServer
        PromptServer.instance.send_sync("easyui.alert", {
            "node_id": unique_id,
            "title": title,
            "message": "\n".join(messages),
        })
    except Exception:
        for m in messages:
            print(f"[{title}] {m}")


def _tmp(suffix):
    fd, path = tempfile.mkstemp(prefix="easyui_", suffix=suffix)
    os.close(fd)
    return path


def _safe_unlink(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def _resolve_media_path(value):
    """把节点上的字符串值解析成磁盘绝对路径（绝对路径 / input 相对路径均支持）。"""
    if not value:
        return ""
    value = os.fspath(value)
    if os.path.isabs(value) and os.path.isfile(value):
        return value
    try:
        p = folder_paths.get_annotated_filepath(value)
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    try:
        p = os.path.join(folder_paths.get_input_directory(), value)
        if os.path.isfile(p):
            return p
    except Exception:
        pass
    return ""


def _empty_image():
    return torch.zeros((1, 512, 512, 3), dtype=torch.float32)


def _empty_audio(sr=44100, channels=1):
    return {"waveform": torch.zeros((1, channels, sr), dtype=torch.float32),
            "sample_rate": sr}


# --------------------------------------------------------------------------- #
# 解码（ffmpeg）
# --------------------------------------------------------------------------- #
def decode_video_frames(path, fps, w=None, h=None, limit=FRAME_SAFETY_LIMIT):
    """整段解码为 [N,H,W,C] float32 0~1 的 tensor（按 fps 重采样）。

    返回 (tensor, width, height)。w/h 已知时可传入避免重复探测。
    """
    if w is None or h is None:
        info = probe_json(path)
        w = int(info.get("width") or 0)
        h = int(info.get("height") or 0)
    if w <= 0 or h <= 0:
        raise ValueError(f"无法读取视频分辨率：{path}")

    raw = _tmp(".rgb")
    # 注意：输出格式选项必须在 -i 之后、输出文件之前
    args = ["-i", path, "-an", "-sn"]
    if fps and fps > 0:
        args += ["-vf", f"fps={fps}"]
    args += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-y", raw]

    try:
        run_ffmpeg(args, capture=True)
        size = os.path.getsize(raw) if os.path.exists(raw) else 0
        frame_bytes = w * h * 3
        n = size // frame_bytes if frame_bytes else 0
        if n <= 0:
            return _empty_image(), w, h
        if n > limit:
            raise ValueError(
                f"视频按 {fps or 24}fps 解码后约 {n} 帧，超过安全上限 {limit} 帧。"
                f"请先剪辑视频，或把 frame_rate 调小。"
            )
        buf = np.fromfile(raw, dtype=np.uint8, count=n * frame_bytes)
        frames = buf.reshape(n, h, w, 3)
        return torch.from_numpy(frames.astype(np.float32) / 255.0), w, h
    finally:
        _safe_unlink(raw)


def decode_audio(path, sample_rate=None, channels=None):
    """整段解码为 AUDIO dict（waveform 形状 [1, C, N]）。

    sample_rate / channels 为 None 时保持文件原生参数（探测得到）。
    """
    if sample_rate is None or channels is None:
        info = probe_json(path)
        if sample_rate is None:
            sample_rate = int(info.get("sample_rate") or 0) or 44100
        if channels is None:
            channels = int(info.get("channels") or 0) or 2
    sample_rate = int(sample_rate)
    channels = max(1, int(channels))

    raw = _tmp(".f32")
    args = ["-i", path, "-vn", "-sn",
            "-f", "f32le", "-ac", str(channels), "-ar", str(sample_rate), "-y", raw]
    try:
        run_ffmpeg(args, capture=True)
        if not os.path.exists(raw):
            return _empty_audio(sample_rate, channels)
        data = np.fromfile(raw, dtype=np.float32)
        if data.size == 0:
            return _empty_audio(sample_rate, channels)
        usable = (data.size // channels) * channels
        wave = data[:usable].reshape(-1, channels).T  # (C, N)
        return {
            "waveform": torch.from_numpy(wave.copy()).unsqueeze(0),
            "sample_rate": sample_rate,
        }
    finally:
        _safe_unlink(raw)


# --------------------------------------------------------------------------- #
# 裁剪与缩放（与原版 LoadVideoUI 的几何逻辑一致）
# --------------------------------------------------------------------------- #
def _interp_nhwxc(tensor, out_h, out_w):
    """[N,H,W,C] -> 按双线性插值到 (out_h, out_w)。"""
    x = tensor.movedim(-1, 1)  # (N,C,H,W)
    y = torch.nn.functional.interpolate(x, size=(int(out_h), int(out_w)),
                                        mode="bilinear", align_corners=False)
    return y.movedim(1, -1).contiguous()


def apply_crop_and_resize(frames, orig_w, orig_h,
                           crop_x, crop_y, crop_w, crop_h,
                           custom_width, custom_height, resize_method):
    """先按归一化坐标手动裁剪，再按 resize_method 缩放到目标尺寸。

    与原版 LoadVideoUI 的 crop / resize 数学完全一致。
    """
    if not torch.is_tensor(frames) or frames.numel() == 0:
        return frames

    # ---- 手动裁剪（归一化 -> 像素）----
    left = int(orig_w * crop_x)
    top = int(orig_h * crop_y)
    right = orig_w - int(orig_w * (crop_x + crop_w))
    bottom = orig_h - int(orig_h * (crop_y + crop_h))

    left = max(0, min(left, orig_w - 1))
    top = max(0, min(top, orig_h - 1))
    right = max(0, min(right, orig_w - left - 1))
    bottom = max(0, min(bottom, orig_h - top - 1))

    if left > 0 or top > 0 or right > 0 or bottom > 0:
        frames = frames[:, top:orig_h - bottom, left:orig_w - right, :]

    cropped_w = orig_w - left - right
    cropped_h = orig_h - top - bottom
    if cropped_w <= 0 or cropped_h <= 0:
        return frames

    # ---- 缩放 ----
    if custom_width <= 0 and custom_height <= 0:
        return frames

    target_w = int(custom_width) if custom_width > 0 else cropped_w
    target_h = int(custom_height) if custom_height > 0 else cropped_h
    target_w -= target_w % 2
    target_h -= target_h % 2
    if target_w <= 0 or target_h <= 0:
        return frames

    if resize_method == "stretch to fit":
        return _interp_nhwxc(frames, target_h, target_w)

    if resize_method == "maintain aspect ratio":
        ratio = min(target_w / cropped_w, target_h / cropped_h)
        scale_w = int(cropped_w * ratio)
        scale_h = int(cropped_h * ratio)
        scale_w -= scale_w % 2
        scale_h -= scale_h % 2
        return _interp_nhwxc(frames, scale_h, scale_w)

    if resize_method == "pad":
        ratio = min(target_w / cropped_w, target_h / cropped_h)
        scale_w = int(cropped_w * ratio)
        scale_h = int(cropped_h * ratio)
        scale_w -= scale_w % 2
        scale_h -= scale_h % 2
        scaled = _interp_nhwxc(frames, scale_h, scale_w)
        pad_x = target_w - scale_w
        pad_y = target_h - scale_h
        pad_left = pad_x // 2
        pad_top = pad_y // 2
        x = scaled.movedim(-1, 1)
        x = torch.nn.functional.pad(
            x, (pad_left, pad_x - pad_left, pad_top, pad_y - pad_top), value=0.0)
        return x.movedim(1, -1).contiguous()

    if resize_method == "crop":
        ratio = max(target_w / cropped_w, target_h / cropped_h)
        scale_w = int(cropped_w * ratio)
        scale_h = int(cropped_h * ratio)
        scale_w -= scale_w % 2
        scale_h -= scale_h % 2
        scaled = _interp_nhwxc(frames, scale_h, scale_w)
        crop_x_px = scale_w - target_w
        crop_y_px = scale_h - target_h
        crop_left = crop_x_px // 2
        crop_top = crop_y_px // 2
        return scaled[:, crop_top:crop_top + target_h,
                      crop_left:crop_left + target_w, :]

    return frames


# --------------------------------------------------------------------------- #
# LoadVideoRange
# --------------------------------------------------------------------------- #
class LoadVideoRange:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("STRING", {"default": ""}),
                "start_time": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01}),
                "end_time": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01}),
                "duration": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01}),
                "start_frame": ("INT", {"default": 0, "min": 0, "max": 10000000, "step": 1}),
                "end_frame": ("INT", {"default": 0, "min": 0, "max": 10000000, "step": 1}),
                "duration_frames": ("INT", {"default": 0, "min": 0, "max": 10000000, "step": 1}),
                "resize_method": (RESIZE_METHODS, {"default": "maintain aspect ratio"}),
                "custom_width": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 8,
                                         "tooltip": "Custom width. 0 means original width."}),
                "custom_height": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 8,
                                          "tooltip": "Custom height. 0 means original height."}),
                "frame_rate": ("INT", {"default": 24, "min": 1, "max": 120, "step": 1,
                                       "tooltip": "Force the video to a specific frame rate for extraction."}),
                "display_mode": (["seconds", "frames"], {"default": "seconds"}),
                "crop_x": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.001}),
                "crop_y": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.001}),
                "crop_w": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.001}),
                "crop_h": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.001}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "FLOAT", "INT", "IMAGE", "AUDIO", "INT", "INT", "INT")
    RETURN_NAMES = ("images", "audio", "duration", "frame_count",
                    "full_images", "full_audio", "full_frame_count", "start_frame", "end_frame")
    OUTPUT_TOOLTIPS = (
        "选择的视频段画面",
        "选择的视频段音频（无音轨时为静音）",
        "所选片段时长（秒）",
        "所选片段帧数",
        "整个视频段画面（未裁剪区间）",
        "整个视频段音频（未裁剪区间）",
        "整段帧数",
        "所选区间起始帧",
        "所选区间结束帧",
    )
    FUNCTION = "load_video"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = ("Load a video with an on-node range selector (seconds or frames), "
                   "interactive crop and resize. Outputs both the selected segment and "
                   "the full segment (images + audio).")

    def load_video(self, video, frame_rate, display_mode, start_time, end_time, duration,
                   start_frame, end_frame, duration_frames, custom_width=0, custom_height=0,
                   resize_method="maintain aspect ratio", crop_x=0.0, crop_y=0.0,
                   crop_w=1.0, crop_h=1.0, unique_id=None, **kwargs):
        alerts = []

        # ---- 未选择视频：输出空白（与原版一致）----
        if not video:
            empty_image = _empty_image()
            empty_audio = _empty_audio(44100, 1)
            return (empty_image, empty_audio, 0.0, 0, empty_image, empty_audio, 0, 0, 0)

        # ---- 路径解析（绝对路径 / input 相对路径）----
        video_path = _resolve_media_path(video)
        if not video_path:
            raise FileNotFoundError(f"Video file not found: {video}")

        info = probe_json(video_path)
        video_duration = float(info.get("duration") or 0.0)
        orig_w = int(info.get("width") or 0)
        orig_h = int(info.get("height") or 0)
        if orig_w <= 0 or orig_h <= 0:
            raise ValueError(f"无法读取视频分辨率：{video_path}")
        if video_duration <= 0:
            alerts.append("无法读取视频时长，区间终点将按整段处理。")

        fr = float(frame_rate) if frame_rate and frame_rate > 0 else 24.0

        # ---- 选择区间（与原版一致：duration 仅供 UI 联动，不参与计算）----
        if display_mode == "frames":
            trim_start_time = float(start_frame) / fr
            if end_frame > 0 and end_frame > start_frame:
                trim_end_time = float(end_frame) / fr
            else:
                trim_end_time = video_duration if video_duration > 0 else float("inf")
        else:
            trim_start_time = float(start_time or 0.0)
            if end_time > 0 and end_time > start_time:
                trim_end_time = float(end_time)
            else:
                trim_end_time = video_duration if video_duration > 0 else float("inf")

        # ---- 解码整段（画面）----
        full_frames, w, h = decode_video_frames(video_path, fr, orig_w, orig_h)
        n_full = int(full_frames.shape[0])
        if n_full == 0:
            alerts.append("未能解出任何帧，已输出空白画面。")
            full_frames = _empty_image()

        # ---- 手动裁剪 + 缩放（作用于整段，与原版一致）----
        full_frames = apply_crop_and_resize(
            full_frames, orig_w, orig_h,
            float(crop_x or 0.0), float(crop_y or 0.0),
            float(crop_w if crop_w and crop_w > 0 else 1.0),
            float(crop_h if crop_h and crop_h > 0 else 1.0),
            int(custom_width or 0), int(custom_height or 0), resize_method)
        n_full = int(full_frames.shape[0])

        # ---- 解码整段（音频）----
        try:
            full_audio = decode_audio(video_path)
        except Exception as ex:
            alerts.append(f"音轨解码失败，已用静音代替：{ex}")
            full_audio = _empty_audio(44100, 1)

        # ---- 画面切片 ----
        if n_full > 0:
            start_idx = max(0, min(int(trim_start_time * fr), n_full - 1))
            end_idx = int(trim_end_time * fr) if trim_end_time != float("inf") else n_full
            end_idx = max(start_idx + 1, min(end_idx, n_full))
            trimmed_frames = full_frames[start_idx:end_idx]
            if trimmed_frames.shape[0] == 0:
                trimmed_frames = full_frames[:1].clone()
        else:
            trimmed_frames = full_frames

        # ---- 音频切片 ----
        sr = int(full_audio.get("sample_rate") or 44100)
        wave = full_audio.get("waveform")
        if torch.is_tensor(wave) and wave.shape[2] > 0:
            a0 = min(int(trim_start_time * sr), wave.shape[2])
            a1 = int(trim_end_time * sr) if trim_end_time != float("inf") else wave.shape[2]
            a1 = min(max(a0, a1), wave.shape[2])
            trimmed_wave = wave[:, :, a0:a1]
            if trimmed_wave.shape[2] == 0:
                trimmed_wave = wave[:, :, :1].clone()
            trimmed_audio = {"waveform": trimmed_wave, "sample_rate": sr}
        else:
            trimmed_audio = full_audio

        # ---- 输出 ----
        n_sel = int(trimmed_frames.shape[0])
        if trim_end_time != float("inf"):
            final_duration = float(max(0.0, trim_end_time - trim_start_time))
        else:
            final_duration = n_sel / fr if fr else 0.0

        output_start_frame = int(trim_start_time * fr)
        output_end_frame = (int(trim_end_time * fr)
                            if trim_end_time != float("inf") else n_full)

        notify(unique_id, "LoadVideoRange 告警", alerts)
        print(f"[LoadVideoRange] {os.path.basename(video_path)} | 整段 {n_full} 帧 / "
              f"所选 {n_sel} 帧 | {trim_start_time:.2f}s~"
              f"{('∞' if trim_end_time == float('inf') else f'{trim_end_time:.2f}')}s "
              f"@ {fr:.2f}fps")

        return (trimmed_frames, trimmed_audio, final_duration, n_sel,
                full_frames, full_audio, n_full, output_start_frame, output_end_frame)

    @classmethod
    def IS_CHANGED(cls, video, **kwargs):
        path = _resolve_media_path(video)
        if not path:
            return str(video)
        try:
            st = os.stat(path)
            return (video, st.st_mtime, st.st_size, kwargs.get("start_time"),
                    kwargs.get("end_time"), kwargs.get("start_frame"),
                    kwargs.get("end_frame"), kwargs.get("frame_rate"))
        except OSError:
            return str(video)


# --------------------------------------------------------------------------- #
# LoadAudioRange
# --------------------------------------------------------------------------- #
class LoadAudioRange:
    @classmethod
    def INPUT_TYPES(cls):
        # 与原版 LoadAudioUI 一致：优先 ComfyUI 的 audio 列表，
        # 失败则扫描 input 目录中的音频/视频文件
        try:
            files = folder_paths.get_filename_list("audio")
        except Exception:
            files = []

        if not files:
            try:
                input_dir = folder_paths.get_input_directory()
            except Exception:
                input_dir = ""
            if input_dir and os.path.exists(input_dir):
                all_files = [f for f in os.listdir(input_dir)
                             if os.path.isfile(os.path.join(input_dir, f))]
                try:
                    files = sorted(folder_paths.filter_files_content_types(
                        all_files, ["audio", "video"]))
                except Exception:
                    files = sorted(all_files)

        if not files or len(files) == 0:
            files = ["none"]

        return {
            "required": {
                "audio": (files, {"audio_upload": True}),
                "start_time": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01}),
                "end_time": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01}),
                "duration": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01}),
            },
            "optional": {
                "audioUI": ("AUDIO_UI",),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("AUDIO", "AUDIO", "FLOAT", "FLOAT")
    RETURN_NAMES = ("audio", "full_audio", "duration", "full_duration")
    OUTPUT_TOOLTIPS = (
        "选择的音频段",
        "整个音频段（未裁剪）",
        "所选片段时长（秒）",
        "整段时长（秒）",
    )
    FUNCTION = "load_audio"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = ("Load an audio file with an on-node range selector. Outputs both the "
                   "selected segment and the full segment.")

    @classmethod
    def VALIDATE_INPUTS(cls, audio, **kwargs):
        # 允许下拉列表中不存在的历史值（如上传后的子目录路径），交由运行时判断
        return True

    def load_audio(self, audio, start_time, end_time, duration, unique_id=None, **kwargs):
        # 路径解析与视频节点一致：绝对路径（桌面拖入）/ input 相对路径均可
        audio_path = _resolve_media_path(audio) if audio != "none" else ""

        # ---- 文件缺失 / 选择 none：输出 1 秒静音（与原版一致）----
        if audio == "none" or not audio_path or not os.path.exists(audio_path):
            missing_info = audio if audio != "none" else "None selected"
            print(f"!!! [LoadAudioRange] Warning: Audio file '{missing_info}' not found. "
                  f"Outputting 1 second of silence.")
            sample_rate = 44100
            full_audio = {"waveform": torch.zeros((1, 2, 44100)), "sample_rate": sample_rate}
        else:
            try:
                full_audio = decode_audio(audio_path)
                sample_rate = int(full_audio["sample_rate"])
            except Exception as ex:
                print(f"!!! [LoadAudioRange] Error decoding {audio}: {ex}. Falling back to silence.")
                sample_rate = 44100
                full_audio = {"waveform": torch.zeros((1, 2, 44100)), "sample_rate": sample_rate}

        wave = full_audio["waveform"]
        n_full = int(wave.shape[2])
        full_duration = n_full / sample_rate if sample_rate else 0.0

        # ---- 区间切片（duration 仅供 UI 联动，不参与计算）----
        start_sample = int(float(start_time or 0.0) * sample_rate)
        if end_time > 0:
            end_sample = int(float(end_time) * sample_rate)
            end_sample = min(end_sample, n_full)
        else:
            end_sample = n_full
        start_sample = min(start_sample, end_sample)

        trimmed_wave = wave[:, :, start_sample:end_sample]
        if trimmed_wave.shape[2] == 0:
            trimmed_wave = torch.zeros((1, wave.shape[1], 1))

        sel_duration = float(trimmed_wave.shape[2] / sample_rate) if sample_rate else 0.0
        trimmed_audio = {"waveform": trimmed_wave, "sample_rate": sample_rate}

        print(f"[LoadAudioRange] {audio} | 整段 {n_full} 采样点 ({full_duration:.2f}s) / "
              f"所选 {int(trimmed_wave.shape[2])} 采样点 ({sel_duration:.2f}s) @ {sample_rate}Hz")

        return (trimmed_audio, full_audio, sel_duration, full_duration)

    @classmethod
    def IS_CHANGED(cls, audio, **kwargs):
        if audio == "none":
            return "none"
        path = _resolve_media_path(audio)
        if not path or not os.path.isfile(path):
            return str(audio)
        try:
            st = os.stat(path)
            return (audio, st.st_mtime, st.st_size,
                    kwargs.get("start_time"), kwargs.get("end_time"))
        except OSError:
            return str(audio)


NODE_CLASS_MAPPINGS = {
    "LoadVideoRange": LoadVideoRange,
    "LoadAudioRange": LoadAudioRange,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # 基础显示名（英文）。中文等其它语言由 locales/<lang>/main.json 覆盖。
    "LoadVideoRange": "Load Video Range",
    "LoadAudioRange": "Load Audio Range",
}
