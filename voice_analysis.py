"""Voice timbre analysis core for ComfyUI nodes.

Self-contained copy of the workspace voice_analysis.py, with the entry
point analyze_waveform(x, sr) so nodes can consume LoadAudio's waveform
tensor directly (no ffmpeg decode needed).
"""
import os, tempfile, subprocess, numpy as np

SR = 24000


def _load(path, sr=SR):
    """Decode any ffmpeg-readable audio file to mono float32 (file mode)."""
    base = os.path.splitext(os.path.basename(path))[0]
    pcm = os.path.join(tempfile.gettempdir(), f"voice_analysis_{base}_{os.getpid()}.pcm")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path,
                    "-f", "f32le", "-ac", "1", "-ar", str(sr), pcm], check=True)
    try:
        x = np.fromfile(pcm, dtype=np.float32)
    finally:
        try:
            os.remove(pcm)
        except OSError:
            pass
    return x, sr


def analyze(path, sr=SR):
    x, sr = _load(path, sr)
    return analyze_waveform(x, sr, path=path)


def analyze_waveform(x, sr, path=""):
    """Core analysis on a mono float32 waveform (peak-normalized inside)."""
    x = x / (np.max(np.abs(x)) + 1e-9)
    dur = len(x) / sr

    # --- energy VAD: 25ms frame / 10ms hop ---
    fl, hop = int(0.025 * sr), int(0.010 * sr)
    n = (len(x) - fl) // hop
    frames = np.lib.stride_tricks.sliding_window_view(x, fl)[::hop][:n]
    rms = np.sqrt((frames ** 2).mean(axis=1))
    mask = rms > max(rms.max() * 0.06, rms.mean() * 0.35)
    vf = frames[mask]

    db = 20 * np.log10(rms[rms > 1e-6] + 1e-9)

    # --- F0 via autocorrelation per voiced frame (60-400 Hz) ---
    f0s = []
    lo, hi = int(sr / 400), int(sr / 60)
    for fr in vf:
        fr = fr - fr.mean()
        if (fr ** 2).sum() < 1e-8:
            continue
        ac = np.correlate(fr, fr, mode="full")[fl - 1:]
        if ac[0] <= 0:
            continue
        ac /= ac[0]
        seg = ac[lo:hi]
        if len(seg) < 2:
            continue
        pk = np.argmax(seg) + lo
        if ac[pk] > 0.45:
            f0s.append(sr / pk)
    f0s = np.array(f0s)

    # --- spectral features on voiced frames ---
    freqs = np.fft.rfftfreq(4096, 1 / sr)
    win = np.hanning(fl)
    LTS = np.zeros(len(freqs))
    cent, roll85, flat = [], [], []
    for fr in vf:
        fr = fr - fr.mean()
        S = np.abs(np.fft.rfft(fr * win, n=4096))
        P = S ** 2 + 1e-12
        cent.append((freqs * P).sum() / P.sum())
        cum = np.cumsum(P) / P.sum()
        roll85.append(freqs[np.searchsorted(cum, 0.85)])
        flat.append(np.exp(np.log(P + 1e-12).mean()) / (P.mean() + 1e-12))
        LTS += P
    LTS /= max(len(vf), 1)
    cent = np.array(cent); roll85 = np.array(roll85); flat = np.array(flat)
    tot = LTS.sum()
    bands = {}
    for name, lo_b, hi_b in [("low", 80, 250), ("lowmid", 250, 500), ("mid", 500, 1500),
                             ("highmid", 1500, 3000), ("sib", 3000, 6000), ("airy", 6000, 12000)]:
        m = (freqs >= lo_b) & (freqs < hi_b)
        bands[name] = 100 * LTS[m].sum() / tot

    # --- rhythm ---
    d = mask.astype(int)
    transitions = int(np.abs(np.diff(d)).sum())
    runs, cur = [], 0
    for v in d:
        if v:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    longest = max(runs) * hop / sr if runs else 0.0

    jitter = float(np.mean(np.abs(np.diff(f0s)) / f0s[:-1])) if len(f0s) > 5 else float("nan")

    return {
        "path": path, "duration": dur, "active_ratio": float(mask.mean()),
        "level_dbfs": float(db.mean()) if len(db) else float("nan"),
        "level_range": (float(db.min()), float(db.max())) if len(db) else (float("nan"), float("nan")),
        "f0_mean": float(f0s.mean()) if len(f0s) else float("nan"),
        "f0_median": float(np.median(f0s)) if len(f0s) else float("nan"),
        "f0_p10": float(np.percentile(f0s, 10)) if len(f0s) else float("nan"),
        "f0_p90": float(np.percentile(f0s, 90)) if len(f0s) else float("nan"),
        "f0_std": float(f0s.std()) if len(f0s) else float("nan"),
        "f0_span_st": float(12 * np.log2(np.percentile(f0s, 90) / np.percentile(f0s, 10))) if len(f0s) else float("nan"),
        "centroid_median": float(np.median(cent)) if len(cent) else float("nan"),
        "rolloff85_median": float(np.median(roll85)) if len(roll85) else float("nan"),
        "flatness": float(flat.mean()) if len(flat) else float("nan"),
        "bands": bands,
        "jitter": jitter, "transitions": transitions, "longest_voiced": float(longest),
        "tps": transitions / dur,
    }
