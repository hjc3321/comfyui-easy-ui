"""Timbre metrics -> natural-language description mapping (H3 style)."""


def map_gender(m):
    """F0 median -> adult male/female voice classification."""
    f0 = m["f0_median"]
    if f0 != f0:  # NaN
        return "性别音区未知"
    if f0 < 145:
        return "男声"
    if f0 < 175:
        conf = "偏男声" if f0 < 160 else "男声或低音区女声（模糊区）"
        return f"{conf}（F0 中位 {f0:.0f} Hz 处于男女重叠区）"
    return "女声"


def map_register(f0_med):
    """F0 median -> pitch register description (female-oriented thresholds)."""
    if f0_med != f0_med:  # NaN
        return "音高未知"
    if f0_med < 165:
        return "音高偏低沉的中低音区"
    if f0_med < 220:
        return "中低音区"
    if f0_med < 260:
        return "中高音区"
    return "高音区（音高明显偏高）"


def map_brightness(m):
    """Rolloff + band share -> bright/dark description."""
    ro = m["rolloff85_median"]
    low = m["bands"]["low"]
    if ro < 450 or low > 40:
        return "音色暗暖圆润、低频柔和有包裹感"
    if ro < 900:
        return "音色均衡自然"
    return "音色明亮清脆、中频前突穿透力强"


def map_texture(m):
    """Flatness + sibilance share -> voice texture."""
    desc = []
    f = m["flatness"]
    if f < 0.02:
        desc.append("谐波干净、声线清亮利落")
    elif f < 0.05:
        desc.append("声线自然干净")
    else:
        desc.append("带明显气声质感")
    if m["bands"]["sib"] < 1.5:
        desc.append("齿音极少、柔和不刺耳")
    elif m["bands"]["sib"] > 3:
        desc.append("齿音偏明显")
    return "、".join(desc)


def map_pace(m):
    """Transitions/sec + longest voiced run -> tempo description."""
    if m["tps"] > 5.0 or m["longest_voiced"] < 0.9:
        return "语速快、句子短促有力、节奏跳跃"
    if m["tps"] < 4.2 and m["longest_voiced"] > 1.0:
        return "语速舒缓、停顿多、娓娓道来的叙述感"
    return "语速平稳、节奏自然"


def map_loudness(m):
    lv = m["level_dbfs"]
    if lv != lv:
        return "音量未知"
    if lv > -28:
        return "说话响亮有能量"
    if lv < -31:
        return "轻声细语、音量轻柔"
    return "音量适中"


def map_prosody(m):
    sp = m["f0_span_st"]
    if sp != sp:
        return "语调未知"
    if sp > 13:
        return "语调抑扬起伏大、表现力强"
    if sp < 8:
        return "语调平缓克制"
    return "语调起伏自然"


def describe_timbre(m):
    """Full timbre description sentence from metrics dict."""
    return (
        f"{map_gender(m)}，{map_register(m['f0_median'])}，{map_brightness(m)}，"
        f"{map_texture(m)}，说话{map_pace(m)}、{map_loudness(m)}，{map_prosody(m)}。"
    )


def duration_warning(m):
    if m["duration"] > 15:
        return (f"[!] 注意：参考音频时长 {m['duration']:.1f}s 超过 H3 的 15s 上限，"
                f"请先剪辑到 8~12s 的干声最佳段。\n")
    return ""
