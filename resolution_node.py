"""ComfyUI node: 分辨率选择器 (Resolution Selector by Short Side).

相比内置的 Resolution Selector（宽高比 + 百万像素 + 对齐），
本节点用"最短边像素"作为主输入，更直观：短视频竖屏 768/1080 一眼就懂。

输入：画布比例 + 最短边像素 + 对齐倍数
输出：width, height
"""
import math

# 常见画布比例：(宽, 高, 显示名)
ASPECT_PRESETS = [
    ("9:16 竖屏 (1080x1920)", 9, 16),
    ("16:9 横屏 (1920x1080)", 16, 9),
    ("3:4 竖屏", 3, 4),
    ("4:3 横屏", 4, 3),
    ("1:1 方形", 1, 1),
    ("2:3 竖屏", 2, 3),
    ("3:2 横屏", 3, 2),
    ("21:9 宽银幕", 21, 9),
    ("9:21 超长竖屏", 9, 21),
    ("4:5 竖屏 (小红书)", 4, 5),
    ("5:4 横屏", 5, 4),
    ("2:1 宽幅", 2, 1),
]
ASPECT_CHOICES = [name for name, _, _ in ASPECT_PRESETS]
ASPECT_LOOKUP = {name: (w, h) for name, w, h in ASPECT_PRESETS}

ALIGN_CHOICES = ["64", "32", "16", "8", "1"]


def _align(v, align):
    return max(align, int(round(v / align)) * align)


def calc_resolution(aspect, short_side, align=64, swap=False):
    """最短边对齐到 align 倍数，再按比例算出长边，最后长边也按 align 取证。"""
    aw, ah = ASPECT_LOOKUP.get(aspect, (9, 16))

    # 判断哪一边是"短边"
    if aw <= ah:  # 竖屏或方形（w<=h）
        w = _align(short_side, align)
        h = _align(w * ah / aw, align)
    else:         # 横屏（w>h）
        h = _align(short_side, align)
        w = _align(h * aw / ah, align)

    if swap:
        w, h = h, w
    return int(w), int(h)


class ResolutionSelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (ASPECT_CHOICES, {
                    "default": "9:16 竖屏 (1080x1920)",
                    "tooltip": "画布比例",
                }),
                "short_side": ("INT", {
                    "default": 768, "min": 64, "max": 8192, "step": 64,
                    "tooltip": "最短边的像素值（更直观：768/1080 等）",
                }),
                "align": (ALIGN_CHOICES, {
                    "default": "64",
                    "tooltip": "宽高对齐倍数（缺省 64，可改 32/16/8）",
                }),
                "swap": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "交换宽高（把竖屏输出成横屏等）",
                }),
            },
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    OUTPUT_TOOLTIPS = ("计算出的宽度", "计算出的高度")
    FUNCTION = "run"
    CATEGORY = "AIGC/图像"
    DESCRIPTION = ("Compute width/height from canvas aspect ratio + short side + "
                   "alignment, more intuitive than megapixels.")

    def run(self, aspect_ratio, short_side, align="64", swap=False):
        w, h = calc_resolution(aspect_ratio, short_side, int(align), swap)
        return (w, h)


NODE_CLASS_MAPPINGS = {
    "ResolutionSelectorShortSide": ResolutionSelector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # 基础显示名（英文）。中文等其它语言由 locales/<lang>/main.json 覆盖。
    "ResolutionSelectorShortSide": "Resolution by Short Side",
}
