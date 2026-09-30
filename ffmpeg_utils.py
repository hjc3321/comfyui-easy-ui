"""ffmpeg / ffprobe 定位与通用执行工具。

查找顺序：
1. 环境变量 EASYUI_FFMPEG / EASYUI_FFPROBE
2. 系统 PATH 中的 ffmpeg / ffprobe
3. ComfyUI 自带（imageio_ffmpeg 随包附带的 ffmpeg 二进制）
4. custom_nodes 内常见的 ffmpeg/bin 目录
"""
import os
import glob
import json
import shutil
import subprocess

_CACHE = {}


def _candidates(name):
    """返回（按优先级）候选可执行文件路径列表。"""
    out = []

    env_key = "EASYUI_" + name.upper()
    if os.environ.get(env_key):
        out.append(os.environ[env_key])

    p = shutil.which(name)
    if p:
        out.append(p)

    p = shutil.which(name + ".exe")
    if p:
        out.append(p)

    # ComfyUI 依赖里打包的 ffmpeg（node 用 ffmpeg 名，实际只提供 ffmpeg 可执行文件）
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            out.append(imageio_ffmpeg.get_ffmpeg_exe())
        except Exception:
            pass

    # 常见手装目录（ComfyUI 便携版 / aki 版）
    for root in _search_roots():
        out.extend(glob.glob(os.path.join(root, "ffmpeg", "bin", name + ".exe")))
        out.extend(glob.glob(os.path.join(root, "ffmpeg", "bin", name)))
        out.extend(glob.glob(os.path.join(root, "**", "ffmpeg", "bin", name + ".exe")))

    return out


def _search_roots():
    roots = []
    for key in ("COMFYUI_ROOT", "COMFYUI_BASE_PATH"):
        if os.environ.get(key):
            roots.append(os.environ[key])

    # 当前包所在 custom_nodes 的上级（即 ComfyUI 根目录）
    here = os.path.dirname(os.path.abspath(__file__))
    nodes_dir = os.path.dirname(here)
    roots.append(os.path.dirname(nodes_dir))

    # 常见盘符下的 ComfyUI 目录（失败也无所谓，glob 会返回空）
    for drive in ("C:", "D:", "E:", "F:", "G:"):
        roots.extend([
            f"{drive}/ComfyUI",
            f"{drive}/ComfyUI-aki-v1.3",
            f"{drive}/ComfyUI-aki-v2.1",
            f"{drive}/ComfyUI_windows_portable",
            f"{drive}/AIGC/ComfyUI-aki-v2.1/ComfyUI-aki-v2.1",
        ])

    seen, uniq = set(), []
    for r in roots:
        if r and r not in seen and os.path.isdir(r):
            seen.add(r)
            uniq.append(r)
    return uniq


def find_binary(name):
    """定位可执行文件，失败抛 FileNotFoundError。"""
    if name in _CACHE:
        return _CACHE[name]
    for cand in _candidates(name):
        if not cand:
            continue
        cand = os.path.normpath(cand)
        if os.path.isfile(cand):
            _CACHE[name] = cand
            return cand
        # PATH 里的裸命令名交给 shell 解析
        if shutil.which(cand):
            _CACHE[name] = cand
            return cand
    raise FileNotFoundError(
        f"未找到 {name}，请安装 ffmpeg 并加入 PATH，"
        f"或设置环境变量 EASYUI_{name.upper()} 指向可执行文件。"
    )


def ffmpeg_exe():
    return find_binary("ffmpeg")


def ffprobe_exe():
    """ffprobe 可能不存在（imageio_ffmpeg 只带 ffmpeg），返回 None 时调用方走 ffmpeg 兜底。"""
    try:
        return find_binary("ffprobe")
    except FileNotFoundError:
        return None


