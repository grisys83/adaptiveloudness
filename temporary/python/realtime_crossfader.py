#!/usr/bin/env python3
"""
Real-time Crossfader with Keyboard Control
Play two audio files simultaneously with wet/dry control (1-0 keys)
"""

import numpy as np
import soundfile as sf
import sounddevice as sd
import threading
import queue
import time
from pynput import keyboard
import argparse
import sys
import os

class RealtimeCrossfader:
    def __init__(self, file1, file2, blocksize=2048, fade_time=0.05):
        """
        Initialize crossfader with two audio files
        
        Args:
            file1: Path to first audio file (dry)
            file2: Path to second audio file (wet)
            blocksize: Audio block size
            fade_time: Crossfade transition time in seconds
        """
        # Load audio files
        print(f"Loading audio files...")
        self.audio1, self.fs1 = sf.read(file1)
        self.audio2, self.fs2 = sf.read(file2)
        
        # Check sample rates match
        if self.fs1 != self.fs2:
            raise ValueError(f"Sample rates must match: {self.fs1} != {self.fs2}")
        
        self.fs = self.fs1
        self.blocksize = blocksize
        
        # Convert to stereo if needed
        if len(self.audio1.shape) == 1:
            self.audio1 = np.column_stack([self.audio1, self.audio1])
        if len(self.audio2.shape) == 1:
            self.audio2 = np.column_stack([self.audio2, self.audio2])
        
        # Ensure same length
        min_len = min(len(self.audio1), len(self.audio2))
        self.audio1 = self.audio1[:min_len]
        self.audio2 = self.audio2[:min_len]
        
        # Playback position
        self.position = 0
        self.total_samples = min_len
        
        # Crossfade parameters
        self.crossfade = 0.0  # 0.0 = 100% dry, 1.0 = 100% wet
        self.target_crossfade = 0.0
        self.fade_samples = int(fade_time * self.fs)
        
        # Control
        self.playing = False
        self.queue = queue.Queue()
        
        print(f"Sample rate: {self.fs} Hz")
        print(f"Duration: {self.total_samples / self.fs:.1f} seconds")
        print(f"Block size: {self.blocksize} samples")
        
    def audio_callback(self, outdata, frames, time, status):
        """Audio callback for sounddevice"""
        if status:
            print(f'Audio callback status: {status}')
        
        # Check if we have enough samples
        if self.position + frames > self.total_samples:
            # Loop back to beginning
            self.position = 0
        
        # Get audio blocks
        block1 = self.audio1[self.position:self.position + frames]
        block2 = self.audio2[self.position:self.position + frames]
        
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
        # Using sin/cos curves for constant power
        angle = fade_values * np.pi / 2
        gain1 = np.cos(angle)
        gain2 = np.sin(angle)
        
        # Mix signals
        outdata[:] = block1 * gain1 + block2 * gain2
        
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
        print("Use keys 1-9,0 to control crossfade (1=dry, 0=wet)")
        print("Press 'q' to quit\n")
        
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
        print(f"\rCrossfade: [{bar}] {percentage:5.1f}% wet", end='', flush=True)
        
    def on_key_press(self, key):
        """Handle keyboard input"""
        try:
            if hasattr(key, 'char'):
                if key.char == 'q':
                    self.stop()
                    return False
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
        description='Real-time audio crossfader with keyboard control',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Controls:
  1-9  : Set crossfade (1=100% dry, 9=90% wet)
  0    : 100% wet
  q    : Quit

Example:
  %(prog)s original.wav processed.wav
""")
    
    parser.add_argument('file1', help='First audio file (dry)')
    parser.add_argument('file2', help='Second audio file (wet)')
    parser.add_argument('--blocksize', type=int, default=2048,
                        help='Audio block size (default: 2048)')
    parser.add_argument('--fade-time', type=float, default=0.05,
                        help='Crossfade transition time in seconds (default: 0.05)')
    
    args = parser.parse_args()
    
    # Check files exist
    if not os.path.exists(args.file1):
        print(f"Error: File '{args.file1}' not found")
        sys.exit(1)
    if not os.path.exists(args.file2):
        print(f"Error: File '{args.file2}' not found")
        sys.exit(1)
    
    try:
        # Create and run crossfader
        crossfader = RealtimeCrossfader(
            args.file1, 
            args.file2,
            blocksize=args.blocksize,
            fade_time=args.fade_time
        )
        crossfader.run()
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()