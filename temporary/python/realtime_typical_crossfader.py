#!/usr/bin/env python3
"""
Real-time Typical Use Case with Crossfader
- 60→80 phon filter with automatic level correction
- Real-time wet/dry control with keyboard (1-0 keys)
"""

import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy import signal
import threading
import queue
import time
from pynput import keyboard
import argparse
import sys
import os

# Import functions
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from loudness_fir import design_fir
from typical_use_case_fixed import calculate_rms_spl_change

class TypicalUseCaseCrossfader:
    def __init__(self, audio_file, target_phon=60, reference_phon=80, 
                 blocksize=2048, fade_time=0.05, numtaps=513):
        """
        Initialize typical use case crossfader
        """
        # Load audio file
        print(f"Loading audio file: {audio_file}")
        self.audio, self.fs = sf.read(audio_file)
        
        # Convert to stereo if needed
        if len(self.audio.shape) == 1:
            self.audio = np.column_stack([self.audio, self.audio])
        
        self.blocksize = blocksize
        self.numtaps = numtaps
        
        # Design FIR filter
        print(f"\nDesigning FIR filter...")
        print(f"  Target: {target_phon} phon")
        print(f"  Reference: {reference_phon} phon")
        print(f"  Perceptual compensation: 0% (typical use case)")
        
        self.fir_coeffs, _ = design_fir(target_phon, reference_phon, numtaps, self.fs)
        
        # Calculate level correction
        print("\nCalculating level correction...")
        self.correction_db, spl_changes = calculate_rms_spl_change(self.fir_coeffs, self.fs)
        self.correction_linear = 10 ** (self.correction_db / 20)
        
        print(f"\nTypical Use Case Settings:")
        print(f"  Ambient noise: 50 dB")
        print(f"  Playback level: 60 dB") 
        print(f"  Filter: {target_phon}→{reference_phon} phon")
        print(f"  Level correction: {self.correction_db:+.2f} dB")
        
        # Print filter response
        from loudness_fir import ISO_FREQ
        _, h = signal.freqz(self.fir_coeffs, 1, worN=ISO_FREQ, fs=self.fs)
        gain_db = 20 * np.log10(np.abs(h))
        
        print(f"\nFilter characteristics:")
        for i in range(0, len(ISO_FREQ), 5):
            if ISO_FREQ[i] < self.fs/2:
                print(f"  {ISO_FREQ[i]:5.0f} Hz: {gain_db[i]:+6.2f} dB")
        
        # FIR filter state for each channel
        self.filter_state_l = np.zeros(numtaps - 1)
        self.filter_state_r = np.zeros(numtaps - 1)
        
        # Playback position
        self.position = 0
        self.total_samples = len(self.audio)
        
        # Crossfade parameters
        self.crossfade = 0.0  # 0.0 = 100% dry, 1.0 = 100% wet
        self.target_crossfade = 0.0
        self.fade_samples = int(fade_time * self.fs)
        
        # Control
        self.playing = False
        
        print(f"\nAudio info:")
        print(f"  Sample rate: {self.fs} Hz")
        print(f"  Duration: {self.total_samples / self.fs:.1f} seconds")
        print(f"  Block size: {blocksize} samples")
        print(f"  FIR taps: {numtaps}")
        print(f"  Latency: {numtaps / 2 / self.fs * 1000:.1f} ms")
        
    def process_block(self, block):
        """Apply FIR filter with level correction"""
        # Process left channel
        filtered_l, self.filter_state_l = signal.lfilter(
            self.fir_coeffs, 1.0, block[:, 0], zi=self.filter_state_l
        )
        
        # Process right channel
        filtered_r, self.filter_state_r = signal.lfilter(
            self.fir_coeffs, 1.0, block[:, 1], zi=self.filter_state_r
        )
        
        # Combine channels and apply level correction
        filtered = np.column_stack([filtered_l, filtered_r]) * self.correction_linear
        
        # Soft limiting to prevent clipping
        threshold = 0.95
        mask = np.abs(filtered) > threshold
        if np.any(mask):
            over = np.abs(filtered[mask]) - threshold
            filtered[mask] = np.sign(filtered[mask]) * (threshold + np.tanh(over * 2) * 0.05)
        
        return filtered
        
    def audio_callback(self, outdata, frames, time, status):
        """Audio callback for sounddevice"""
        if status:
            print(f'Audio callback status: {status}')
        
        # Check if we have enough samples
        if self.position + frames > self.total_samples:
            # Loop back to beginning
            self.position = 0
            self.filter_state_l.fill(0)
            self.filter_state_r.fill(0)
        
        # Get audio block
        dry_block = self.audio[self.position:self.position + frames]
        
        # Apply FIR filter with correction
        wet_block = self.process_block(dry_block)
        
        # Smooth crossfade transition
        if self.crossfade != self.target_crossfade:
            diff = self.target_crossfade - self.crossfade
            step = diff / self.fade_samples
            
            fade_values = np.zeros(frames)
            for i in range(frames):
                if abs(self.crossfade - self.target_crossfade) > 0.001:
                    self.crossfade += step
                else:
                    self.crossfade = self.target_crossfade
                fade_values[i] = self.crossfade
            
            fade_values = fade_values[:, np.newaxis]
        else:
            fade_values = self.crossfade
        
        # Equal-power crossfade
        angle = fade_values * np.pi / 2
        gain_dry = np.cos(angle)
        gain_wet = np.sin(angle)
        
        # Mix signals
        outdata[:] = dry_block * gain_dry + wet_block * gain_wet
        
        # Update position
        self.position += frames
        
    def start(self):
        """Start audio playback"""
        self.playing = True
        self.stream = sd.OutputStream(
            samplerate=self.fs,
            blocksize=self.blocksize,
            channels=2,
            callback=self.audio_callback,
            finished_callback=self.stop
        )
        self.stream.start()
        print("\nPlayback started!")
        print("\nControls:")
        print("  1-9 : Crossfade (1=original, 9=90% filtered)")
        print("  0   : 100% filtered (60→80 phon with correction)")
        print("  r   : Reset to original")
        print("  q   : Quit")
        print("\n")
        
    def stop(self):
        """Stop audio playback"""
        self.playing = False
        if hasattr(self, 'stream'):
            self.stream.close()
        print("\nPlayback stopped")
        
    def set_crossfade(self, value):
        """Set crossfade value (0.0 to 1.0)"""
        self.target_crossfade = np.clip(value, 0.0, 1.0)
        percentage = self.target_crossfade * 100
        bar_length = 40
        filled = int(bar_length * self.target_crossfade)
        bar = '=' * filled + '-' * (bar_length - filled)
        
        # Show current state
        if self.target_crossfade == 0:
            state = "ORIGINAL"
        elif self.target_crossfade == 1:
            state = f"FILTERED (60→80 phon, {self.correction_db:+.1f}dB)"
        else:
            state = f"{percentage:.1f}% filtered"
            
        print(f"\rCrossfade: [{bar}] {state:<40}", end='', flush=True)
        
    def on_key_press(self, key):
        """Handle keyboard input"""
        try:
            if hasattr(key, 'char'):
                if key.char == 'q':
                    self.stop()
                    return False
                elif key.char == 'r':
                    self.set_crossfade(0.0)
                elif key.char in '1234567890':
                    # Map 1-9,0 to 0.0-1.0
                    if key.char == '0':
                        value = 1.0
                    else:
                        value = (int(key.char) - 1) / 9.0
                    self.set_crossfade(value)
        except AttributeError:
            pass
        
    def run(self):
        """Run the crossfader"""
        self.start()
        
        # Setup keyboard listener
        with keyboard.Listener(on_press=self.on_key_press) as listener:
            try:
                while self.playing:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                pass
            
        self.stop()


