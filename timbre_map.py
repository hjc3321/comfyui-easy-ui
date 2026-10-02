"""Timbre metrics -> natural-language description mapping (H3 style).

All description text is output in English.  Designed to produce highly
discriminative, numerically-grounded descriptions for TTS voice cloning.
"""


# ---------------------------------------------------------------- helpers

def _nan(v):
    return v != v


def map_gender(m):
    """F0 median + low-energy share -> voice classification."""
    f0 = m["f0_median"]
    low = m["low_energy"]
    if _nan(f0):
        return "voice gender unknown"
    # male: lower F0 and/or strong low-frequency chest resonance
    if f0 < 145 or low > 12:
        return "male voice"
    if f0 < 175:
        conf = "leaning male voice" if f0 < 160 else "male or low-register female voice (ambiguous)"
        return f"{conf} (F0 median {f0:.0f} Hz, in the male/female overlap zone)"
    return "female voice"


def map_register(m):
    """Pitch register with F0 number embedded."""
    f0 = m["f0_median"]
    if _nan(f0):
        return "pitch register unknown"
    if f0 < 165:
        reg = "a deep, low-to-mid pitch register"
    elif f0 < 220:
        reg = "a mid-low pitch register"
    elif f0 < 260:
        reg = "a mid-high pitch register"
    else:
        reg = "a high pitch register"
    return f"{reg} (F0 median {f0:.0f} Hz)"


def map_brightness(m):
    """Brightness with low-frequency energy % and spectral tilt."""
    ro = m["rolloff85_median"]
    low = m["low_energy"]
    tilt = m.get("spectral_tilt")
    tilt_str = f", spectral tilt {tilt:.0f} dB/dec" if tilt and not _nan(tilt) else ""
    if ro < 450 or low > 40:
        return f"a dark, warm, rounded tone with soft, enveloping lows ({low:.0f}% low-freq energy{tilt_str})"
    if ro < 900:
        return f"a balanced, natural tone ({low:.0f}% low-freq energy{tilt_str})"
    if low > 8:
        return (f"a bright, forward tone with strong mid-highs but a solid chest foundation "
                f"({low:.0f}% low-freq energy{tilt_str})")
    return f"a bright, crisp tone with forward, penetrating mids ({low:.0f}% low-freq energy{tilt_str})"


def map_texture(m):
    """Flatness + sibilance + harmonic PAR -> texture with numbers."""
    desc = []
    f = m["flatness"]
    par = m.get("harmonic_par", 0)
    if f < 0.02:
        desc.append(f"clean harmonics and a clear, crisp voice (flatness {f:.3f}, harmonic PAR {par:.0f}x)")
    elif f < 0.05:
        desc.append(f"a natural, clean voice (flatness {f:.3f}, harmonic PAR {par:.0f}x)")
    else:
        desc.append(f"a noticeably breathy texture (flatness {f:.3f}, harmonic PAR {par:.0f}x)")
    sib = m["bands"]["sib"]
    if sib < 1.5:
        desc.append("minimal sibilance, soft and non-harsh")
    elif sib > 3:
        desc.append("prominent sibilance")
    return ", ".join(desc)


def map_pace(m):
    """Transitions/sec + longest voiced run -> tempo description."""
    if m["tps"] > 5.0 or m["longest_voiced"] < 0.9:
        return "a fast pace, short punchy phrases and a jumpy rhythm"
    if m["tps"] < 4.2 and m["longest_voiced"] > 1.0:
        return "a relaxed pace with frequent pauses, a storytelling narration feel"
    return "a steady pace and natural rhythm"


def map_loudness(m):
    lv = m["level_dbfs"]
    if _nan(lv):
        return "unknown loudness"
    if lv > -28:
        return "loud and energetic delivery"
    if lv < -31:
        return "soft-spoken, gentle delivery"
    return "moderate volume"


def map_prosody(m):
    sp = m["f0_span_st"]
    if _nan(sp):
        return "unknown intonation"
    if sp > 13:
        return "wide, expressive intonation swings"
    if sp < 8:
        return "flat, restrained intonation"
    return "natural intonation"


def map_formants(m):
    """Vocal-tract resonances (F1/F2) — strong timbre discriminator.

    Longer vocal tract (typically male) -> lower formants.
    """
    f1, f2 = m.get("formant_f1"), m.get("formant_f2")
    if not f1 or _nan(f1) or not f2 or _nan(f2):
        return ""
    return f"vocal-tract resonances F1 {f1:.0f} Hz / F2 {f2:.0f} Hz"


