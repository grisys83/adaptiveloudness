#!/usr/bin/env python3
"""
Real-time FIR Filter with Crossfader
Apply adaptive loudness filter in real-time with wet/dry control
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

# Import loudness functions from process_audio_offline
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from process_audio_offline import calculate_loudness_gain, design_fir_filter

class RealtimeFIRCrossfader:
    def __init__(self, audio_file, target_phon=40, reference_phon=60, 
                 compensation=0.4, blocksize=2048, fade_time=0.05, numtaps=513):
        """
        Initialize real-time FIR filter with crossfader
        
        Args:
            audio_file: Path to audio file
            target_phon: Target loudness level
            reference_phon: Reference loudness level
            compensation: Perceptual compensation (0-1)
            blocksize: Audio block size
            fade_time: Crossfade transition time
            numtaps: FIR filter taps
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
        print(f"Designing FIR filter...")
        print(f"  Target: {target_phon} phon")
        print(f"  Reference: {reference_phon} phon")
        print(f"  Compensation: {compensation * 100}%")
        
        gain_db = calculate_loudness_gain(target_phon, reference_phon, compensation)
        self.fir_coeffs = design_fir_filter(gain_db, self.fs, numtaps)
        
        # Print filter info
        print(f"\nFilter characteristics:")
        from process_audio_offline import ISO_FREQ
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
        
        print(f"\nSample rate: {self.fs} Hz")
        print(f"Duration: {self.total_samples / self.fs:.1f} seconds")
        print(f"Block size: {blocksize} samples")
        print(f"FIR taps: {numtaps}")
        print(f"Latency: {numtaps / 2 / self.fs * 1000:.1f} ms")
        
    def process_block(self, block):
        """Apply FIR filter to audio block"""
        # Process left channel
        filtered_l, self.filter_state_l = signal.lfilter(
            self.fir_coeffs, 1.0, block[:, 0], zi=self.filter_state_l
        )
        
        # Process right channel
        filtered_r, self.filter_state_r = signal.lfilter(
            self.fir_coeffs, 1.0, block[:, 1], zi=self.filter_state_r
        )
        
        # Combine channels
        filtered = np.column_stack([filtered_l, filtered_r])
        
        # Soft limiting to prevent clipping
        threshold = 0.95
        mask = np.abs(filtered) > threshold
        if np.any(mask):
            # Soft knee compression
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
            # Reset filter states for seamless loop
            self.filter_state_l.fill(0)
            self.filter_state_r.fill(0)
        
        # Get audio block
        dry_block = self.audio[self.position:self.position + frames]
        
        # Apply FIR filter
        wet_block = self.process_block(dry_block)
        
        # Smooth crossfade transition
        if self.crossfade != self.target_crossfade:
            # Calculate fade step
            diff = self.target_crossfade - self.crossfade
            step = diff / self.fade_samples
            
            # Apply fade with sample-by-sample precision
            fade_values = np.zeros(frames)
            for i in range(frames):
                if abs(self.crossfade - self.target_crossfade) > 0.001:
                    self.crossfade += step
                else:
                    self.crossfade = self.target_crossfade
                fade_values[i] = self.crossfade
            
            # Expand fade values for stereo
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
        print("Controls:")
        print("  1-9 : Crossfade (1=dry, 9=90% wet)")
        print("  0   : 100% wet (full FIR filter)")
        print("  q   : Quit")
        print("  r   : Reset to dry")
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
            state = "DRY (no filter)"
        elif self.target_crossfade == 1:
            state = "WET (full filter)"
        else:
            state = f"{percentage:.1f}% filtered"
            
        print(f"\rCrossfade: [{bar}] {state:<20}", end='', flush=True)
        
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
        description='Real-time FIR filter with crossfader control',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Controls:
  1-9  : Set crossfade (1=dry, 9=90% wet)
  0    : 100% wet (full FIR filter)
  r    : Reset to dry
  q    : Quit

Example:
  # Basic usage with default settings (40->60 phon, 40% compensation)
  %(prog)s music.flac
  
  # Custom loudness settings
  %(prog)s music.flac --target 50 --reference 70 --compensation 0.6
  
  # Lower latency with smaller filter
  %(prog)s music.flac --taps 257 --blocksize 1024
""")
    
    parser.add_argument('audio_file', help='Audio file to process')
    parser.add_argument('--target', type=float, default=40,
                        help='Target playback level in phons (default: 40)')
    parser.add_argument('--reference', type=float, default=60,
                        help='Reference level in phons (default: 60)')
    parser.add_argument('--compensation', type=float, default=0.4,
                        help='Perceptual compensation 0-1 (default: 0.4)')
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
    
    if args.compensation < 0 or args.compensation > 1:
        print("Error: Compensation must be between 0 and 1")
        sys.exit(1)
    
    if args.target < 20 or args.target > 100:
        print("Error: Target phon must be between 20 and 100")
        sys.exit(1)
    
    if args.reference < 20 or args.reference > 100:
        print("Error: Reference phon must be between 20 and 100")
        sys.exit(1)
    
    try:
        # Create and run FIR crossfader
        crossfader = RealtimeFIRCrossfader(
            args.audio_file,
            target_phon=args.target,
            reference_phon=args.reference,
            compensation=args.compensation,
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