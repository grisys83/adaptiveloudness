#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bulk_fir_loudness.py
지정 범위(phon min~max, step) 필터를 일괄 생성하여
 .wav, .npy, index.json 으로 저장.
사용 예:
    python bulk_fir_loudness.py --t_min 40 --t_max 90 --t_step 0.5 \
                                --ref 80 --dir filters_40-90_to_80
"""

import argparse, json, itertools, os, time, numpy as np
from loudness_fir import design_fir, save_impulse

def bulk_generate(t_min, t_max, t_step,
                  ref_min, ref_max, ref_step,
                  taps, fs, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    t_vals  = np.round(np.arange(t_min,  t_max+1e-9,  t_step),  1)
    r_vals  = np.round(np.arange(ref_min, ref_max+1e-9, ref_step), 1)
    total   = len(t_vals) * len(r_vals)

    meta_all = []
    t0 = time.time()
    for i, (t, r) in enumerate(itertools.product(t_vals, r_vals), 1):
        coeffs, meta = design_fir(t, r, taps, fs)
        base = f"{t:.1f}-to-{r:.1f}"
        np.save(os.path.join(out_dir, base + ".npy"), coeffs)
        save_impulse(coeffs, os.path.join(out_dir, base + ".wav"), fs)
        meta["file"] = base
        meta_all.append(meta)

        if i % 100 == 0 or i == total:
            print(f"{i}/{total} ({i/total*100:.1f} %) 완료", end="\r")

    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump(meta_all, f, indent=2)
    print(f"\n총 {len(meta_all)} 개 필터 → {out_dir}  (경과 {time.time()-t0:.1f}s)")


def _cli():
    p = argparse.ArgumentParser()
    p.add_argument("--t_min",  type=float, required=True)
    p.add_argument("--t_max",  type=float, required=True)
    p.add_argument("--t_step", type=float, required=True)
    p.add_argument("--ref",    type=float, nargs="+", required=True,
                   help="reference phon (하나 또는 [min max step])")
    p.add_argument("--taps",   type=int,   default=1025)
    p.add_argument("--fs",     type=int,   default=48000)
    p.add_argument("--dir",    type=str,   required=True, help="출력 폴더")
    args = p.parse_args()

    if len(args.ref) == 1:
        ref_min = ref_max = args.ref[0]; ref_step = 1
    elif len(args.ref) == 3:
        ref_min, ref_max, ref_step = args.ref
    else:
        sys.exit("--ref 는 1개(고정) 또는 3개(min max step) 값을 줘야 합니다.")

    bulk_generate(args.t_min, args.t_max, args.t_step,
                  ref_min, ref_max, ref_step,
                  args.taps, args.fs, args.dir)

if __name__ == "__main__":
    _cli()
