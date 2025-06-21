#!/usr/bin/env python3
"""
Simple Crossfade Gain Compensation
- Reduce overall gain based on crossfade position
- Maximum reduction at 50% mix
"""

import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy import signal
import time
from pynput import keyboard
import argparse
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from loudness_fir import design_fir
from typical_use_case_fixed import calculate_rms_spl_change

class SimpleCrossfadeGain:
    def __init__(self, audio_file, target_phon=60, reference_phon=80,
                 blocksize=4096, numtaps=4095, max_reduction_db=-3.0):
        """
        Initialize with simple gain compensation
        max_reduction_db: Maximum gain reduction at 50% mix (default -3dB)
        """
        print(f"Loading audio file: {audio_file}")
        self.audio, self.fs = sf.read(audio_file)
        
        if len(self.audio.shape) == 1:
            self.audio = np.column_stack([self.audio, self.audio])
        
        self.blocksize = blocksize
        self.numtaps = numtaps
        self.max_reduction_db = max_reduction_db
        
        # FIR delay
        self.fir_delay_samples = (numtaps - 1) // 2
        self.fir_delay_ms = self.fir_delay_samples / self.fs * 1000
        
        print(f"\nSimple Gain Compensation:")
        print(f"  Maximum reduction at 50% mix: {max_reduction_db} dB")
        print(f"  FIR taps: {numtaps}")
        print(f"  FIR delay: {self.fir_delay_ms:.1f} ms")
        
        # Design FIR filter
        print(f"\nDesigning filter ({target_phon}→{reference_phon} phon)...")
        self.fir_coeffs, _ = design_fir(target_phon, reference_phon, numtaps, self.fs)
        
        # Calculate level correction
        self.correction_db, _ = calculate_rms_spl_change(self.fir_coeffs, self.fs)
        self.correction_linear = 10 ** (self.correction_db / 20)
        print(f"  Level correction: {self.correction_db:+.2f} dB")
        
        # Create gain compensation curve
        self.create_gain_curve()
        
        # Initialize buffers
        self.dry_delay_buffer = np.zeros((self.fir_delay_samples, 2))
        self.dry_delay_pos = 0
        
        self.filter_state_l = np.zeros(numtaps - 1)
        self.filter_state_r = np.zeros(numtaps - 1)
        
        self.position = 0
        self.total_samples = len(self.audio)
        self.crossfade = 0.0
        self.target_crossfade = 0.0
        self.fade_samples = int(0.05 * self.fs)
        
        self.playing = False
        
    def create_gain_curve(self):
        """
        Create gain reduction curve:
        - 0dB at 0% and 100% (single signal)
        - Maximum reduction at 50% (both signals equal)
        """
        x = np.linspace(0, 1, 101)
        
        # Simple parabolic curve: max reduction at center
        # reduction = max_reduction * 4 * x * (1 - x)
        self.gain_reduction_curve = self.max_reduction_db * 4 * x * (1 - x)
        
        # Convert to linear
        self.gain_curve_linear = 10 ** (self.gain_reduction_curve / 20)
        
        print(f"\nGain compensation curve:")
        print(f"  At 0%: {self.gain_reduction_curve[0]:.1f} dB")
        print(f"  At 25%: {self.gain_reduction_curve[25]:.1f} dB")
        print(f"  At 50%: {self.gain_reduction_curve[50]:.1f} dB")
        print(f"  At 75%: {self.gain_reduction_curve[75]:.1f} dB")
        print(f"  At 100%: {self.gain_reduction_curve[100]:.1f} dB")
        
    def get_gain_compensation(self, crossfade):
        """Get gain compensation for current crossfade position"""
        idx = int(crossfade * 100)
        idx = np.clip(idx, 0, 100)
        return self.gain_curve_linear[idx]
        
    def delay_dry_signal(self, dry_block):
        """Delay dry signal to match FIR"""
        delayed = np.zeros_like(dry_block)
        
        for i in range(len(dry_block)):
            delayed[i] = self.dry_delay_buffer[self.dry_delay_pos]
            self.dry_delay_buffer[self.dry_delay_pos] = dry_block[i]
            self.dry_delay_pos = (self.dry_delay_pos + 1) % self.fir_delay_samples
        
        return delayed
        
    def audio_callback(self, outdata, frames, time, status):
        """Audio callback with simple gain compensation"""
        if status:
            print(f'Audio callback status: {status}')
        
        if self.position + frames > self.total_samples:
            self.position = 0
            self.filter_state_l.fill(0)
            self.filter_state_r.fill(0)
            self.dry_delay_buffer.fill(0)
            self.dry_delay_pos = 0
        
        # Get audio block
        dry_block = self.audio[self.position:self.position + frames].copy()
        
        # Apply FIR filter for wet signal
        filtered_l, self.filter_state_l = signal.lfilter(
            self.fir_coeffs, 1.0, dry_block[:, 0], zi=self.filter_state_l
        )
        filtered_r, self.filter_state_r = signal.lfilter(
            self.fir_coeffs, 1.0, dry_block[:, 1], zi=self.filter_state_r
        )
        wet_block = np.column_stack([filtered_l, filtered_r]) * self.correction_linear
        
        # Delay dry signal
        dry_block_delayed = self.delay_dry_signal(dry_block)
        
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
        mixed = dry_block_delayed * gain_dry + wet_block * gain_wet
        
        # Apply gain compensation based on crossfade position
        gain_comp = self.get_gain_compensation(self.crossfade)
        outdata[:] = mixed * gain_comp
        
        # Very soft limiting just in case
        mask = np.abs(outdata) > 0.99
        if np.any(mask):
            outdata[mask] = np.sign(outdata[mask]) * 0.99
        
        self.position += frames
        
    def start(self):
        """Start playback"""
        self.playing = True
        self.stream = sd.OutputStream(
            samplerate=self.fs,
            blocksize=self.blocksize,
            channels=2,
            callback=self.audio_callback,
            finished_callback=self.stop,
            latency='low'
        )
        self.stream.start()
        print("\n🎵 Simple Gain Compensation Active!")
        print("\nControls:")
        print("  1-9 : Crossfade")
        print("  0   : 100% filtered")
        print("  q   : Quit")
        print(f"\n✨ Automatic gain reduction up to {self.max_reduction_db}dB at 50% mix\n")
        
    def stop(self):
        self.playing = False
        if hasattr(self, 'stream'):
            self.stream.close()
        print("\nPlayback stopped")
        
    def set_crossfade(self, value):
        self.target_crossfade = np.clip(value, 0.0, 1.0)
        percentage = self.target_crossfade * 100
        bar_length = 40
        filled = int(bar_length * self.target_crossfade)
        bar = '=' * filled + '-' * (bar_length - filled)
        
        # Get current gain reduction
        gain_comp = self.get_gain_compensation(self.target_crossfade)
        gain_db = 20 * np.log10(gain_comp)
        
        state = f"{percentage:3.0f}% (gain: {gain_db:+.1f}dB)"
        
        print(f"\rCrossfade: [{bar}] {state:<20}", end='', flush=True)
        
    def on_key_press(self, key):
        try:
            if hasattr(key, 'char'):
                if key.char == 'q':
                    self.stop()
                    return False
                elif key.char in '1234567890':
                    value = 1.0 if key.char == '0' else (int(key.char) - 1) / 9.0
                    self.set_crossfade(value)
        except AttributeError:
            pass
        
    def run(self):
        self.start()
        with keyboard.Listener(on_press=self.on_key_press) as listener:
            try:
                while self.playing:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                pass
        self.stop()


def main():
    parser = argparse.ArgumentParser(
        description='Simple gain compensation for clipping-free crossfading'
    )
    
    parser.add_argument('audio_file', help='Audio file')
    parser.add_argument('--max-reduction', type=float, default=-3.0,
                        help='Maximum gain reduction at 50%% mix in dB (default: -3.0)')
    parser.add_argument('--taps', type=int, default=4095,
                        help='FIR filter taps (default: 4095)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.audio_file):
        print(f"Error: File '{args.audio_file}' not found")
        sys.exit(1)
    
    try:
        crossfader = SimpleCrossfadeGain(
            args.audio_file,
            numtaps=args.taps,
            max_reduction_db=args.max_reduction
        )
        crossfader.run()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()