def run_ffmpeg(args, capture=False):
    """执行 ffmpeg，返回完成后的 CompletedProcess。"""
    exe = ffmpeg_exe()
    cmd = [exe, "-hide_banner", "-nostdin", "-loglevel", "error"] + list(args)
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE) if capture else {}
    proc = subprocess.run(cmd, check=False, **kwargs)
    if proc.returncode != 0:
        err = ""
        if capture and proc.stderr:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg 执行失败（code={proc.returncode}）：{err or ' '.join(cmd)}")
    return proc


def probe_json(path):
    """用 ffprobe 读取媒体信息；没有 ffprobe 时用 ffmpeg 估算。

    返回 dict: {"duration": float, "width": int, "height": int, "sample_rate": int,
                "channels": int, "has_video": bool, "has_audio": bool, "fps": float}
    """
    info = {
        "duration": 0.0, "width": 0, "height": 0, "sample_rate": 0,
        "channels": 0, "has_video": False, "has_audio": False, "fps": 0.0,
    }
    path = os.fspath(path)
    if not os.path.isfile(path):
        return info

    probe = ffprobe_exe()
    if probe:
        cmd = [probe, "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout.decode("utf-8", errors="replace") or "{}")
                fmt = data.get("format") or {}
                info["duration"] = float(fmt.get("duration") or 0.0)
                for st in data.get("streams") or []:
                    kind = st.get("codec_type")
                    if kind == "video" and not info["has_video"]:
                        info["has_video"] = True
                        info["width"] = int(st.get("width") or 0)
                        info["height"] = int(st.get("height") or 0)
                        info["fps"] = _parse_fps(st.get("avg_frame_rate") or st.get("r_frame_rate"))
                        if not info["duration"]:
                            info["duration"] = float(st.get("duration") or 0.0)
                    elif kind == "audio" and not info["has_audio"]:
                        info["has_audio"] = True
                        info["sample_rate"] = int(st.get("sample_rate") or 0)
                        info["channels"] = int(st.get("channels") or 0)
                        if not info["duration"]:
                            info["duration"] = float(st.get("duration") or 0.0)
                return info
        except Exception:
            pass

    # 无 ffprobe：依赖 ffmpeg 在 stderr 输出的 Duration 行
    try:
        exe = ffmpeg_exe()
        proc = subprocess.run([exe, "-hide_banner", "-i", path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        text = (proc.stderr or b"").decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("Duration:"):
                info["duration"] = _parse_ffmpeg_duration(line)
            elif "Video:" in line and not info["has_video"]:
                info["has_video"] = True
                info["width"], info["height"] = _parse_ffmpeg_resolution(line)
                info["fps"] = _parse_ffmpeg_fps(line)
            elif "Audio:" in line and not info["has_audio"]:
                info["has_audio"] = True
                info["sample_rate"], info["channels"] = _parse_ffmpeg_audio(line)
    except Exception:
        pass
    return info


def _parse_fps(raw):
    if not raw or raw == "0/0":
        return 0.0
    try:
        if "/" in raw:
            num, den = raw.split("/")
            den = float(den)
            return float(num) / den if den else 0.0
        return float(raw)
    except Exception:
        return 0.0


def _parse_ffmpeg_duration(line):
    try:
        part = line.split("Duration:")[1].split(",")[0].strip()
        h, m, s = part.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return 0.0


def _parse_ffmpeg_resolution(line):
    try:
        import re
        m = re.search(r"(\d{2,5})x(\d{2,5})", line)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 0, 0


def _parse_ffmpeg_fps(line):
    try:
        import re
        m = re.search(r"([\d.]+)\s*fps", line)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return 0.0


def _parse_ffmpeg_audio(line):
    try:
        import re
        sr = 0
        ch = 0
        m = re.search(r"(\d+)\s*Hz", line)
        if m:
            sr = int(m.group(1))
        m = re.search(r"(mono|stereo)", line, re.I)
        if m:
            ch = 1 if m.group(1).lower() == "mono" else 2
        return sr, ch
    except Exception:
        return 0, 0
