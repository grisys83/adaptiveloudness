#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
loudness_fir.py
ISO-226(2003) 등가시청 곡선을 이용해
‘target phon → reference phon’ 보정 FIR 필터 생성.

예시:
    python loudness_fir.py --target 42.2 --reference 66.2 --taps 513 \
                           --fs 48000 --out FIR_42.2_to_66.2.wav
"""

import argparse, json, os, sys, textwrap
import numpy as np
from scipy import signal
from scipy.io import wavfile

# ---------------------------------------------------------------------------
#  ISO-226:2003  (20 Hz – 20 kHz, 31 포인트)  등가음압 레벨[sound-pressure level] (dB SPL)
#  출처: ISO 226 Table 1. (20 phon ≤ phon ≤ 100 phon, 10 단위) + 보간용 함수는 밑에
# ---------------------------------------------------------------------------
ISO_FREQ = np.array(
   [ 20,  25,  31.5,  40,  50,  63,  80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800,1000,1250,1600,
   2000,2500,3150,4000,5000,6300,8000,10000,12500,16000,20000], float)

ISO_CURVES = {
  20:  [74.3,64.4,56.3,49.5,44.7,40.6,37.5,35.0,33.1,31.6,30.2,28.9,27.7,26.6,25.6,
        24.7,23.8,22.5,21.2,20.3,19.1,18.1,17.2,16.3,15.0,13.4,11.5,10.4,10.1,11.2,13.4],
  30:  [86.3,75.3,66.2,58.4,52.7,48.0,44.4,41.3,39.2,37.3,35.7,34.2,32.9,31.7,30.6,
        29.5,28.4,27.1,25.8,24.7,23.3,22.1,21.0,19.9,18.2,16.1,14.6,13.6,13.3,14.6,17.1],
  40:  [96.9,85.4,76.3,68.3,62.1,57.0,52.5,48.7,46.2,44.0,42.1,40.4,38.9,37.5,36.3,
        35.1,33.9,32.6,31.2,29.9,28.4,27.1,25.9,24.7,22.9,20.7,19.0,17.8,17.3,18.6,21.4],
  50:  [107.6,95.6,86.4,78.3,71.1,65.0,60.1,56.1,53.4,51.0,48.9,47.1,45.4,43.8,42.3,
        40.9,39.4,38.1,36.6,35.1,33.4,32.0,30.6,29.2,27.4,25.1,23.4,22.1,21.6,22.8,25.8],
  60:  [118.6,106.1,96.8,88.4,81.3,75.0,69.2,65.1,62.2,59.6,57.3,55.3,53.5,51.7,50.1,
        48.6,47.0,45.6,44.0,42.3,40.5,38.9,37.3,35.6,33.7,31.3,29.6,28.3,27.9,29.1,32.3],
  70:  [129.5,116.9,107.1,98.3,91.2,84.7,78.5,74.2,71.1,68.2,65.7,63.5,61.5,59.6,57.9,
        56.2,54.5,53.0,51.3,49.5,47.6,45.8,44.1,42.3,40.1,37.7,35.9,34.6,34.3,35.4,38.7],
  80:  [139.9,127.3,117.5,108.6,101.4,94.8,88.4,83.9,80.7,77.6,74.9,72.6,70.4,68.3,66.4,
        64.6,62.8,61.1,59.3,57.4,55.3,53.4,51.4,49.5,47.2,44.8,43.0,41.7,41.2,42.2,45.6],
  90:  [150.2,137.5,127.7,118.7,111.4,104.8,98.4,93.8,90.4,87.1,84.2,81.7,79.4,77.1,75.1,
        73.3,71.4,69.6,67.6,65.6,63.5,61.5,59.5,57.4,55.1,52.7,50.8,49.4,48.8,49.8,53.2],
 100:  [160.4,147.6,137.8,128.8,121.4,114.8,108.3,103.7,100.3,96.9,93.9,91.4,88.9,86.6,84.5,
        82.5,80.5,78.6,76.6,74.5,72.4,70.3,68.3,66.2,63.9,61.4,59.5,58.1,57.5,58.5,62.0],
}

ISO_CURVES = {k: np.asarray(v, dtype=float) for k, v in ISO_CURVES.items()}

# ---------------------------------------------------------------------------
def interp_iso(curves, step=0.1):
    """0.1 phon 간격까지 선형 보간한 dict 반환."""
    fine = {}
    keys = sorted(curves)
    for p in np.arange(keys[0], keys[-1] + step, step):
        p = round(p, 1)
        if p in curves:
            fine[p] = np.asarray(curves[p], dtype=float)
            continue
        lo = max(k for k in keys if k <= p)
        hi = min(k for k in keys if k >= p)
        w = (p - lo) / (hi - lo)
        fine[p] = curves[lo] * (1 - w) + curves[hi] * w
    return fine

FINE_CURVES = interp_iso(ISO_CURVES, 0.1)

# ---------------------------------------------------------------------------
def iso_gain(target_phon, ref_phon):
    """주파수별 '증가시킬 dB'(=ref - target, 1 kHz anchor) 반환."""
    t = FINE_CURVES[round(target_phon, 1)]
    r = FINE_CURVES[round(ref_phon, 1)]
    delta = r - t
    delta -= delta[ISO_FREQ.tolist().index(1000)]          # 1 kHz → 0 dB
    return delta


def design_fir(target_phon, ref_phon,
               taps=513, fs=48000, window="hann"):
    """firwin2 로 선형-위상 FIR 설계, (coeff, meta) 반환."""
    if taps % 2 == 0:
        taps += 1                                          # 홀수 보정
    g_db = iso_gain(target_phon, ref_phon)
    g_lin = 10 ** (g_db / 20)

    nyq = fs / 2
    freq = np.r_[0, ISO_FREQ[ISO_FREQ < nyq], nyq]
    gain = np.r_[g_lin[0], g_lin[ISO_FREQ < nyq], g_lin[-1]]
    # 중복 주파수 제거
    freq, idx = np.unique(freq, return_index=True)
    gain = gain[idx]

    fir = signal.firwin2(taps, freq, gain, fs=fs, window=window)

    # 1 kHz 정규화 (수치 오차 보정)
    _, h = signal.freqz(fir, worN=[1000], fs=fs)
    fir /= np.abs(h[0])

    meta = {
        "target_phon": float(target_phon),
        "reference_phon": float(ref_phon),
        "taps": int(len(fir)),
        "fs": int(fs),
        "window": window,
    }
    return fir.astype(np.float32), meta


def save_impulse(coeffs, path, fs):
    """32-bit float WAV 로 저장."""
    wavfile.write(path, fs, coeffs)


# ---------------------------------------------------------------------------
def _cli():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
        단일 ISO 226 기반 FIR 필터 생성기
        -----------------------------------
        예) 42.2 phon → 66.2 phon, 513 tap @48 kHz
            python loudness_fir.py -t 42.2 -r 66.2 -n 513 -f 48000 -o FIR.wav
        """))
    p.add_argument("-t", "--target",    type=float, required=True, help="원본 loudness (phon)")
    p.add_argument("-r", "--reference", type=float, required=True, help="목표 loudness (phon)")
    p.add_argument("-n", "--taps",      type=int,   default=513,  help="FIR tap 수 (홀수)")
    p.add_argument("-f", "--fs",        type=int,   default=48000,help="샘플링 레이트 (Hz)")
    p.add_argument("-o", "--out",       type=str,   required=True, help="출력 WAV 경로")
    p.add_argument("-j", "--json",      type=str,   help="메타데이터 JSON 경로")
    args = p.parse_args()

    coeffs, meta = design_fir(args.target, args.reference,
                              args.taps, args.fs)
    save_impulse(coeffs, args.out, args.fs)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(meta, f, indent=2)
    print(f"✔ FIR 저장 완료 → {args.out}")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    _cli()