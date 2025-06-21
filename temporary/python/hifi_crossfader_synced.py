#!/usr/bin/env python3
"""
HiFi Crossfader with Delay Compensation
- 4095 taps FIR filter for maximum quality
- Automatic delay compensation for perfect sync
- Real-time wet/dry control
"""

import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy import signal
import threading
import time
from pynput import keyboard
import argparse
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from loudness_fir import design_fir
from typical_use_case_fixed import calculate_rms_spl_change

class HiFiSyncedCrossfader:
    def __init__(self, audio_file, target_phon=60, reference_phon=80, 
                 blocksize=4096, fade_time=0.05, numtaps=4095):
        """
        Initialize HiFi crossfader with delay compensation
        """
        # Load audio file
        print(f"Loading audio file: {audio_file}")
        self.audio, self.fs = sf.read(audio_file)
        
        # Convert to stereo if needed
        if len(self.audio.shape) == 1:
            self.audio = np.column_stack([self.audio, self.audio])
        
        self.blocksize = blocksize
        self.numtaps = numtaps
        
        # Calculate FIR filter delay
        self.fir_delay_samples = (numtaps - 1) // 2
        self.fir_delay_ms = self.fir_delay_samples / self.fs * 1000
        
        print(f"\nHiFi Configuration:")
        print(f"  FIR taps: {numtaps}")
        print(f"  FIR delay: {self.fir_delay_samples} samples ({self.fir_delay_ms:.1f} ms)")
        print(f"  Block size: {blocksize} samples")
        
        # Design FIR filter
        print(f"\nDesigning HiFi FIR filter...")
        print(f"  Target: {target_phon} phon")
        print(f"  Reference: {reference_phon} phon")
        
        self.fir_coeffs, _ = design_fir(target_phon, reference_phon, numtaps, self.fs)
        
        # Calculate level correction
        print("\nCalculating level correction...")
        self.correction_db, _ = calculate_rms_spl_change(self.fir_coeffs, self.fs)
        self.correction_linear = 10 ** (self.correction_db / 20)
        print(f"  Level correction: {self.correction_db:+.2f} dB")
        
        # Create delay buffer for dry signal to match FIR delay
        self.dry_delay_buffer = np.zeros((self.fir_delay_samples, 2))
        self.dry_delay_pos = 0
        
        # FIR filter state for each channel
        self.filter_state_l = np.zeros(numtaps - 1)
        self.filter_state_r = np.zeros(numtaps - 1)
        
        # Playback position
        self.position = 0
        self.total_samples = len(self.audio)
        
        # Crossfade parameters
        self.crossfade = 0.0
        self.target_crossfade = 0.0
        self.fade_samples = int(fade_time * self.fs)
        
        # Latency measurement
        self.measure_latency = False
        self.latency_click_time = 0
        
        self.playing = False
        
        print(f"\nAudio info:")
        print(f"  Sample rate: {self.fs} Hz")
        print(f"  Duration: {self.total_samples / self.fs:.1f} seconds")
        print(f"\nDelay compensation: ENABLED")
        print(f"  Dry signal delayed by {self.fir_delay_ms:.1f} ms to match FIR")
        
    def delay_dry_signal(self, dry_block):
        """Delay dry signal to match FIR filter delay"""
        delayed = np.zeros_like(dry_block)
        
        for i in range(len(dry_block)):
            # Get delayed sample from circular buffer
            delayed[i] = self.dry_delay_buffer[self.dry_delay_pos]
            
            # Store new sample in delay buffer
            self.dry_delay_buffer[self.dry_delay_pos] = dry_block[i]
            
            # Update circular buffer position
            self.dry_delay_pos = (self.dry_delay_pos + 1) % self.fir_delay_samples
        
        return delayed
        
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
        
        # Soft limiting
        threshold = 0.95
        mask = np.abs(filtered) > threshold
        if np.any(mask):
            over = np.abs(filtered[mask]) - threshold
            filtered[mask] = np.sign(filtered[mask]) * (threshold + np.tanh(over * 2) * 0.05)
        
        return filtered
        
    def inject_click(self, block):
        """Inject click for latency measurement"""
        if self.measure_latency:
            # Add click at beginning of block
            click_amplitude = 0.5
            click_samples = min(10, len(block))  # 10 sample click
            block[:click_samples] += click_amplitude
            self.latency_click_time = time.time()
            self.measure_latency = False
            print("\n[Click injected for latency measurement]")
        return block
        
    def audio_callback(self, outdata, frames, time, status):
        """Audio callback with delay compensation"""
        if status:
            print(f'Audio callback status: {status}')
        
        # Check if we have enough samples
        if self.position + frames > self.total_samples:
            self.position = 0
            self.filter_state_l.fill(0)
            self.filter_state_r.fill(0)
            self.dry_delay_buffer.fill(0)
            self.dry_delay_pos = 0
        
        # Get audio block
        dry_block = self.audio[self.position:self.position + frames].copy()
        
        # Inject click if measuring latency
        dry_block = self.inject_click(dry_block)
        
        # Process wet signal (FIR filtered)
        wet_block = self.process_block(dry_block)
        
        # Delay dry signal to match FIR delay
        dry_block_delayed = self.delay_dry_signal(dry_block)
        
        # Smooth crossfade
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
        
        # Equal-power crossfade between delayed dry and wet
        angle = fade_values * np.pi / 2
        gain_dry = np.cos(angle)
        gain_wet = np.sin(angle)
        
        # Mix signals (both are now time-aligned)
        outdata[:] = dry_block_delayed * gain_dry + wet_block * gain_wet
        
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
            finished_callback=self.stop,
            latency='low'
        )
        self.stream.start()
        print("\n🎵 HiFi Playback Started!")
        print("\nControls:")
        print("  1-9 : Crossfade (1=original, 9=90% filtered)")
        print("  0   : 100% filtered")
        print("  r   : Reset to original")
        print("  l   : Measure system latency")
        print("  q   : Quit")
        print("\n⚡ Delay compensation active - Dry/Wet perfectly synchronized!")
        print("\n")
        
    def stop(self):
        """Stop audio playback"""
        self.playing = False
        if hasattr(self, 'stream'):
            self.stream.close()
        print("\nPlayback stopped")
        
    def set_crossfade(self, value):
        """Set crossfade value"""
        self.target_crossfade = np.clip(value, 0.0, 1.0)
        percentage = self.target_crossfade * 100
        bar_length = 40
        filled = int(bar_length * self.target_crossfade)
        bar = '=' * filled + '-' * (bar_length - filled)
        
        if self.target_crossfade == 0:
            state = "ORIGINAL (delayed for sync)"
        elif self.target_crossfade == 1:
            state = f"FILTERED ({self.correction_db:+.1f}dB corrected)"
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
                elif key.char == 'l':
                    self.measure_latency = True
                    print("\n[Press SPACE when you hear the click]")
                elif key.char in '1234567890':
                    if key.char == '0':
                        value = 1.0
                    else:
                        value = (int(key.char) - 1) / 9.0
                    self.set_crossfade(value)
            elif key == keyboard.Key.space and self.latency_click_time > 0:
                latency = (time.time() - self.latency_click_time) * 1000
                print(f"\nMeasured total system latency: {latency:.1f} ms")
                print(f"(FIR delay: {self.fir_delay_ms:.1f} ms + system: {latency - self.fir_delay_ms:.1f} ms)")
                self.latency_click_time = 0
        except AttributeError:
            pass
        
    def run(self):
        """Run the crossfader"""
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
        description='HiFi crossfader with automatic delay compensation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
