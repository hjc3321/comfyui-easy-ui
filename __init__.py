"""comfyui-easy-ui: ComfyUI 易用性节点合集.

1. VoiceRefDescription          音色参考描述：多路音频 -> 音色特征 + 用途说明拼接的 STRING
2. ResolutionSelectorShortSide  分辨率选择器·最短边：比例 + 最短边 + 对齐 -> 宽高
3. EasyLoadImage                Load Image（支持 None 占位，选中时输出 None）
4. EasyBatchImages              Batch Images（None/空输入自动跳过，端口动态扩展）
5. LoadVideoRange               Load Video UI：界面选区（秒/帧 + 裁剪 + 缩放），
                                输出「所选视频段」+「整个视频段」的画面和音频
6. LoadAudioRange               Load Audio UI：界面选区，
                                输出「所选音频段」+「整个音频段」

5/6 的节点界面移植自 WhatDreamsCost-ComfyUI 的 LoadVideoUI /
LoadAudioUI（Time/Frames 切换、Crop 裁剪框、时间轴、上传与拖拽），
并补全了输出（同时输出「所选段 + 整段」），
解码改用 ffmpeg 子进程（不依赖 av / cv2）。

注意：包目录名含连字符（comfyui-easy-ui），Python 不支持对这类包名做相对导入
（from .xxx import 会报 ModuleNotFoundError），因此统一改用绝对模块名导入。
"""
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from voice_ref_node import (  # noqa: E402
    NODE_CLASS_MAPPINGS as _VOICE_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _VOICE_NAMES,
)
from resolution_node import (  # noqa: E402
    NODE_CLASS_MAPPINGS as _RES_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _RES_NAMES,
)
from image_node import (  # noqa: E402
    NODE_CLASS_MAPPINGS as _IMG_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _IMG_NAMES,
)
from video_audio_ui_node import (  # noqa: E402
    NODE_CLASS_MAPPINGS as _AV_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _AV_NAMES,
)

NODE_CLASS_MAPPINGS = {**_VOICE_CLASSES, **_RES_CLASSES, **_IMG_CLASSES, **_AV_CLASSES}
NODE_DISPLAY_NAME_MAPPINGS = {**_VOICE_NAMES, **_RES_NAMES, **_IMG_NAMES, **_AV_NAMES}

WEB_DIRECTORY = "./web/js"

# 注册 /easyui/view 与 /easyui/upload_chunk（失败不影响节点本身）
try:
    from api_routes import register_routes
    register_routes()
except Exception as _e:  # pragma: no cover
    print(f"[comfyui-easy-ui] API 路由注册失败（节点仍可用）：{_e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
