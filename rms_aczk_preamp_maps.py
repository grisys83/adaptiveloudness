#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_preamp_map.py
────────────────────────────────────────────────────────
• ISO-226 'target→reference' 보정 FIR 설계를 위한 프리앰프 값 대량 계산
• 지정된 범위의 모든 (target, reference) 조합에 대해 계산 수행
• FIR로 인한 RMS SPL 변화를 A/C/Z/K-weighting으로 계산하고 평균 사용
• 출력: C++ std::map 형식의 조회 테이블 (지정된 파일로 저장)

필요 패키지: numpy, scipy  (pip install numpy scipy)
"""

import numpy as np
import argparse
import time
import sys
from scipy import signal
from datetime import datetime

# ── “loudness_fir.py” 가 같은 폴더(또는 PYTHONPATH)에 있다고 가정 ──
try:
    from loudness_fir import design_fir
except ImportError:
    print("오류: 'loudness_fir.py' 파일을 찾을 수 없습니다.")
    print("이 스크립트와 같은 디렉토리에 있거나 PYTHONPATH에 포함되어 있는지 확인하세요.")
    sys.exit(1)

# ==========  기본 설정값 (명령줄 인수로 덮어쓸 수 있음)  ======================
TP_HEADROOM_DBTP = -1.0           # 진폭 여유 (dBTP)
# ==============================================================================

# ----------  K-Weighting (ITU-R BS.1770)  ----------------------------------------------
def get_k_weighting_gains_linear(freqs_hz, fs):
    """BS.1770-4 K-weighting FIR 구현 (소프트 1차 HP @ 60 Hz + 슈퍼트위터 EQ)"""
    # 아날로그 zpk → 디지털 변환
    z = np.array([-np.inf, -np.inf]) # 두 개의 DC zero (s=0 이므로 log(0)=-inf)
    p1 = 2 * np.pi * 38.135199 # Pre-filter
    p2 = 2 * np.pi * 1550.0   # High-shelf
    p_analog = -0.5 * (p1**2 + p2**2) + np.array([1, -1]) * 0.5 * np.sqrt((p1**2 + p2**2)**2 - 4 * (p1 * p2)**2 + 0j)

    z_d = np.exp(z / fs)
    p_d = np.exp(p_analog / fs)
    b, a = signal.zpk2tf(z_d, p_d, 1.0)
    
    # 정규화 및 주파수 응답 계산 (scipy 1.12+ 호환)
    w_norm, h_norm = signal.freqz(b, a, worN=[1000], fs=fs)
    b /= np.abs(h_norm[0])
    
    w, h = signal.freqz(b, a, worN=freqs_hz, fs=fs)
    return np.abs(h)

# --------------------------------------------------------------------------------------

def get_weighting_gains_linear(freqs_hz, fs, curve='A'):
    """A, C, Z, K 중 하나의 선형 응답 반환"""
    if curve == 'Z':
        return np.ones_like(freqs_hz)
    if curve == 'K':
        return get_k_weighting_gains_linear(freqs_hz, fs)
    
    # A/C 가중치 zpk 정의 (IEC 61672)
    f1, f2, f3, f4 = 20.598997, 107.65265, 737.86223, 12194.217
    A1000 = 1.9997
    C1000 = 1.0062
    
    p_a = [-2*np.pi*f1, -2*np.pi*f1, -2*np.pi*f4, -2*np.pi*f4]
    z_a = [0, 0, 0, 0]
    k_a = (2*np.pi*f4)**2 * 10**(A1000/20)

    p_c = [-2*np.pi*f1, -2*np.pi*f1]
    z_c = [0, 0]
    k_c = 10**(C1000/20)

    if curve == 'A':
        p_a.extend([-2*np.pi*f2, -2*np.pi*f3])
        z, p, k = z_a, p_a, k_a
    elif curve == 'C':
        z, p, k = z_c, p_c, k_c
    else: # Z-weighting
        return np.ones_like(freqs_hz)

    z_d, p_d, k_d = signal.bilinear_zpk(z, p, k, fs)
    b, a = signal.zpk2tf(z_d, p_d, k_d)

    _, h = signal.freqz(b, a, worN=freqs_hz, fs=fs)
    return np.abs(h)

# ----------  RMS SPL 변화 계산  ---------------------------------------------------------
def rms_spl_change(fir_coeffs, fs, freqs_hz, pink_pow, ref_powers):
    """주어진 FIR 필터에 대한 A/C/Z/K 가중 RMS 변화 계산"""
    _, eq_gains_complex = signal.freqz(fir_coeffs, 1, worN=freqs_hz, fs=fs)
    eq_gains_sq = np.abs(eq_gains_complex)**2
    power_post_eq = pink_pow * eq_gains_sq

    results = {}
    for wt in ['A', 'C', 'Z', 'K']:
        w_gain_sq = get_weighting_gains_linear(freqs_hz, fs, wt)**2
        tot_pow = np.sum(power_post_eq * w_gain_sq)
        
        # 0으로 나누는 것을 방지
        if ref_powers.get(wt, 0) > 1e-12:
            results[wt] = 10 * np.log10(tot_pow / ref_powers[wt])
        else:
            results[wt] = -999.0  # 오류 값
            
    valid_results = [v for v in results.values() if v > -900]
    if valid_results:
        results['average'] = np.mean(valid_results)
        results['consistency'] = np.std(valid_results)
    else:
        results['average'] = -999.0
        results['consistency'] = 0.0
        
    return results

# ----------  메인 루틴  -----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Generate a C++ lookup table for ISO-226 based pre-amp values.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # 범위 인수
    ap.add_argument("--t_min", type=float, default=20.0, help="Minimum target phon level.")
    ap.add_argument("--t_max", type=float, default=85.0, help="Maximum target phon level.")
    ap.add_argument("--t_step", type=float, default=1.0, help="Step for target phon level.")
    ap.add_argument("--r_min", type=float, default=20.0, help="Minimum reference phon level.")
    ap.add_argument("--r_max", type=float, default=85.0, help="Maximum reference phon level.")
    ap.add_argument("--r_step", type=float, default=1.0, help="Step for reference phon level.")
    
    # FIR 및 시스템 인수
    ap.add_argument("--taps", type=int, default=2047, help="Number of FIR taps.")
    ap.add_argument("--fs", type=int, default=48000, help="Sampling frequency in Hz.")
    ap.add_argument("--headroom", type=float, default=TP_HEADROOM_DBTP, help="True Peak headroom in dBTP.")

    # 출력 인수
    ap.add_argument("-o", "--output", type=str, default="recommended_preamp_map_rms_aczk.hpp",
                    help="Output C++ header file name.")
    ap.add_argument("--map_name", type=str, default="recommended_preamp_map_rms_aczk",
                    help="Name of the std::map variable in the C++ code.")

    args = ap.parse_args()

    # 계산할 Phon 레벨 범위 생성
    target_phons = np.arange(args.t_min, args.t_max + args.t_step / 2, args.t_step)
    ref_phons = np.arange(args.r_min, args.r_max + args.r_step / 2, args.r_step)

    print(f"계산 설정:")
    print(f"  - Target Phons: {args.t_min} to {args.t_max} (step {args.t_step}) -> {len(target_phons)}개")
    print(f"  - Reference Phons: {args.r_min} to {args.r_max} (step {args.r_step}) -> {len(ref_phons)}개")
    print(f"  - FIR Taps: {args.taps}, FS: {args.fs} Hz")
    
    # Count only valid pairs where target <= reference
    total_calcs = 0
    for ref_phon in ref_phons:
        for target_phon in target_phons:
            if target_phon <= ref_phon:
                total_calcs += 1
    
    print(f"  - 총 계산 횟수: {total_calcs} (target <= reference 조건)")
    print("-" * 30)

    # 계산을 위한 공통 주파수 샘플 및 Pink 1/f 파워 스펙트럼 (한 번만 계산)
    f_calc = np.logspace(np.log10(20), np.log10(args.fs / 2 - 1), 1024)
    pink_pow = 1.0 / np.maximum(f_calc, 1e-9)
    pink_pow /= np.sum(pink_pow)

    results_map = {}
    current_calc = 0
    start_time = time.time()

    # 외부 루프: 레퍼런스 Phon
    for ref_phon in ref_phons:
        print(f"\nProcessing Reference Phon: {ref_phon:.1f}")
        results_map[ref_phon] = {}

        # 레퍼런스(ref→ref) 필터에 대한 가중 파워 계산 (이 레퍼런스 레벨에 대한 기준값)
        fir_ref, _ = design_fir(ref_phon, ref_phon, args.taps, args.fs)
        _, eq_ref_complex = signal.freqz(fir_ref, 1, worN=f_calc, fs=args.fs)
        eq_ref_sq = np.abs(eq_ref_complex)**2
        pow_after_ref = pink_pow * eq_ref_sq
        
        ref_pows = {}
        for wt in ['A', 'C', 'Z', 'K']:
            w_gain_sq = get_weighting_gains_linear(f_calc, args.fs, wt)**2
            ref_pows[wt] = np.sum(pow_after_ref * w_gain_sq)

        # 클리핑 방지를 위한 최대 부스트 계산
        max_boost_db = 20 * np.log10(np.max(np.abs(eq_ref_complex)))

        # 내부 루프: 타겟 Phon
        for target_phon in target_phons:
            # Skip if target > reference (only process target <= reference)
            if target_phon > ref_phon:
                continue
                
            current_calc += 1
            progress = (current_calc / total_calcs) * 100
            
            # 진행률 표시
            elapsed = time.time() - start_time
            eta = (elapsed / current_calc * (total_calcs - current_calc)) if current_calc > 0 else 0
            sys.stdout.write(
                f"\r  -> Target {target_phon:.1f} ({current_calc}/{total_calcs}) [{progress:.1f}%] "
                f"ETA: {int(eta//60)}m {int(eta%60)}s   "
            )
            sys.stdout.flush()

            # (target → ref) FIR 필터 설계
            fir_target, _ = design_fir(target_phon, ref_phon, args.taps, args.fs)
            
            # SPL 변화 계산
            splchg = rms_spl_change(fir_target, args.fs, f_calc, pink_pow, ref_pows)
            
            # 프리앰프 계산
            # 1. SPL 목표에 맞춘 프리앰프 (목표 SPL = 레퍼런스 SPL + SPL 변화 + 프리앰프)
            preamp_spl_target = target_phon - ref_phon - splchg['average']
            # 2. 클리핑 방지를 위한 프리앰프 (보수적)
            preamp_clip = args.headroom - max(0, max_boost_db)
            # 3. 두 제약 조건 중 더 작은 값(더 많이 줄이는 값)을 최종 프리앰프로 선택
            preamp_final = round(min(preamp_spl_target, preamp_clip), 2)
            
            results_map[ref_phon][target_phon] = preamp_final

    print(f"\n\n모든 계산 완료. 총 소요 시간: {time.time() - start_time:.2f}초")
    
    # C++ 맵 파일 생성
    print(f"'{args.output}' 파일에 C++ 조회 테이블을 생성합니다...")
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(f"// Generated by generate_preamp_map.py on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"// Calculation based on RMS power change with A/C/Z/K weighting average.\n")
            f.write(f"// Only includes pairs where target phon <= reference phon\n")
            f.write(f"// Parameters: Taps={args.taps}, Fs={args.fs}Hz, Headroom={args.headroom}dBTP\n\n")
            f.write("#include <map>\n\n")
            f.write(f"const std::map<double, std::map<double, double>> {args.map_name} = {{\n")

            sorted_ref_phons = sorted(results_map.keys())
            for i, ref_phon in enumerate(sorted_ref_phons):
                f.write(f"    {{{ref_phon:.1f}, {{ // For Reference Phon {ref_phon:.1f}\n")
                
                inner_map = results_map[ref_phon]
                sorted_target_phons = sorted(inner_map.keys())
                
                # Only include target phons that are <= reference phon
                valid_target_phons = [t for t in sorted_target_phons if t <= ref_phon]
                
                for j, target_phon in enumerate(valid_target_phons):
                    preamp_val = inner_map[target_phon]
                    f.write(f"        {{{target_phon:.1f}, {preamp_val:.2f}}}")
                    if j < len(valid_target_phons) - 1:
                        f.write(",")
                    f.write("\n")
                
                f.write("    }}")
                if i < len(sorted_ref_phons) - 1:
                    f.write(",")
                f.write("\n")

            f.write("};\n")
        print("파일 생성이 완료되었습니다.")
    except IOError as e:
        print(f"오류: 파일을 쓰는 데 실패했습니다. {e}")

if __name__ == "__main__":
    main()