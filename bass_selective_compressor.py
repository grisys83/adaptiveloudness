#!/usr/bin/env python3
"""
Bass-Selective Compressor for Crossfade
- Compress only bass frequencies that exceed threshold
- Maintain overall loudness perception
- Reduce crossfade artifacts
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

class BassSelectiveCompressor:
    def __init__(self, audio_file, target_phon=60, reference_phon=80,
                 bass_threshold_db=-6, bass_ratio=4.0, bass_freq=200,
                 blocksize=4096, numtaps=4095):
        """
        Initialize with bass-selective compression
        
        Args:
            bass_threshold_db: Threshold for bass compression
            bass_ratio: Compression ratio for bass
            bass_freq: Crossover frequency for bass/mid split
        """
        print(f"Loading audio file: {audio_file}")
        self.audio, self.fs = sf.read(audio_file)
        
        if len(self.audio.shape) == 1:
            self.audio = np.column_stack([self.audio, self.audio])
        
        self.blocksize = blocksize
        self.numtaps = numtaps
        
        # Bass compression parameters
        self.bass_threshold_db = bass_threshold_db
        self.bass_threshold_linear = 10 ** (bass_threshold_db / 20)
        self.bass_ratio = bass_ratio
        self.bass_freq = bass_freq
        
        # FIR delay
        self.fir_delay_samples = (numtaps - 1) // 2
        self.fir_delay_ms = self.fir_delay_samples / self.fs * 1000
        
        print(f"\nBass-Selective Compression Settings:")
        print(f"  Bass threshold: {bass_threshold_db} dB")
        print(f"  Bass ratio: {bass_ratio}:1")
        print(f"  Bass frequency: < {bass_freq} Hz")
        print(f"  FIR taps: {numtaps}")
        print(f"  FIR delay: {self.fir_delay_ms:.1f} ms")
        
        # Design crossover filters (Linkwitz-Riley 4th order)
        self.design_crossover_filters()
        
        # Design FIR filter
        print(f"\nDesigning loudness filter...")
        self.fir_coeffs, _ = design_fir(target_phon, reference_phon, numtaps, self.fs)
        
        # Calculate level correction
        self.correction_db, _ = calculate_rms_spl_change(self.fir_coeffs, self.fs)
        self.correction_linear = 10 ** (self.correction_db / 20)
        
        print(f"  Level correction: {self.correction_db:+.2f} dB")
        
        # Initialize delay buffers
        self.dry_delay_buffer = np.zeros((self.fir_delay_samples, 2))
        self.dry_delay_pos = 0
        
        # FIR filter states
        self.filter_state_l = np.zeros(numtaps - 1)
        self.filter_state_r = np.zeros(numtaps - 1)
        
        # Crossover filter states
        self.init_filter_states()
        
        # Compression envelope followers
        self.bass_envelope_l = 0.0
        self.bass_envelope_r = 0.0
        self.envelope_attack = np.exp(-1.0 / (0.001 * self.fs))  # 1ms attack
        self.envelope_release = np.exp(-1.0 / (0.050 * self.fs))  # 50ms release
        
        # Loudness normalization
        self.rms_window_size = int(0.1 * self.fs)  # 100ms RMS window
        self.rms_buffer_dry = np.zeros(self.rms_window_size)
        self.rms_buffer_wet = np.zeros(self.rms_window_size)
        self.rms_pos = 0
        
        self.position = 0
        self.total_samples = len(self.audio)
        self.crossfade = 0.0
        self.target_crossfade = 0.0
        self.fade_samples = int(0.05 * self.fs)
        
        self.playing = False
        
    def design_crossover_filters(self):
        """Design Linkwitz-Riley crossover filters"""
        # 4th order Butterworth = 2x 2nd order
        nyq = self.fs / 2
        freq_norm = self.bass_freq / nyq
        
        # Low-pass for bass
        self.sos_bass = signal.butter(4, freq_norm, btype='low', output='sos')
        
        # High-pass for mids/highs
        self.sos_mid = signal.butter(4, freq_norm, btype='high', output='sos')
        
        print(f"  Crossover at {self.bass_freq} Hz (Linkwitz-Riley 24dB/oct)")
        
    def init_filter_states(self):
        """Initialize all filter states"""
        # Crossover states for each channel and path
        self.bass_state_dry_l = signal.sosfilt_zi(self.sos_bass)
        self.bass_state_dry_r = signal.sosfilt_zi(self.sos_bass)
        self.mid_state_dry_l = signal.sosfilt_zi(self.sos_mid)
        self.mid_state_dry_r = signal.sosfilt_zi(self.sos_mid)
        
        self.bass_state_wet_l = signal.sosfilt_zi(self.sos_bass)
        self.bass_state_wet_r = signal.sosfilt_zi(self.sos_bass)
        self.mid_state_wet_l = signal.sosfilt_zi(self.sos_mid)
        self.mid_state_wet_r = signal.sosfilt_zi(self.sos_mid)
        
    def compress_bass(self, bass_signal, envelope, channel='L'):
        """Apply compression to bass signal"""
        compressed = np.zeros_like(bass_signal)
        
        for i in range(len(bass_signal)):
            # Update envelope
            level = abs(bass_signal[i])
            if level > envelope:
                envelope = level + (envelope - level) * self.envelope_attack
            else:
                envelope = level + (envelope - level) * self.envelope_release
            
            # Apply compression
            if envelope > self.bass_threshold_linear:
                # Calculate gain reduction
                over_threshold = envelope / self.bass_threshold_linear
                gain_reduction = (over_threshold ** (1/self.bass_ratio - 1))
                compressed[i] = bass_signal[i] * gain_reduction
            else:
                compressed[i] = bass_signal[i]
        
        return compressed, envelope
        
    def process_with_bass_compression(self, signal_block, is_wet=False):
        """Process signal with selective bass compression"""
        output = np.zeros_like(signal_block)
        
        for ch in range(2):
            # Select appropriate filter states
            if ch == 0:  # Left
                if is_wet:
                    bass_state = self.bass_state_wet_l
                    mid_state = self.mid_state_wet_l
                    envelope = self.bass_envelope_l
                else:
                    bass_state = self.bass_state_dry_l
                    mid_state = self.mid_state_dry_l
                    envelope = self.bass_envelope_l
            else:  # Right
                if is_wet:
                    bass_state = self.bass_state_wet_r
                    mid_state = self.mid_state_wet_r
                    envelope = self.bass_envelope_r
                else:
                    bass_state = self.bass_state_dry_r
                    mid_state = self.mid_state_dry_r
                    envelope = self.bass_envelope_r
            
            # Split into bass and mid/high
            bass, bass_state = signal.sosfilt(self.sos_bass, signal_block[:, ch], zi=bass_state)
            mid, mid_state = signal.sosfilt(self.sos_mid, signal_block[:, ch], zi=mid_state)
            
            # Compress bass
            bass_compressed, envelope = self.compress_bass(bass, envelope, 'L' if ch == 0 else 'R')
            
            # Update states
            if ch == 0:
                if is_wet:
                    self.bass_state_wet_l = bass_state
                    self.mid_state_wet_l = mid_state
                    self.bass_envelope_l = envelope
                else:
                    self.bass_state_dry_l = bass_state
                    self.mid_state_dry_l = mid_state
                    self.bass_envelope_l = envelope
            else:
                if is_wet:
                    self.bass_state_wet_r = bass_state
                    self.mid_state_wet_r = mid_state
                    self.bass_envelope_r = envelope
                else:
                    self.bass_state_dry_r = bass_state
                    self.mid_state_dry_r = mid_state
                    self.bass_envelope_r = envelope
            
            # Recombine
            output[:, ch] = bass_compressed + mid
        
        return output
        
    def calculate_rms_normalization(self, dry_block, wet_block):
        """Calculate normalization factor to match RMS levels"""
        # Update RMS buffers (mono sum for simplicity)
        mono_dry = np.mean(dry_block, axis=1)
        mono_wet = np.mean(wet_block, axis=1)
        
        for i in range(len(mono_dry)):
            self.rms_buffer_dry[self.rms_pos] = mono_dry[i] ** 2
            self.rms_buffer_wet[self.rms_pos] = mono_wet[i] ** 2
            self.rms_pos = (self.rms_pos + 1) % self.rms_window_size
        
        # Calculate RMS
        rms_dry = np.sqrt(np.mean(self.rms_buffer_dry))
        rms_wet = np.sqrt(np.mean(self.rms_buffer_wet))
        
        # Calculate normalization factor
        if rms_wet > 0.001:
            norm_factor = rms_dry / rms_wet
            # Limit normalization range
            norm_factor = np.clip(norm_factor, 0.5, 2.0)
        else:
            norm_factor = 1.0
            
        return norm_factor
        
    def delay_dry_signal(self, dry_block):
        """Delay dry signal to match FIR"""
        delayed = np.zeros_like(dry_block)
        
        for i in range(len(dry_block)):
            delayed[i] = self.dry_delay_buffer[self.dry_delay_pos]
            self.dry_delay_buffer[self.dry_delay_pos] = dry_block[i]
            self.dry_delay_pos = (self.dry_delay_pos + 1) % self.fir_delay_samples
        
        return delayed
        
    def audio_callback(self, outdata, frames, time, status):
        """Audio callback with bass compression"""
        if status:
            print(f'Audio callback status: {status}')
        
        if self.position + frames > self.total_samples:
            self.position = 0
            self.filter_state_l.fill(0)
            self.filter_state_r.fill(0)
            self.dry_delay_buffer.fill(0)
            self.dry_delay_pos = 0
            self.init_filter_states()
        
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
        
        # Apply bass compression to both signals
        dry_compressed = self.process_with_bass_compression(dry_block_delayed, is_wet=False)
        wet_compressed = self.process_with_bass_compression(wet_block, is_wet=True)
        
        # Calculate RMS normalization
        norm_factor = self.calculate_rms_normalization(dry_compressed, wet_compressed)
        wet_normalized = wet_compressed * norm_factor
        
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
        
        # Equal-power crossfade
        angle = fade_values * np.pi / 2
        gain_dry = np.cos(angle)
        gain_wet = np.sin(angle)
        
        # Mix signals
        outdata[:] = dry_compressed * gain_dry + wet_normalized * gain_wet
        
        # Soft limit output
        threshold = 0.95
        mask = np.abs(outdata) > threshold
        if np.any(mask):
            over = np.abs(outdata[mask]) - threshold
            outdata[mask] = np.sign(outdata[mask]) * (threshold + np.tanh(over * 2) * 0.05)
        
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
        print("\n🎵 Bass-Selective Compression Active!")
        print("\nControls:")
        print("  1-9 : Crossfade")
        print("  0   : 100% filtered")
        print("  q   : Quit")
        print("\n✨ Bass compression + RMS normalization enabled\n")
        
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
        
        state = f"{percentage:.1f}% filtered" if 0 < self.target_crossfade < 1 else \
                ("ORIGINAL" if self.target_crossfade == 0 else "FILTERED")
        
        print(f"\rCrossfade: [{bar}] {state:<30}", end='', flush=True)
        
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
        description='Bass-selective compression for smooth crossfading'
    )
    
    parser.add_argument('audio_file', help='Audio file')
    parser.add_argument('--bass-threshold', type=float, default=-6,
                        help='Bass compression threshold in dB (default: -6)')
    parser.add_argument('--bass-ratio', type=float, default=4.0,
                        help='Bass compression ratio (default: 4:1)')
    parser.add_argument('--bass-freq', type=float, default=200,
                        help='Bass crossover frequency (default: 200 Hz)')
    parser.add_argument('--taps', type=int, default=4095,
                        help='FIR filter taps (default: 4095)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.audio_file):
        print(f"Error: File '{args.audio_file}' not found")
        sys.exit(1)
    
    try:
        compressor = BassSelectiveCompressor(
            args.audio_file,
            bass_threshold_db=args.bass_threshold,
            bass_ratio=args.bass_ratio,
            bass_freq=args.bass_freq,
            numtaps=args.taps
        )
        compressor.run()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()