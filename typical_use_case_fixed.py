#!/usr/bin/env python3
"""
Typical Use Case: Adaptive Loudness with Level Correction (Fixed)
- Ambient noise: 50dB
- Playback level: 60dB  
- Filter: 60→80 phon (no perceptual compensation)
- Automatic level correction using A/C/Z/K weighting average
"""

import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy import signal
import sys
import os
import argparse
import time

# Import the correct design_fir function from loudness_fir.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from loudness_fir import design_fir

# K-Weighting (ITU-R BS.1770)
def get_k_weighting_gains_linear(freqs_hz, fs):
    """BS.1770-4 K-weighting FIR implementation"""
    z = np.array([-np.inf, -np.inf])
    p1 = 2 * np.pi * 38.135199
    p2 = 2 * np.pi * 1550.0
    p_analog = -0.5 * (p1**2 + p2**2) + np.array([1, -1]) * 0.5 * np.sqrt((p1**2 + p2**2)**2 - 4 * (p1 * p2)**2 + 0j)

    z_d = np.exp(z / fs)
    p_d = np.exp(p_analog / fs)
    b, a = signal.zpk2tf(z_d, p_d, 1.0)
    
    # Normalize
    w_norm, h_norm = signal.freqz(b, a, worN=[1000], fs=fs)
    b /= np.abs(h_norm[0])
    
    w, h = signal.freqz(b, a, worN=freqs_hz, fs=fs)
    return np.abs(h)

def get_weighting_gains_linear(freqs_hz, fs, curve='A'):
    """A, C, Z, K weighting curves"""
    if curve == 'Z':
        return np.ones_like(freqs_hz)
    if curve == 'K':
        return get_k_weighting_gains_linear(freqs_hz, fs)
    
    # A/C weighting zpk (IEC 61672)
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
    else:
        return np.ones_like(freqs_hz)

    z_d, p_d, k_d = signal.bilinear_zpk(z, p, k, fs)
    b, a = signal.zpk2tf(z_d, p_d, k_d)

    _, h = signal.freqz(b, a, worN=freqs_hz, fs=fs)
    return np.abs(h)

def generate_pink_noise(duration, fs):
    """Generate pink noise (1/f spectrum)"""
    n_samples = int(duration * fs)
    white = np.random.randn(n_samples)
    
    # Paul Kellet's method
    b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786])
    a = np.array([1, -2.494956002, 2.017265875, -0.522189400])
    
    pink = signal.lfilter(b, a, white)
    pink = pink / np.max(np.abs(pink))
    
    return pink

def calculate_rms_spl_change(fir_coeffs, fs):
    """Calculate RMS SPL change for FIR filter using A/C/Z/K weighting"""
    print("\nCalculating filter gain correction...")
    
    # Frequency samples for calculation
    f_calc = np.logspace(np.log10(20), np.log10(fs / 2 - 1), 1024)
    
    # Pink noise power spectrum (1/f)
    pink_pow = 1.0 / np.maximum(f_calc, 1e-9)
    pink_pow /= np.sum(pink_pow)
    
    # Get filter frequency response
    _, eq_gains_complex = signal.freqz(fir_coeffs, 1, worN=f_calc, fs=fs)
    eq_gains_sq = np.abs(eq_gains_complex)**2
    
    # Power after filtering
    power_post_eq = pink_pow * eq_gains_sq
    
    # Reference power (flat response)
    ref_powers = {}
    for wt in ['A', 'C', 'Z', 'K']:
        w_gain_sq = get_weighting_gains_linear(f_calc, fs, wt)**2
        ref_powers[wt] = np.sum(pink_pow * w_gain_sq)
    
    # Calculate SPL change for each weighting
    results = {}
    print("\nFilter response analysis:")
    print("-" * 50)
    
    for wt in ['A', 'C', 'Z', 'K']:
        w_gain_sq = get_weighting_gains_linear(f_calc, fs, wt)**2
        tot_pow = np.sum(power_post_eq * w_gain_sq)
        
        if ref_powers.get(wt, 0) > 1e-12:
            spl_change = 10 * np.log10(tot_pow / ref_powers[wt])
            results[wt] = spl_change
            print(f"{wt}-weighted SPL change: {spl_change:+6.2f} dB")
        else:
            results[wt] = 0.0
    
    # Calculate average
    valid_results = [v for v in results.values()]
    if valid_results:
        average_spl_change = np.mean(valid_results)
        std_spl_change = np.std(valid_results)
        print(f"\nAverage SPL change: {average_spl_change:+6.2f} dB")
        print(f"Standard deviation: {std_spl_change:6.2f} dB")
    else:
        average_spl_change = 0.0
    
    # Correction is negative of SPL change
    correction_db = -average_spl_change
    print(f"\nRecommended gain correction: {correction_db:+6.2f} dB")
    
    return correction_db, results