def main():
    parser = argparse.ArgumentParser(
        description='Real-time typical use case with crossfader control',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Typical Use Case:
  - Ambient noise: 50 dB
  - Playback level: 60 dB  
  - Filter: 60→80 phon
  - Automatic level correction for consistent loudness

Controls:
  1-9  : Set crossfade (1=original, 9=90% filtered)
  0    : 100% filtered
  r    : Reset to original
  q    : Quit

Example:
  %(prog)s music.flac
  %(prog)s music.flac --blocksize 1024  # Lower latency
  %(prog)s music.flac --taps 2047       # Higher quality
""")
    
    parser.add_argument('audio_file', help='Audio file to process')
    parser.add_argument('--blocksize', type=int, default=2048,
                        help='Audio block size (default: 2048)')
    parser.add_argument('--taps', type=int, default=513,
                        help='FIR filter taps (default: 513)')
    parser.add_argument('--fade-time', type=float, default=0.05,
                        help='Crossfade time in seconds (default: 0.05)')
    
    args = parser.parse_args()
    
    # Validate inputs
    if not os.path.exists(args.audio_file):
        print(f"Error: File '{args.audio_file}' not found")
        sys.exit(1)
    
    try:
        # Create and run typical use case crossfader
        crossfader = TypicalUseCaseCrossfader(
            args.audio_file,
            target_phon=60,      # Fixed for typical use case
            reference_phon=80,   # Fixed for typical use case
            blocksize=args.blocksize,
            fade_time=args.fade_time,
            numtaps=args.taps
        )
        crossfader.run()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()