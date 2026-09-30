"""前端交互所需的少量 HTTP 路由。

/easyui/view          从任意绝对路径读取媒体文件用于节点内预览
                      （ComfyUI 自带的 /view 只服务 input/output/temp 目录，
                       绝对路径的视频/音频预览不了；与原版 WhatDreamsCost-ComfyUI
                       的 /video_ui_custom_view 行为对齐——任意媒体绝对路径均可预览）
/easyui/upload_chunk  分片上传，绕开大文件 413 Payload Too Large
/easyui/check_file    按 filename + size 查询 input/easyui/ 下是否已有同名同
                      大小文件，避免重复上传（拖入已上传过的文件时秒完成）

所有路由都做了「禁止目录穿越」与「仅限媒体后缀」的校验。
"""
import os
import asyncio

from aiohttp import web

try:
    from server import PromptServer
except Exception:  # pragma: no cover - 非 ComfyUI 环境
    PromptServer = None

try:
    import folder_paths
except Exception:  # pragma: no cover
    folder_paths = None


MEDIA_EXTS = (
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg", ".ts",
    ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
)

_MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".mkv": "video/x-matroska", ".webm": "video/webm", ".avi": "video/x-msvideo",
    ".flv": "video/x-flv", ".wmv": "video/x-ms-wmv", ".ts": "video/mp2t",
    ".mpg": "video/mpeg", ".mpeg": "video/mpeg",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
    ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
    ".opus": "audio/opus", ".wma": "audio/x-ms-wma",
    ".aiff": "audio/aiff", ".aif": "audio/aiff",
}

MAX_UPLOAD_NAME = 240


def _is_media(path):
    return os.path.splitext(path)[1].lower() in MEDIA_EXTS


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _under_any(path, roots):
    p = _norm(path)
    for r in roots:
        if p == r or p.startswith(r + os.sep):
            return True
    return False


def register_routes():
    if PromptServer is None or not getattr(PromptServer, "instance", None):
        return False

    routes = PromptServer.instance.routes

    @routes.get("/easyui/view")
    async def easyui_view(request):
        raw = request.query.get("filename", "")
        if not raw:
            return web.Response(status=400, text="filename is required")

        try:
            path = os.path.abspath(raw) if os.path.isabs(raw) else ""
            if not path and folder_paths is not None:
                path = folder_paths.get_annotated_filepath(raw)
                path = os.path.abspath(path) if path else ""
        except Exception:
            path = ""

        if not path or not os.path.isfile(path):
            return web.Response(status=404, text="file not found")
        if not _is_media(path):
            return web.Response(status=403, text="only media files can be previewed")

        mime = _MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        resp = web.FileResponse(path)
        resp.headers["Content-Type"] = mime
        resp.headers["Accept-Ranges"] = "bytes"
        return resp

    @routes.post("/easyui/upload_chunk")
    async def easyui_upload_chunk(request):
        post = await request.post()
        part = post.get("file")
        filename = os.path.basename(str(post.get("filename") or ""))
        try:
            chunk_index = int(post.get("chunk_index"))
            total_chunks = int(post.get("total_chunks"))
        except (TypeError, ValueError):
            return web.json_response({"error": "bad chunk_index/total_chunks"}, status=400)

        if not part or not filename:
            return web.json_response({"error": "file/filename is required"}, status=400)
        if len(filename) > MAX_UPLOAD_NAME:
            filename = filename[-MAX_UPLOAD_NAME:]
        if not _is_media(filename):
            return web.json_response({"error": "unsupported media type"}, status=400)

        upload_dir = os.path.join(folder_paths.get_input_directory(), "easyui")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, filename)

        # 校验最终路径仍落在上传目录内，防目录穿越
        if not _under_any(file_path, [_norm(upload_dir)]):
            return web.json_response({"error": "invalid path"}, status=400)

        mode = "ab" if chunk_index > 0 else "wb"
        data = part.file.read()

        def _write():
            with open(file_path, mode) as f:
                f.write(data)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write)

        if chunk_index >= total_chunks - 1:
            return web.json_response({"name": filename, "subfolder": "easyui"})
        return web.json_response({"status": "ok"})

    @routes.get("/easyui/check_file")
    async def easyui_check_file(request):
        """按 filename + size 查询 input/easyui/ 下是否已有同名同大小文件。

        与前端 LoadVideoRange / LoadAudioRange 的上传去重逻辑配合：
        已存在 -> {"exists": true, "name", "subfolder", "size"}，前端直接复用；
        不存在 -> {"exists": false}，前端继续走正常上传。
        """
        filename = os.path.basename(str(request.query.get("filename") or ""))
        try:
            size = int(request.query.get("size") or -1)
        except (TypeError, ValueError):
            size = -1

        if not filename or folder_paths is None:
            return web.json_response({"exists": False})

        upload_dir = os.path.join(folder_paths.get_input_directory(), "easyui")
        path = os.path.join(upload_dir, filename)

        # 防目录穿越：最终路径必须仍在上传目录内
        if not _under_any(path, [_norm(upload_dir)]):
            return web.json_response({"exists": False})

        if os.path.isfile(path) and (size < 0 or os.path.getsize(path) == size):
            return web.json_response({
                "exists": True,
                "name": filename,
                "subfolder": "easyui",
                "size": os.path.getsize(path),
            })
        return web.json_response({"exists": False})

    return True
