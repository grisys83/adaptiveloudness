#!/usr/bin/env python3
"""
Typical Use Case: Adaptive Loudness with Level Correction
- Ambient noise: 50dB
- Playback level: 60dB
- Filter: 60→80 phon (no perceptual compensation)
- Automatic level correction to maintain consistent loudness
"""

import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy import signal
import sys
import os

# Import functions
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from process_audio_offline import calculate_loudness_gain, design_fir_filter
# Copy necessary functions to avoid matplotlib dependency
def generate_pink_noise(duration, fs):
    """Generate pink noise (1/f spectrum)"""
    n_samples = int(duration * fs)
    white = np.random.randn(n_samples)
    
    # Using Paul Kellet's refined method
    b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786])
    a = np.array([1, -2.494956002, 2.017265875, -0.522189400])
    
    pink = signal.lfilter(b, a, white)
    pink = pink / np.max(np.abs(pink))
    
    return pink

# Weighting curves
WEIGHTING_FREQ = np.array([10, 12.5, 16, 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 
                          200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 
                          2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000])

A_WEIGHTING = np.array([-70.4, -63.4, -56.7, -50.5, -44.7, -39.4, -34.6, -30.2, -26.2, -22.5, 
                       -19.1, -16.1, -13.4, -10.9, -8.6, -6.6, -4.8, -3.2, -1.9, -0.8, 
                       0.0, 0.6, 1.0, 1.2, 1.3, 1.2, 1.0, 0.5, -0.1, -1.1, -2.5, -4.3, -6.6, -9.3])

C_WEIGHTING = np.array([-14.3, -11.2, -8.5, -6.2, -4.4, -3.0, -2.0, -1.3, -0.8, -0.5, 
                       -0.3, -0.2, -0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -0.1, 
                       -0.2, -0.3, -0.5, -0.8, -1.3, -2.0, -3.0, -4.4, -6.2, -8.5, -11.2, -14.3, -17.7, -21.3])

K_WEIGHTING = np.array([-50.0, -40.0, -30.0, -23.0, -17.0, -12.0, -8.0, -5.0, -3.0, -1.5, 
                       -0.5, 0.0, 0.5, 1.0, 1.3, 1.5, 1.6, 1.7, 1.8, 1.9, 
                       2.0, 2.0, 2.0, 2.0, 1.5, 1.0, 0.5, -0.5, -2.0, -4.0, -6.5, -9.5, -13.0, -17.0])

def apply_weighting_filter(audio, fs, weighting_type='A'):
    """Apply frequency weighting filter"""
    if weighting_type == 'Z':
        return audio
    
    if weighting_type == 'A':
        weighting_db = A_WEIGHTING
    elif weighting_type == 'C':
        weighting_db = C_WEIGHTING
    elif weighting_type == 'K':
        weighting_db = K_WEIGHTING
    else:
        raise ValueError(f"Unknown weighting type: {weighting_type}")
    
    weighting_linear = 10 ** (weighting_db / 20)
    
    nyq = fs / 2
    freq_points = [0]
    gain_points = [weighting_linear[0]]
    
    for i, f in enumerate(WEIGHTING_FREQ):
        if f < nyq:
            freq_points.append(f)
            gain_points.append(weighting_linear[i])
    
    freq_points.append(nyq)
    gain_points.append(weighting_linear[-1])
    
    h = signal.firwin2(257, freq_points, gain_points, fs=fs)
    
    return signal.convolve(audio, h, mode='same')

def calculate_rms_in_band(audio, fs, f_low=20, f_high=16000):
    """Calculate RMS in frequency band"""
    sos = signal.butter(4, [f_low, f_high], btype='bandpass', fs=fs, output='sos')
    filtered = signal.sosfilt(sos, audio)
    rms = np.sqrt(np.mean(filtered ** 2))
    return rms

