#!/usr/bin/env python3
"""
Offline Audio Processor with Adaptive Loudness
Step 1: Basic loudness filter with gain parameter
"""

import numpy as np
import soundfile as sf
import argparse
from scipy import signal
import os
import sys

# ISO 226:2003 Equal-Loudness Contours data
ISO_FREQ = np.array([20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
                     200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
                     2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000])

ISO_CURVES = {
    20: np.array([74.3, 64.4, 56.3, 49.5, 44.7, 40.6, 37.5, 35.0, 33.1, 31.6, 30.2, 28.9, 27.7, 26.6, 25.6,
                  24.7, 23.8, 22.5, 21.2, 20.3, 19.1, 18.1, 17.2, 16.3, 15.0, 13.4, 11.5, 10.4, 10.1, 11.2, 13.4]),
    30: np.array([86.3, 75.3, 66.2, 58.4, 52.7, 48.0, 44.4, 41.3, 39.2, 37.3, 35.7, 34.2, 32.9, 31.7, 30.6,
                  29.5, 28.4, 27.1, 25.8, 24.7, 23.3, 22.1, 21.0, 19.9, 18.2, 16.1, 14.6, 13.6, 13.3, 14.6, 17.1]),
    40: np.array([96.9, 85.4, 76.3, 68.3, 62.1, 57.0, 52.5, 48.7, 46.2, 44.0, 42.1, 40.4, 38.9, 37.5, 36.3,
                  35.1, 33.9, 32.6, 31.2, 29.9, 28.4, 27.1, 25.9, 24.7, 22.9, 20.7, 19.0, 17.8, 17.3, 18.6, 21.4]),
    50: np.array([107.6, 95.6, 86.4, 78.3, 71.1, 65.0, 60.1, 56.1, 53.4, 51.0, 48.9, 47.1, 45.4, 43.8, 42.3,
                  40.9, 39.4, 38.1, 36.6, 35.1, 33.4, 32.0, 30.6, 29.2, 27.4, 25.1, 23.4, 22.1, 21.6, 22.8, 25.8]),
    60: np.array([118.6, 106.1, 96.8, 88.4, 81.3, 75.0, 69.2, 65.1, 62.2, 59.6, 57.3, 55.3, 53.5, 51.7, 50.1,
                  48.6, 47.0, 45.6, 44.0, 42.3, 40.5, 38.9, 37.3, 35.6, 33.7, 31.3, 29.6, 28.3, 27.9, 29.1, 32.3]),
    70: np.array([129.5, 116.9, 107.1, 98.3, 91.2, 84.7, 78.5, 74.2, 71.1, 68.2, 65.7, 63.5, 61.5, 59.6, 57.9,
                  56.2, 54.5, 53.0, 51.3, 49.5, 47.6, 45.8, 44.1, 42.3, 40.1, 37.7, 35.9, 34.6, 34.3, 35.4, 38.7]),
    80: np.array([139.9, 127.3, 117.5, 108.6, 101.4, 94.8, 88.4, 83.9, 80.7, 77.6, 74.9, 72.6, 70.4, 68.3, 66.4,
                  64.6, 62.8, 61.1, 59.3, 57.4, 55.3, 53.4, 51.4, 49.5, 47.2, 44.8, 43.0, 41.7, 41.2, 42.2, 45.6]),
    90: np.array([150.2, 137.5, 127.7, 118.7, 111.4, 104.8, 98.4, 93.8, 90.4, 87.1, 84.2, 81.7, 79.4, 77.1, 75.1,
                  73.3, 71.4, 69.6, 67.6, 65.6, 63.5, 61.5, 59.5, 57.4, 55.1, 52.7, 50.8, 49.4, 48.8, 49.8, 53.2]),
    100: np.array([160.4, 147.6, 137.8, 128.8, 121.4, 114.8, 108.3, 103.7, 100.3, 96.9, 93.9, 91.4, 88.9, 86.6, 84.5,
                   82.5, 80.5, 78.6, 76.6, 74.5, 72.4, 70.3, 68.3, 66.2, 63.9, 61.4, 59.5, 58.1, 57.5, 58.5, 62.0])
}


def interpolate_iso_curve(phon):
    """Interpolate ISO 226 curve for given phon level"""
    phon_levels = sorted(ISO_CURVES.keys())
    
    if phon in ISO_CURVES:
        return ISO_CURVES[phon]
    
    # Clamp to valid range
    phon = max(phon_levels[0], min(phon_levels[-1], phon))
    
    # Find surrounding curves
    lo = phon_levels[0]
    hi = phon_levels[-1]
    
    for i in range(len(phon_levels) - 1):
        if phon_levels[i] <= phon <= phon_levels[i + 1]:
            lo = phon_levels[i]
            hi = phon_levels[i + 1]
            break
    
    # Linear interpolation
    w = (phon - lo) / (hi - lo)
    return ISO_CURVES[lo] * (1 - w) + ISO_CURVES[hi] * w


def calculate_loudness_gain(target_phon, reference_phon, perceptual_compensation=0.4):
    """
    Calculate frequency-dependent gain based on ISO 226 curves
    
    Args:
        target_phon: Playback loudness level in phons
        reference_phon: Reference loudness level in phons
        perceptual_compensation: Factor to reduce compensation (0.4 = 40%)
    
    Returns:
        gain_db: Frequency-dependent gain in dB
    """
    target_curve = interpolate_iso_curve(target_phon)
    reference_curve = interpolate_iso_curve(reference_phon)
    
    # Calculate gain difference
    gain_db = reference_curve - target_curve
    
    # Normalize to 1kHz
    idx_1khz = np.where(ISO_FREQ == 1000)[0][0]
    gain_db -= gain_db[idx_1khz]
    
    # Apply perceptual compensation
    gain_db *= perceptual_compensation
    
    return gain_db


