"""ComfyUI node: 音色参考描述 (Voice Reference Description) - multi audio.

支持 5 路音频输入：每接一路 audio，就对应填一行说明文本框。
未连接 / 为 None / 过短的音频自动跳过。
超过 15s 的音频会在 ComfyUI 界面上弹出告警（不写入输出文本）。
输出 = 所有已接音频的 [说明文字] + [音色特征描述]，按行拼接。
"""
import numpy as np

try:
    from .voice_analysis import analyze_waveform
    from .timbre_map import describe_timbre, format_dsp_features, DSP_CONVERSION_HINT
except ImportError:  # direct file execution fallback
    from voice_analysis import analyze_waveform
    from timbre_map import describe_timbre, format_dsp_features, DSP_CONVERSION_HINT

MAX_AUDIO = 5      # 支持 5 路参考音频（改大即可适配支持更多 audio 的模型）
MIN_AUDIO = 1      # 至少显示一路，可自动增长到 MAX_AUDIO
MIN_DURATION = 0.3  # 短于此时长直接报错
MAX_DURATION = 15.0  # 超过则界面告警（不写入输出文本）

MODE_NATURAL = "natural description"   # 节点内直接转自然语言音色描述
MODE_DSP = "DSP acoustic features"     # 仅输出 DSP 声学特征，交给 LLM 转换
OUTPUT_MODES = [MODE_NATURAL, MODE_DSP]


def _to_mono(x):
    """torch tensor / numpy (B, C, N) 或 (C, N) 或 (N,) -> mono float32 1D."""
    if x is None:
        return None
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    x = np.asarray(x)
    if x.size == 0:
        return None
    if x.ndim == 3:        # (B, C, N)
        x = x[0]
    if x.ndim == 2:        # (C, N)
        x = x.mean(axis=0) if x.shape[0] > 1 else x[0]
    return x.astype(np.float32).ravel()


class VoiceRefDescription:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "output_mode": (OUTPUT_MODES, {
                    "default": MODE_NATURAL,
                    "tooltip": (
                        "natural description：节点直接输出自然语言音色描述（不识别性别）；"
                        "DSP acoustic features：仅输出原始 DSP 声学特征数值，"
                        "并附说明让 LLM 自行转换为自然语言音色描述（同样不识别、不推断性别）。"
                    ),
                }),
                "audio_1": ("AUDIO", {"tooltip": "第 1 路参考音频（接 LoadAudio）"}),
                "text_1": ("STRING", {
                    "default": "Audio 1:",
                    "multiline": False,
                    "tooltip": "第 1 路音频的用途说明",
                }),
            },
            "optional": {},
            "hidden": {"unique_id": "UNIQUE_ID"},
        }
        for i in range(2, MAX_AUDIO + 1):
            inputs["optional"][f"audio_{i}"] = ("AUDIO", {"tooltip": f"第 {i} 路参考音频（不接则跳过）"})
            inputs["optional"][f"text_{i}"] = ("STRING", {
                "default": f"Audio {i}:",
                "multiline": False,
                "tooltip": f"第 {i} 路音频的用途说明",
            })
        return inputs

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("voice_prompt",)
    OUTPUT_TOOLTIPS = ("用途说明 + 音色描述（自然语言或 DSP 声学特征，由 output_mode 决定）",)
    FUNCTION = "run"
    CATEGORY = "AIGC/音色"
    OUTPUT_NODE = False
    DESCRIPTION = ("Analyze timbre features of multiple reference audios and merge them "
                   "with their usage notes into prompt text.")

    def _notify(self, unique_id, messages):
        """发送界面弹窗告警（仅 UI，不影响返回值）。"""
        if not messages:
            return
        try:
            from server import PromptServer
            PromptServer.instance.send_sync("voiceref.alert", {
                "node_id": unique_id,
                "title": "音色参考音频告警",
                "message": "\n".join(messages),
            })
        except Exception:
            # 非 ComfyUI 环境（如命令行自测）时退回打印
            for msg in messages:
                print(f"[VoiceRefDescription] {msg}")

    def run(self, output_mode=MODE_NATURAL,
            audio_1=None, text_1="", audio_2=None, text_2="", audio_3=None, text_3="",
            audio_4=None, text_4="", audio_5=None, text_5="", unique_id=None):
        audio_map = {
            1: (audio_1, text_1), 2: (audio_2, text_2), 3: (audio_3, text_3),
            4: (audio_4, text_4), 5: (audio_5, text_5),
        }

        parts, alerts = [], []
        for idx in range(1, MAX_AUDIO + 1):
            audio, text = audio_map.get(idx, (None, ""))

            # 未接入 / 结构不完整 -> 静默跳过
            if audio is None or not isinstance(audio, dict):
                continue
            waveform = audio.get("waveform")
            sr = int(audio.get("sample_rate") or 0)
            if waveform is None or sr <= 0:
                continue

            x = _to_mono(waveform)
            if x is None or len(x) == 0:
                continue  # 空波形 -> 视为未接入
            if len(x) < int(MIN_DURATION * sr):
                raise ValueError(
                    f"第 {idx} 路音频时长仅 {len(x) / sr:.2f}s，短于 {MIN_DURATION}s 最低要求，"
                    f"无法分析音色，请更换更长的参考音频。"
                )

            m = analyze_waveform(x, sr)
            purpose = (text or "").strip()

            if output_mode == MODE_DSP:
                # 仅输出原始 DSP 声学特征，不做自然语言转换
                block = f"{purpose}\n{format_dsp_features(m)}" if purpose \
                        else format_dsp_features(m)
            else:
                desc = describe_timbre(m)
                block = f"{purpose}{desc}" if purpose else desc
            parts.append(block)

            if m["duration"] > MAX_DURATION:
                alerts.append(
                    f"第 {idx} 路音频时长 {m['duration']:.1f}s 超过 {MAX_DURATION:.0f}s 上限，"
                    f"建议剪辑到 8~12s 的干声最佳段。"
                )

        self._notify(unique_id, alerts)

        if not parts:
            raise ValueError("没有任何可用的音频输入，请至少接入一路不小于 0.3s 的 LoadAudio。")

        if output_mode == MODE_DSP:
            result = "\n\n".join(parts) + f"\n\n{DSP_CONVERSION_HINT}"
        else:
            result = "\n".join(parts)
        return (result,)


NODE_CLASS_MAPPINGS = {
    "VoiceRefDescription": VoiceRefDescription,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # 基础显示名（英文）。中文等其它语言由 locales/<lang>/main.json 覆盖。
    "VoiceRefDescription": "Voice Reference Description",
}