# ---------------------------------------------------------------- main

def describe_timbre(m):
    """Full timbre description sentence from metrics dict.

    Designed to be maximally discriminative: every sentence embeds
    concrete numeric values so that two similar-sounding references
    still produce clearly different text.
    """
    # gender + register line
    g = map_gender(m)
    r = map_register(m)

    # body / resonance line (low-frequency weight is the strongest
    # discriminator between chesty male and focused female voices)
    b = map_brightness(m)

    # texture line
    t = map_texture(m)

    # formants (available with librosa backend)
    fmt = map_formants(m)

    # rhythm / delivery line
    p = map_pace(m)
    l = map_loudness(m)
    pr = map_prosody(m)

    parts = [g, r, b, t]
    if fmt:
        parts.append(fmt)
    return ", ".join(parts) + f"; speaks with {p}, {l}, {pr}."


def duration_warning(m):
    if m["duration"] > 15:
        return (f"[!] Note: reference audio is {m['duration']:.1f}s long, exceeding the 15s limit; "
                f"please trim it to an 8-12s dry-sound segment first.\n")
    return ""


# --------------------------------------------------------- DSP raw features

def _v(v, fmt="{:.0f}"):
    """Format a numeric metric; NaN/None -> N/A."""
    if v is None:
        return "N/A"
    try:
        if v != v:  # NaN
            return "N/A"
    except TypeError:
        return "N/A"
    return fmt.format(v)


def format_dsp_features(m):
    """Raw DSP acoustic features as structured English text (no interpretation).

    The caller is expected to append an instruction asking the LLM to turn
    these numbers into a natural-language timbre description.
    """
    backend = m.get("backend", "numpy")
    lines = ["DSP acoustic features extracted from this reference audio "
             f"(analysis backend: {backend}):"]
    lines.append(f"- duration {_v(m.get('duration'), '{:.1f}')} s, "
                 f"voiced-frame ratio {_v(m.get('active_ratio'), '{:.2f}')}")
    lines.append(
        f"- F0 pitch: median {_v(m.get('f0_median'))} Hz, "
        f"p10 {_v(m.get('f0_p10'))} Hz, p90 {_v(m.get('f0_p90'))} Hz, "
        f"range {_v(m.get('f0_span_st'), '{:.1f}')} semitones, "
        f"frame-to-frame jitter {_v(m.get('jitter'), '{:.3f}')}"
    )
    lines.append(
        f"- low-frequency energy below 250 Hz: {_v(m.get('low_energy'), '{:.1f}')}% of total"
    )
    lines.append(
        f"- spectrum: centroid median {_v(m.get('centroid_median'))} Hz, "
        f"85% rolloff {_v(m.get('rolloff85_median'))} Hz, "
        f"spectral tilt {_v(m.get('spectral_tilt'), '{:.0f}')} dB/decade, "
        f"spectral flatness {_v(m.get('flatness'), '{:.4f}')}, "
        f"harmonic peak-to-average ratio {_v(m.get('harmonic_par'), '{:.0f}')}x"
    )
    f1, f2, f3 = m.get("formant_f1"), m.get("formant_f2"), m.get("formant_f3")
    if not (f1 is None or _nan(f1)):
        lines.append(
            f"- vocal-tract formants: F1 {_v(f1)} Hz, F2 {_v(f2)} Hz, F3 {_v(f3)} Hz"
        )
    else:
        lines.append("- vocal-tract formants: N/A (pure-numpy backend; install librosa)")
    lines.append(
        f"- rhythm: {_v(m.get('tps'), '{:.1f}')} voiced/unvoiced transitions per second, "
        f"longest continuous voiced run {_v(m.get('longest_voiced'), '{:.2f}')} s"
    )
    lines.append(f"- loudness: mean {_v(m.get('level_dbfs'), '{:.1f}')} dBFS")
    return "\n".join(lines)


DSP_CONVERSION_HINT = (
    "Convert the DSP acoustic features listed above into one concise natural-language "
    "timbre description per labeled audio (gender, pitch register, brightness, texture, "
    "resonance, pace, loudness and intonation), and use those descriptions in the "
    "downstream TTS / voice-cloning prompt."
)