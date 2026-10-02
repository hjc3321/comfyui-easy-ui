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


def _ensure_requirements():
    """自动安装 requirements.txt 中缺失的依赖（静默失败不影响节点加载）。"""
    import importlib.util
    import subprocess

    req_path = os.path.join(_DIR, "requirements.txt")
    if not os.path.exists(req_path):
        return
    # requirements 里的包名 -> 实际 import 名（仅列不一致的）
    _IMPORT_NAMES = {"librosa": "librosa"}
    missing = []
    with open(req_path, encoding="utf-8") as f:
        for line in f:
            spec = line.split("#", 1)[0].strip()
            if not spec:
                continue
            pkg = spec
            for sep in ("==", ">=", "<=", "~=", ">", "<", ";", "[", " "):
                pkg = pkg.split(sep, 1)[0]
            mod_name = _IMPORT_NAMES.get(pkg.lower(), pkg.replace("-", "_"))
            if importlib.util.find_spec(mod_name) is None:
                missing.append(spec)
    if not missing:
        return
    print(f"[comfyui-easy-ui] 检测到缺失依赖，正在安装：{', '.join(missing)}")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", *missing],
            check=True,
            capture_output=True,
            text=True,
        )
        print("[comfyui-easy-ui] 依赖安装完成")
    except Exception as e:
        print(
            f"[comfyui-easy-ui] 依赖自动安装失败（节点仍可加载，音色分析将回退到纯 numpy 后端）：{e}\n"
            f"  可手动执行：{sys.executable} -m pip install {' '.join(missing)}"
        )


_ensure_requirements()

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