def design_fir_filter(gain_db, fs, numtaps=513):
    """
    Design FIR filter using frequency sampling method
    
    Args:
        gain_db: Gain in dB at ISO frequencies
        fs: Sample rate
        numtaps: Number of filter taps
    
    Returns:
        h: FIR filter coefficients
    """
    # Convert to linear gain
    gain_linear = 10 ** (gain_db / 20)
    
    # Create frequency points up to Nyquist
    nyq = fs / 2
    freq_points = [0]
    gain_points = [gain_linear[0]]
    
    # Add ISO frequencies below Nyquist
    for i, f in enumerate(ISO_FREQ):
        if f < nyq:
            freq_points.append(f)
            gain_points.append(gain_linear[i])
    
    # Add Nyquist frequency
    freq_points.append(nyq)
    gain_points.append(gain_linear[-1])
    
    # Design filter using firwin2
    h = signal.firwin2(numtaps, freq_points, gain_points, fs=fs)
    
    return h


def process_audio_file(input_file, output_file, target_phon, reference_phon, 
                      perceptual_compensation=0.4, numtaps=513, level_correction=None):
    """
    Process audio file with adaptive loudness compensation
    
    Args:
        input_file: Input audio file path
        output_file: Output audio file path
        target_phon: Target playback level in phons
        reference_phon: Reference level in phons
        perceptual_compensation: Compensation factor (0-1)
        numtaps: FIR filter length
    """
    # Read audio file
    print(f"Reading audio file: {input_file}")
    audio, fs = sf.read(input_file)
    
    # Calculate gain curve
    print(f"Calculating loudness compensation...")
    print(f"  Target: {target_phon} phon")
    print(f"  Reference: {reference_phon} phon")
    print(f"  Compensation: {perceptual_compensation * 100}%")
    
    gain_db = calculate_loudness_gain(target_phon, reference_phon, perceptual_compensation)
    
    # Design FIR filter
    print(f"Designing FIR filter ({numtaps} taps)...")
    h = design_fir_filter(gain_db, fs, numtaps)
    
    # Process audio
    print("Processing audio...")
    if len(audio.shape) == 1:
        # Mono
        filtered = signal.convolve(audio, h, mode='same')
    else:
        # Stereo or multichannel
        filtered = np.zeros_like(audio)
        for ch in range(audio.shape[1]):
            filtered[:, ch] = signal.convolve(audio[:, ch], h, mode='same')
    
    # Apply level correction if specified
    if level_correction is not None:
        correction_linear = 10 ** (level_correction / 20)
        filtered *= correction_linear
        print(f"  Applied level correction: {level_correction:+.2f} dB")
    
    # Normalize to prevent clipping
    max_val = np.max(np.abs(filtered))
    if max_val > 0.95:
        filtered = filtered * 0.95 / max_val
        print(f"  Applied normalization (peak: {max_val:.2f})")
    
    # Write output file
    print(f"Writing output file: {output_file}")
    sf.write(output_file, filtered, fs)
    
    print("Processing complete!")
    
    # Print frequency response info
    print("\nFrequency response adjustment:")
    for i in range(0, len(ISO_FREQ), 5):
        print(f"  {ISO_FREQ[i]:5.0f} Hz: {gain_db[i]:+6.2f} dB")


def main():
    parser = argparse.ArgumentParser(
        description='Process audio file with adaptive loudness compensation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process with 40 phon playback, 50 phon reference
  %(prog)s input.wav output.wav --target 40 --reference 50
  
  # Use 60%% perceptual compensation
  %(prog)s input.wav output.wav --target 40 --reference 50 --compensation 0.6
  
  # High quality with 1025 taps
  %(prog)s input.wav output.wav --target 40 --reference 50 --taps 1025
""")
    
    parser.add_argument('input', help='Input audio file')
    parser.add_argument('output', help='Output audio file')
    parser.add_argument('--target', type=float, default=40,
                        help='Target playback level in phons (default: 40)')
    parser.add_argument('--reference', type=float, default=60,
                        help='Reference level in phons (default: 60)')
    parser.add_argument('--compensation', type=float, default=0.4,
                        help='Perceptual compensation factor 0-1 (default: 0.4)')
    parser.add_argument('--taps', type=int, default=513,
                        help='FIR filter taps (default: 513)')
    parser.add_argument('--level-correction', type=float, default=None,
                        help='Additional level correction in dB (optional)')
    
    args = parser.parse_args()
    
    # Validate inputs
    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found")
        sys.exit(1)
    
    if args.compensation < 0 or args.compensation > 1:
        print("Error: Compensation must be between 0 and 1")
        sys.exit(1)
    
    if args.target < 20 or args.target > 100:
        print("Error: Target phon must be between 20 and 100")
        sys.exit(1)
    
    if args.reference < 20 or args.reference > 100:
        print("Error: Reference phon must be between 20 and 100")
        sys.exit(1)
    
    # Process the file
    process_audio_file(
        args.input,
        args.output,
        args.target,
        args.reference,
        args.compensation,
        args.taps,
        args.level_correction
    )


if __name__ == '__main__':
    main()