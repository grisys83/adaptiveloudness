#!/usr/bin/env python3
"""
Test loudness filter response with pink noise
Measures RMS with different weighting curves (A, C, K, Z)
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
import sys
import os

# Add parent directory to path to import process_audio_offline
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from process_audio_offline import calculate_loudness_gain, design_fir_filter, ISO_FREQ

# Weighting curve frequencies (IEC 61672-1:2013)
WEIGHTING_FREQ = np.array([10, 12.5, 16, 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 
                          200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 
                          2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000])

# A-weighting curve (dB)
A_WEIGHTING = np.array([-70.4, -63.4, -56.7, -50.5, -44.7, -39.4, -34.6, -30.2, -26.2, -22.5, 
                       -19.1, -16.1, -13.4, -10.9, -8.6, -6.6, -4.8, -3.2, -1.9, -0.8, 
                       0.0, 0.6, 1.0, 1.2, 1.3, 1.2, 1.0, 0.5, -0.1, -1.1, -2.5, -4.3, -6.6, -9.3])

# C-weighting curve (dB)
C_WEIGHTING = np.array([-14.3, -11.2, -8.5, -6.2, -4.4, -3.0, -2.0, -1.3, -0.8, -0.5, 
                       -0.3, -0.2, -0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -0.1, 
                       -0.2, -0.3, -0.5, -0.8, -1.3, -2.0, -3.0, -4.4, -6.2, -8.5, -11.2, -14.3, -17.7, -21.3])

# K-weighting (approximate, based on ITU-R BS.1770)
K_WEIGHTING = np.array([-50.0, -40.0, -30.0, -23.0, -17.0, -12.0, -8.0, -5.0, -3.0, -1.5, 
                       -0.5, 0.0, 0.5, 1.0, 1.3, 1.5, 1.6, 1.7, 1.8, 1.9, 
                       2.0, 2.0, 2.0, 2.0, 1.5, 1.0, 0.5, -0.5, -2.0, -4.0, -6.5, -9.5, -13.0, -17.0])


def generate_pink_noise(duration, fs):
    """Generate pink noise (1/f spectrum)"""
    n_samples = int(duration * fs)
    white = np.random.randn(n_samples)
    
    # Design pink noise filter (1/f)
    # Using Paul Kellet's refined method
    b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786])
    a = np.array([1, -2.494956002, 2.017265875, -0.522189400])
    
    # Apply filter
    pink = signal.lfilter(b, a, white)
    
    # Normalize
    pink = pink / np.max(np.abs(pink))
    
    return pink


def interpolate_weighting(freq_target, freq_curve, weighting_db):
    """Interpolate weighting curve to target frequencies"""
    return np.interp(freq_target, freq_curve, weighting_db)


def apply_weighting_filter(audio, fs, weighting_type='A'):
    """Apply frequency weighting filter"""
    if weighting_type == 'Z':
        # Z-weighting (flat)
        return audio
    
    # Select weighting curve
    if weighting_type == 'A':
        weighting_db = A_WEIGHTING
    elif weighting_type == 'C':
        weighting_db = C_WEIGHTING
    elif weighting_type == 'K':
        weighting_db = K_WEIGHTING
    else:
        raise ValueError(f"Unknown weighting type: {weighting_type}")
    
    # Convert to linear gain
    weighting_linear = 10 ** (weighting_db / 20)
    
    # Design filter
    nyq = fs / 2
    freq_points = [0]
    gain_points = [weighting_linear[0]]
    
    for i, f in enumerate(WEIGHTING_FREQ):
        if f < nyq:
            freq_points.append(f)
            gain_points.append(weighting_linear[i])
    
    freq_points.append(nyq)
    gain_points.append(weighting_linear[-1])
    
    # Create FIR filter
    h = signal.firwin2(257, freq_points, gain_points, fs=fs)
    
    # Apply filter
    return signal.convolve(audio, h, mode='same')


def calculate_rms_in_band(audio, fs, f_low=20, f_high=16000):
    """Calculate RMS in frequency band"""
    # Design bandpass filter
    sos = signal.butter(4, [f_low, f_high], btype='bandpass', fs=fs, output='sos')
    filtered = signal.sosfilt(sos, audio)
    
    # Calculate RMS
    rms = np.sqrt(np.mean(filtered ** 2))
    return rms


def test_loudness_filter(target_phon=40, reference_phon=60, compensation=0.4, fs=48000):
    """Test loudness filter response with pink noise"""
    
    print(f"\nTesting loudness filter response")
    print(f"Target: {target_phon} phon, Reference: {reference_phon} phon")
    print(f"Compensation: {compensation * 100}%")
    print("-" * 60)
    
    # Generate pink noise
    duration = 10.0  # seconds
    pink = generate_pink_noise(duration, fs)
    
    # Calculate and apply loudness filter
    gain_db = calculate_loudness_gain(target_phon, reference_phon, compensation)
    h = design_fir_filter(gain_db, fs, numtaps=513)
    filtered = signal.convolve(pink, h, mode='same')
    
    # Measure RMS with different weightings
    weightings = ['Z', 'A', 'C', 'K']
    results = {}
    
    for weighting in weightings:
        # Original pink noise
        pink_weighted = apply_weighting_filter(pink, fs, weighting)
        rms_original = calculate_rms_in_band(pink_weighted, fs, 20, 16000)
        
        # Filtered pink noise
        filtered_weighted = apply_weighting_filter(filtered, fs, weighting)
        rms_filtered = calculate_rms_in_band(filtered_weighted, fs, 20, 16000)
        
        # Calculate difference
        diff_db = 20 * np.log10(rms_filtered / rms_original)
        
        results[weighting] = {
            'original_rms': rms_original,
            'filtered_rms': rms_filtered,
            'diff_db': diff_db
        }
        
        print(f"\n{weighting}-weighted measurements:")
        print(f"  Original RMS: {rms_original:.6f}")
        print(f"  Filtered RMS: {rms_filtered:.6f}")
        print(f"  Difference: {diff_db:+.2f} dB")
    
    # Plot frequency response
    plt.figure(figsize=(12, 8))
    
    # Plot 1: Filter frequency response
    plt.subplot(2, 1, 1)
    freq_interp = np.logspace(np.log10(20), np.log10(20000), 1000)
    gain_interp = np.interp(freq_interp, ISO_FREQ, gain_db)
    plt.semilogx(freq_interp, gain_interp, 'b-', linewidth=2)
    plt.grid(True, alpha=0.3)
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Gain (dB)')
    plt.title(f'Loudness Filter Response ({target_phon} → {reference_phon} phon, {compensation*100}% compensation)')
    plt.xlim(20, 20000)
    
    # Plot 2: Weighting curves
    plt.subplot(2, 1, 2)
    colors = {'A': 'red', 'C': 'green', 'K': 'blue'}
    for weighting, color in colors.items():
        if weighting == 'A':
            plt.semilogx(WEIGHTING_FREQ, A_WEIGHTING, color=color, label=f'{weighting}-weighting', linewidth=2)
        elif weighting == 'C':
            plt.semilogx(WEIGHTING_FREQ, C_WEIGHTING, color=color, label=f'{weighting}-weighting', linewidth=2)
        elif weighting == 'K':
            plt.semilogx(WEIGHTING_FREQ, K_WEIGHTING, color=color, label=f'{weighting}-weighting', linewidth=2)
    
    plt.grid(True, alpha=0.3)
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Weighting (dB)')
    plt.title('Frequency Weighting Curves')
    plt.xlim(20, 20000)
    plt.ylim(-80, 10)
    plt.legend()
    
    plt.tight_layout()
    plt.savefig('loudness_filter_test.png', dpi=150)
    plt.show()
    
    return results


def calculate_correction_gain(results):
    """Calculate correction gain to maintain consistent weighted levels"""
    print("\n" + "="*60)
    print("Correction gains to maintain weighted levels:")
    print("="*60)
    
    corrections = []
    for weighting, data in results.items():
        correction = -data['diff_db']
        corrections.append(correction)
        print(f"{weighting}-weighting: {correction:+.2f} dB correction needed")
    
    # Calculate arithmetic mean of corrections
    mean_correction = np.mean(corrections)
    print(f"\nArithmetic mean correction: {mean_correction:+.2f} dB")
    
    return mean_correction


if __name__ == '__main__':
    # Test with different settings
    test_cases = [
        (40, 50, 0.4),  # Quiet listening
        (40, 60, 0.4),  # Very quiet listening
        (60, 70, 0.4),  # Moderate listening
    ]
    
    all_corrections = []
    
    for target, reference, comp in test_cases:
        results = test_loudness_filter(target, reference, comp)
        mean_correction = calculate_correction_gain(results)
        all_corrections.append((target, reference, comp, mean_correction))
        print("\n" + "="*60 + "\n")
    
    # Summary
    print("\nSUMMARY - Mean corrections needed:")
    print("Target  Reference  Compensation  Mean Correction")
    print("-" * 50)
    for target, reference, comp, correction in all_corrections:
        print(f"{target:6.0f}  {reference:9.0f}  {comp:12.1%}  {correction:+14.2f} dB")