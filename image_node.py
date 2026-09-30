"""ComfyUI nodes: 增强版 Load Image 与 Batch Images.

EasyLoadImage:
  在下拉列表最前面加入 "None" 选项作为占位。选择 None 时输出 None（空图像），
  便于"暂时不接图"的草稿工作流，不会因缺图报错。

EasyBatchImages:
  合并多路 IMAGE，输入为 None / 空的自动跳过（内置 ImageBatch 会直接报错）。
  支持 2~5 路可选输入。
"""
import os
import numpy as np
import torch

import folder_paths
import node_helpers
import comfy.utils
import comfy.model_management

from PIL import Image, ImageOps, ImageSequence

NONE_OPTION = "[None] 不使用图片"
MIN_IMAGE_INPUTS = 2      # 起始至少 2 路，前端按连接情况自动扩展


def _list_input_images():
    input_dir = folder_paths.get_input_directory()
    files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
    try:
        files = folder_paths.filter_files_content_types(files, ["image"])
    except Exception:
        exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
        files = [f for f in files if f.lower().endswith(exts)]
    return sorted(files)


class EasyLoadImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ([NONE_OPTION] + _list_input_images(), {
                    "image_upload": True,
                    "tooltip": f"选择 input 目录中的图片；选 {NONE_OPTION} 时输出 None（占位）",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    OUTPUT_TOOLTIPS = ("图片张量；选择 None 时输出 None", "遮罩张量；选择 None 时输出 None")
    FUNCTION = "load_image"
    CATEGORY = "AIGC/图像"
    DESCRIPTION = ("Enhanced Load Image: supports selecting None as a placeholder and "
                   "outputs None instead of raising an error.")

    def load_image(self, image):
        if image is None or image == NONE_OPTION:
            return (None, None)

        image_path = folder_paths.get_annotated_filepath(image)
        if not os.path.isfile(image_path):
            raise ValueError(f"图片不存在：{image}")

        dtype = comfy.model_management.intermediate_dtype()
        device = comfy.model_management.intermediate_device()

        img = node_helpers.pillow(Image.open, image_path)
        output_images, output_masks = [], []
        w = h = None

        for i in ImageSequence.Iterator(img):
            i = node_helpers.pillow(ImageOps.exif_transpose, i)
            frame = i.convert("RGB")
            if len(output_images) == 0:
                w, h = frame.size[0], frame.size[1]
            if frame.size[0] != w or frame.size[1] != h:
                continue

            arr = np.array(frame).astype(np.float32) / 255.0
            arr = torch.from_numpy(arr)[None,]
            if "A" in i.getbands():
                mask = np.array(i.getchannel("A")).astype(np.float32) / 255.0
                mask = 1.0 - torch.from_numpy(mask)
            else:
                mask = torch.zeros((64, 64), dtype=torch.float32, device="cpu")
            output_images.append(arr.to(dtype=dtype))
            output_masks.append(mask.unsqueeze(0).to(dtype=dtype))

        if not output_images:
            raise ValueError(f"无法解码图片：{image}")

        return (torch.cat(output_images, dim=0).to(device=device, dtype=dtype),
                torch.cat(output_masks, dim=0).to(device=device, dtype=dtype))

    @classmethod
    def IS_CHANGED(cls, image):
        if image is None or image == NONE_OPTION:
            return NONE_OPTION
        path = folder_paths.get_annotated_filepath(image)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        return (image, mtime)

    @classmethod
    def VALIDATE_INPUTS(cls, image):
        if image is None or image == NONE_OPTION:
            return True
        if not folder_paths.exists_annotated_filepath(image):
            return f"input 目录中找不到图片：{image}"
        return True


class EasyBatchImages:
    """动态扩展输入：接一张图就多长出一个 image_N 端口（由前端 JS 实现）。

    后端用 **kwargs 接收任意数量的 image_N，便于前端自由增删端口。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_1": ("IMAGE", {"tooltip": "第 1 路图片；为 None 或空时自动跳过"}),
            },
            "optional": {
                "image_2": ("IMAGE", {"tooltip": "第 2 路图片；为 None 或空时自动跳过"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    OUTPUT_TOOLTIPS = ("合并后的图片批次",)
    FUNCTION = "batch"
    CATEGORY = "AIGC/图像"
    DESCRIPTION = ("Enhanced Batch Images: input ports expand dynamically, None/empty "
                   "inputs are skipped automatically.")

    def batch(self, image_1=None, unique_id=None, **kwargs):
        # 收集 image_1 + image_2..image_N（动态端口全部落在 kwargs）
        candidates = [image_1]
        indexed = []
        for key, val in kwargs.items():
            if key.startswith("image_") and key[6:].isdigit():
                indexed.append((int(key[6:]), val))
        indexed.sort(key=lambda kv: kv[0])
        candidates.extend(val for _, val in indexed)

        # 只保留有效张量：None / 空张量 / 非张量 全部跳过
        valid = [img for img in candidates
                 if torch.is_tensor(img) and img.numel() > 0 and img.shape[0] > 0]

        if not valid:
            raise ValueError("没有任何有效图片输入，请至少接入一路非空图片。")

        # 以第一路为尺寸基准，其余按需对齐通道与分辨率
        base = valid[0]
        merged = [base]
        for img in valid[1:]:
            cur = img
            if cur.shape[-1] != base.shape[-1]:
                if cur.shape[-1] < base.shape[-1]:
                    pad = (0, base.shape[-1] - cur.shape[-1])
                    cur = torch.nn.functional.pad(cur, pad, mode="constant", value=1.0)
                else:
                    cur = cur[..., :base.shape[-1]]
            if cur.shape[1:] != base.shape[1:]:
                cur = comfy.utils.common_upscale(
                    cur.movedim(-1, 1), base.shape[2], base.shape[1], "bilinear", "center"
                ).movedim(1, -1)
            merged.append(cur)

        return (torch.cat(merged, dim=0),)


NODE_CLASS_MAPPINGS = {
    "EasyLoadImage": EasyLoadImage,
    "EasyBatchImages": EasyBatchImages,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # 基础显示名（英文）。中文等其它语言由 locales/<lang>/main.json 覆盖。
    "EasyLoadImage": "Load Image (None Placeholder)",
    "EasyBatchImages": "Batch Images (Skip None)",
}
