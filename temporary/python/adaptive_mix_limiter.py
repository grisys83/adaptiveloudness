#!/usr/bin/env python3
"""
Adaptive Mix Limiter for Crossfade
- Intelligent gain reduction during crossfade
- Look-ahead limiting to prevent clipping
- Frequency-dependent limiting
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

class AdaptiveMixLimiter:
    def __init__(self, audio_file, target_phon=60, reference_phon=80,
                 blocksize=4096, numtaps=4095):
        """
        Initialize with adaptive limiting for crossfade
        """
        print(f"Loading audio file: {audio_file}")
        self.audio, self.fs = sf.read(audio_file)
        
        if len(self.audio.shape) == 1:
            self.audio = np.column_stack([self.audio, self.audio])
        
        self.blocksize = blocksize
        self.numtaps = numtaps
        
        # FIR delay
        self.fir_delay_samples = (numtaps - 1) // 2
        self.fir_delay_ms = self.fir_delay_samples / self.fs * 1000
        
        # Look-ahead for limiter (5ms)
        self.lookahead_samples = int(0.005 * self.fs)
        self.lookahead_buffer = np.zeros((self.lookahead_samples, 2))
        self.lookahead_pos = 0
        
        print(f"\nAdaptive Mix Limiter Configuration:")
        print(f"  FIR taps: {numtaps}")
        print(f"  FIR delay: {self.fir_delay_ms:.1f} ms")
        print(f"  Look-ahead: {self.lookahead_samples} samples (5ms)")
        
        # Design FIR filter
        print(f"\nDesigning loudness filter...")
        self.fir_coeffs, _ = design_fir(target_phon, reference_phon, numtaps, self.fs)
        
        # Calculate level correction
        self.correction_db, _ = calculate_rms_spl_change(self.fir_coeffs, self.fs)
        self.correction_linear = 10 ** (self.correction_db / 20)
        
        print(f"  Level correction: {self.correction_db:+.2f} dB")
        
        # Multiband splitter for frequency-dependent limiting
        self.design_multiband_filters()
        
        # Initialize buffers and states
        self.dry_delay_buffer = np.zeros((self.fir_delay_samples, 2))
        self.dry_delay_pos = 0
        
        self.filter_state_l = np.zeros(numtaps - 1)
        self.filter_state_r = np.zeros(numtaps - 1)
        
        # Limiter states
        self.gain_reduction = 1.0
        self.gain_smoothing = 0.995  # Smooth gain changes
        
        # Crossfade mix compensation curve
        self.mix_compensation = self.create_mix_compensation_curve()
        
        self.position = 0
        self.total_samples = len(self.audio)
        self.crossfade = 0.0
        self.target_crossfade = 0.0
        self.fade_samples = int(0.05 * self.fs)
        
        self.playing = False
        
    def design_multiband_filters(self):
        """Design 3-band crossover filters"""
        # Crossover frequencies: 200Hz, 2kHz
        self.freq_low = 200
        self.freq_high = 2000
        
        nyq = self.fs / 2
        
        # Low band (< 200Hz)
        self.sos_low = signal.butter(4, self.freq_low/nyq, btype='low', output='sos')
        
        # Mid band (200Hz - 2kHz)
        self.sos_mid = signal.butter(4, [self.freq_low/nyq, self.freq_high/nyq], 
                                     btype='band', output='sos')
        
        # High band (> 2kHz)
        self.sos_high = signal.butter(4, self.freq_high/nyq, btype='high', output='sos')
        
        # Initialize filter states
        self.init_multiband_states()
        
        print(f"  Multiband: Low<{self.freq_low}Hz, Mid={self.freq_low}-{self.freq_high}Hz, High>{self.freq_high}Hz")
        
    def init_multiband_states(self):
        """Initialize multiband filter states"""
        self.low_state_l = signal.sosfilt_zi(self.sos_low)
        self.low_state_r = signal.sosfilt_zi(self.sos_low)
        self.mid_state_l = signal.sosfilt_zi(self.sos_mid)
        self.mid_state_r = signal.sosfilt_zi(self.sos_mid)
        self.high_state_l = signal.sosfilt_zi(self.sos_high)
        self.high_state_r = signal.sosfilt_zi(self.sos_high)
        
    def create_mix_compensation_curve(self):
        """Create compensation curve for crossfade mixing
        Maximum at 50% mix where both signals combine
        """
        x = np.linspace(0, 1, 101)
        # Equal-power crossfade gain sum
        gain_dry = np.cos(x * np.pi / 2)
        gain_wet = np.sin(x * np.pi / 2)
        total_power = np.sqrt(gain_dry**2 + gain_wet**2)
        
        # Compensation is inverse of total power
        compensation = 1.0 / total_power
        # Normalize so endpoints are 1.0
        compensation = compensation / compensation[0]
        
        return compensation
        
    def get_mix_compensation(self, crossfade):
        """Get compensation factor for current crossfade position"""
        idx = int(crossfade * 100)
        idx = np.clip(idx, 0, 100)
        return self.mix_compensation[idx]
        
    def multiband_limit(self, signal_block):
        """Apply frequency-dependent limiting"""
        output = np.zeros_like(signal_block)
        
        for ch in range(2):
            # Split into bands
            if ch == 0:
                low, self.low_state_l = signal.sosfilt(self.sos_low, signal_block[:, ch], 
                                                       zi=self.low_state_l)
                mid, self.mid_state_l = signal.sosfilt(self.sos_mid, signal_block[:, ch], 
                                                       zi=self.mid_state_l)
                high, self.high_state_l = signal.sosfilt(self.sos_high, signal_block[:, ch], 
                                                         zi=self.high_state_l)
            else:
                low, self.low_state_r = signal.sosfilt(self.sos_low, signal_block[:, ch], 
                                                       zi=self.low_state_r)
                mid, self.mid_state_r = signal.sosfilt(self.sos_mid, signal_block[:, ch], 
                                                       zi=self.mid_state_r)
                high, self.high_state_r = signal.sosfilt(self.sos_high, signal_block[:, ch], 
                                                         zi=self.high_state_r)
            
            # Apply different limiting to each band
            # More aggressive on low frequencies
            low_limited = self.soft_limit(low, threshold=0.7)
            mid_limited = self.soft_limit(mid, threshold=0.8)
            high_limited = self.soft_limit(high, threshold=0.9)
            
            # Recombine
            output[:, ch] = low_limited + mid_limited + high_limited
            
        return output
        
    def soft_limit(self, signal, threshold=0.9):
        """Soft limiting with smooth knee"""
        knee_width = 0.1
        
        # Calculate soft knee curve
        over_knee = np.maximum(0, np.abs(signal) - (threshold - knee_width))
        knee_factor = 1 - (over_knee / knee_width)**2
        knee_factor = np.maximum(0, knee_factor)
        
        # Apply limiting
        limited = np.where(
            np.abs(signal) > threshold,
            np.sign(signal) * (threshold + (np.abs(signal) - threshold) * 0.1),
            np.where(
                np.abs(signal) > threshold - knee_width,
                signal * knee_factor + np.sign(signal) * threshold * (1 - knee_factor),
                signal
            )
        )
        
        return limited
        
    def look_ahead_process(self, input_block):
        """Process with look-ahead for predictive limiting"""
        output = np.zeros_like(input_block)
        
        for i in range(len(input_block)):
            # Store in look-ahead buffer
            self.lookahead_buffer[self.lookahead_pos] = input_block[i]
            
            # Get delayed sample
            delayed_pos = (self.lookahead_pos + 1) % self.lookahead_samples
            delayed_sample = self.lookahead_buffer[delayed_pos]
            
            # Calculate peak in look-ahead window
            peak = np.max(np.abs(self.lookahead_buffer))
            
            # Calculate required gain reduction
            if peak > 0.9:
                target_gain = 0.9 / peak
            else:
                target_gain = 1.0
                
            # Smooth gain changes
            self.gain_reduction = (self.gain_reduction * self.gain_smoothing + 
                                  target_gain * (1 - self.gain_smoothing))
            
            # Apply gain
            output[i] = delayed_sample * self.gain_reduction
            
            # Update position
            self.lookahead_pos = (self.lookahead_pos + 1) % self.lookahead_samples
            
        return output
        
    def delay_dry_signal(self, dry_block):
        """Delay dry signal to match FIR"""
        delayed = np.zeros_like(dry_block)
        
        for i in range(len(dry_block)):
            delayed[i] = self.dry_delay_buffer[self.dry_delay_pos]
            self.dry_delay_buffer[self.dry_delay_pos] = dry_block[i]
            self.dry_delay_pos = (self.dry_delay_pos + 1) % self.fir_delay_samples
        
        return delayed
        
    def audio_callback(self, outdata, frames, time, status):
        """Audio callback with adaptive limiting"""
        if status:
            print(f'Audio callback status: {status}')
        
        if self.position + frames > self.total_samples:
            self.position = 0
            self.filter_state_l.fill(0)
            self.filter_state_r.fill(0)
            self.dry_delay_buffer.fill(0)
            self.dry_delay_pos = 0
            self.lookahead_buffer.fill(0)
            self.lookahead_pos = 0
            self.init_multiband_states()
        
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
        
        # Get mix compensation based on crossfade position
        mix_comp = self.get_mix_compensation(self.crossfade)
        
        # Apply compensation to both signals BEFORE mixing
        dry_compensated = dry_block_delayed * mix_comp
        wet_compensated = wet_block * mix_comp
        
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
        mixed = dry_compensated * gain_dry + wet_compensated * gain_wet
        
        # Apply multiband limiting
        limited = self.multiband_limit(mixed)
        
        # Apply look-ahead limiting
        outdata[:] = self.look_ahead_process(limited)
        
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
        print("\n🎵 Adaptive Mix Limiter Active!")
        print("\nControls:")
        print("  1-9 : Crossfade")
        print("  0   : 100% filtered")
        print("  q   : Quit")
        print("\n✨ Intelligent limiting prevents clipping at any mix position\n")
        
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
        
        # Show mix compensation
        mix_comp = self.get_mix_compensation(self.target_crossfade)
        comp_db = 20 * np.log10(mix_comp)
        
        state = f"{percentage:.1f}% (comp: {comp_db:+.1f}dB)"
        
        print(f"\rCrossfade: [{bar}] {state:<35}", end='', flush=True)
        
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
        description='Adaptive mix limiter for clipping-free crossfading'
    )
    
    parser.add_argument('audio_file', help='Audio file')
    parser.add_argument('--taps', type=int, default=4095,
                        help='FIR filter taps (default: 4095)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.audio_file):
        print(f"Error: File '{args.audio_file}' not found")
        sys.exit(1)
    
    try:
        limiter = AdaptiveMixLimiter(
            args.audio_file,
            numtaps=args.taps
        )
        limiter.run()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()