def calculate_filter_gain_correction(fir_coeffs, fs):
    """
    Calculate gain correction by measuring filter response to pink noise
    Returns correction in dB to maintain consistent loudness
    """
    print("Calculating filter gain correction...")
    
    # Generate test pink noise
    duration = 10.0
    pink = generate_pink_noise(duration, fs)
    
    # Apply FIR filter
    filtered = signal.convolve(pink, fir_coeffs, mode='same')
    
    # Measure RMS with different weightings
    weightings = ['Z', 'A', 'C', 'K']
    corrections = []
    
    print("\nFilter response analysis:")
    print("-" * 50)
    for weighting in weightings:
        # Original pink noise
        pink_weighted = apply_weighting_filter(pink, fs, weighting)
        rms_original = calculate_rms_in_band(pink_weighted, fs, 20, 16000)
        
        # Filtered pink noise
        filtered_weighted = apply_weighting_filter(filtered, fs, weighting)
        rms_filtered = calculate_rms_in_band(filtered_weighted, fs, 20, 16000)
        
        # Calculate difference
        diff_db = 20 * np.log10(rms_filtered / rms_original)
        correction = -diff_db
        corrections.append(correction)
        
        print(f"{weighting}-weighted: {diff_db:+6.2f} dB → correction: {correction:+6.2f} dB")
    
    # Calculate mean correction
    mean_correction = np.mean(corrections)
    print(f"\nMean correction: {mean_correction:+6.2f} dB")
    
    return mean_correction

def process_typical_use_case(audio_file, output_file=None):
    """
    Process audio for typical use case
    """
    # Parameters for typical use case
    ambient_noise = 50  # dB
    playback_level = 60  # dB
    target_phon = 60
    reference_phon = 80
    compensation = 0.0  # No perceptual compensation as requested
    
    print("="*60)
    print("Typical Use Case Processing")
    print("="*60)
    print(f"Ambient noise: {ambient_noise} dB")
    print(f"Playback level: {playback_level} dB")
    print(f"Target: {target_phon} phon → Reference: {reference_phon} phon")
    print(f"Perceptual compensation: {compensation*100}% (disabled)")
    print("="*60)
    
    # Read audio
    print(f"\nLoading: {audio_file}")
    audio, fs = sf.read(audio_file)
    
    # Design filter
    gain_db = calculate_loudness_gain(target_phon, reference_phon, compensation)
    fir_coeffs = design_fir_filter(gain_db, fs, numtaps=513)
    
    # Print filter response first
    print("\nFilter frequency response:")
    from process_audio_offline import ISO_FREQ
    for i in range(0, len(ISO_FREQ), 5):
        if ISO_FREQ[i] < fs/2:
            print(f"  {ISO_FREQ[i]:5.0f} Hz: {gain_db[i]:+6.2f} dB")
    
    # Calculate correction for nonlinear distortion
    correction_db = calculate_filter_gain_correction(fir_coeffs, fs)
    
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
    
    # Print frequency response
    print("\nFrequency response adjustment:")
    from process_audio_offline import ISO_FREQ
    for i in range(0, len(ISO_FREQ), 5):
        if ISO_FREQ[i] < fs/2:
            print(f"  {ISO_FREQ[i]:5.0f} Hz: {gain_db[i]:+6.2f} dB")
    
    return audio, filtered_corrected, fs, correction_db

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Process audio for typical use case (50dB ambient, 60dB playback)',
        epilog="""
Example:
  %(prog)s input.flac
  %(prog)s input.flac -o output.flac
  %(prog)s input.flac --play
""")
    
    parser.add_argument('input', help='Input audio file')
    parser.add_argument('-o', '--output', help='Output file (optional)')
    parser.add_argument('--play', action='store_true', 
                        help='Play comparison after processing')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Error: File '{args.input}' not found")
        sys.exit(1)
    
    # Process audio
    original, processed, fs, correction = process_typical_use_case(
        args.input, args.output
    )
    
    # Play comparison if requested
    if args.play:
        print("\n" + "="*60)
        print("Real-time A/B Comparison")
        print("="*60)
        print("Press SPACE to toggle between original/processed")
        print("Press Q to quit")
        
        # Simple toggle playback
        import time
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
                print(f"\rPlaying: {mode} (with {correction:+.1f}dB correction)    ", 
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