HiFi Features:
  - Ultra-high quality FIR filter (4095 taps default)
  - Automatic delay compensation for perfect sync
  - Level correction for consistent loudness
  - Latency measurement tool

Example:
  %(prog)s music.flac
  %(prog)s music.flac --taps 8191    # Even higher quality
  %(prog)s music.flac --taps 2047    # Good quality, less delay
""")
    
    parser.add_argument('audio_file', help='Audio file to process')
    parser.add_argument('--target', type=float, default=60,
                        help='Target phon level (default: 60)')
    parser.add_argument('--reference', type=float, default=80,
                        help='Reference phon level (default: 80)')
    parser.add_argument('--blocksize', type=int, default=4096,
                        help='Audio block size (default: 4096)')
    parser.add_argument('--taps', type=int, default=4095,
                        help='FIR filter taps (default: 4095)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.audio_file):
        print(f"Error: File '{args.audio_file}' not found")
        sys.exit(1)
    
    # Ensure odd number of taps for symmetric filter
    if args.taps % 2 == 0:
        args.taps += 1
        print(f"Adjusted to odd number of taps: {args.taps}")
    
    try:
        crossfader = HiFiSyncedCrossfader(
            args.audio_file,
            target_phon=args.target,
            reference_phon=args.reference,
            blocksize=args.blocksize,
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