def process_typical_use_case(audio_file, output_file=None, numtaps=513):
    """
    Process audio for typical use case with proper level correction
    """
    # Parameters for typical use case
    ambient_noise = 50  # dB
    playback_level = 60  # dB
    target_phon = 60
    reference_phon = 80
    
    print("="*60)
    print("Typical Use Case Processing")
    print("="*60)
    print(f"Ambient noise: {ambient_noise} dB")
    print(f"Playback level: {playback_level} dB")
    print(f"Target: {target_phon} phon → Reference: {reference_phon} phon")
    print(f"Perceptual compensation: 0% (disabled)")
    print(f"FIR taps: {numtaps}")
    print("="*60)
    
    # Read audio
    print(f"\nLoading: {audio_file}")
    audio, fs = sf.read(audio_file)
    
    # Design filter using loudness_fir.py
    print(f"\nDesigning FIR filter...")
    fir_coeffs, freq_response = design_fir(target_phon, reference_phon, numtaps, fs)
    
    # Print designed filter response
    print("\nFilter frequency response (from design):")
    from loudness_fir import ISO_FREQ
    # Calculate gain in dB for each ISO frequency
    _, h = signal.freqz(fir_coeffs, 1, worN=ISO_FREQ, fs=fs)
    gain_db = 20 * np.log10(np.abs(h))
    
    for i in range(0, len(ISO_FREQ), 5):
        if ISO_FREQ[i] < fs/2:
            print(f"  {ISO_FREQ[i]:5.0f} Hz: {gain_db[i]:+6.2f} dB")
    
    # Calculate correction for nonlinear distortion
    correction_db, spl_changes = calculate_rms_spl_change(fir_coeffs, fs)
    
    # Apply filter
    print("\nApplying filter...")
    if len(audio.shape) == 1:
        filtered = signal.convolve(audio, fir_coeffs, mode='same')
    else:
        filtered = np.zeros_like(audio)
        for ch in range(audio.shape[1]):
            filtered[:, ch] = signal.convolve(audio[:, ch], fir_coeffs, mode='same')
    
    # Apply level correction
    correction_linear = 10 ** (correction_db / 20)
    filtered_corrected = filtered * correction_linear
    print(f"Applied level correction: {correction_db:+.2f} dB")
    
    # Normalize to prevent clipping
    max_val = np.max(np.abs(filtered_corrected))
    if max_val > 0.95:
        filtered_corrected = filtered_corrected * 0.95 / max_val
        print(f"Applied peak normalization (peak was {max_val:.2f})")
    
    # Save if output file specified
    if output_file:
        print(f"\nSaving: {output_file}")
        sf.write(output_file, filtered_corrected, fs)
        print("Processing complete!")
    
    return audio, filtered_corrected, fs, correction_db

def main():
    parser = argparse.ArgumentParser(
        description='Process audio for typical use case (50dB ambient, 60dB playback)',
        epilog="""
Example:
  %(prog)s input.flac
  %(prog)s input.flac -o output.flac
  %(prog)s input.flac --play
  %(prog)s input.flac --taps 2047  # Higher quality filter
""")
    
    parser.add_argument('input', help='Input audio file')
    parser.add_argument('-o', '--output', help='Output file (optional)')
    parser.add_argument('--play', action='store_true', 
                        help='Play comparison after processing')
    parser.add_argument('--taps', type=int, default=513,
                        help='FIR filter taps (default: 513)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Error: File '{args.input}' not found")
        sys.exit(1)
    
    # Process audio
    original, processed, fs, correction = process_typical_use_case(
        args.input, args.output, args.taps
    )
    
    # Play comparison if requested
    if args.play:
        print("\n" + "="*60)
        print("Real-time A/B Comparison")
        print("="*60)
        print("Press SPACE to toggle between original/processed")
        print("Press Q to quit")
        
        # Simple toggle playback
        from pynput import keyboard
        
        class Player:
            def __init__(self, audio1, audio2, fs):
                self.audio = [audio1, audio2]
                self.fs = fs
                self.current = 0
                self.position = 0
                self.playing = True
                
            def audio_callback(self, outdata, frames, time, status):
                if status:
                    print(status)
                
                audio = self.audio[self.current]
                if self.position + frames > len(audio):
                    self.position = 0
                
                outdata[:] = audio[self.position:self.position + frames]
                self.position += frames
                
            def toggle(self):
                self.current = 1 - self.current
                mode = "PROCESSED" if self.current else "ORIGINAL"
                print(f"\rPlaying: {mode} (60→80 phon with {correction:+.1f}dB correction)    ", 
                      end='', flush=True)
                
            def on_key_press(self, key):
                if key == keyboard.Key.space:
                    self.toggle()
                elif hasattr(key, 'char') and key.char == 'q':
                    self.playing = False
                    return False
                    
        player = Player(original, processed, fs)
        
        with sd.OutputStream(samplerate=fs, channels=2, 
                           callback=player.audio_callback):
            print("\rPlaying: ORIGINAL                           ", end='', flush=True)
            
            with keyboard.Listener(on_press=player.on_key_press) as listener:
                while player.playing:
                    time.sleep(0.1)
        
        print("\n\nPlayback stopped")

if __name__ == '__main__':
    main()