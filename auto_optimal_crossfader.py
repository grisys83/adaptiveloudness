#!/usr/bin/env python3
"""
Auto-Optimal Crossfader
- Automatically finds the optimal gain reduction
- Analyzes actual peak levels at different mix ratios
- Adapts to content characteristics
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

class AutoOptimalCrossfader:
    def __init__(self, audio_file, target_phon=60, reference_phon=80,
                 blocksize=4096, numtaps=4095, analysis_duration=30.0):
        """
        Initialize with automatic optimal gain detection
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
        
        print(f"\nAuto-Optimal Crossfader Configuration:")
        print(f"  FIR taps: {numtaps}")
        print(f"  FIR delay: {self.fir_delay_ms:.1f} ms")
        
        # Design FIR filter
        print(f"\nDesigning filter ({target_phon}→{reference_phon} phon)...")
        self.fir_coeffs, _ = design_fir(target_phon, reference_phon, numtaps, self.fs)
        
        # Calculate level correction
        self.correction_db, _ = calculate_rms_spl_change(self.fir_coeffs, self.fs)
        self.correction_linear = 10 ** (self.correction_db / 20)
        print(f"  Level correction: {self.correction_db:+.2f} dB")
        
        # Analyze audio to find optimal reduction
        print(f"\nAnalyzing audio for optimal gain reduction...")
        self.optimal_reduction_db = self.analyze_optimal_reduction(analysis_duration)
        
        # Create adaptive gain curve
        self.create_adaptive_gain_curve()
        
        # Initialize buffers
        self.dry_delay_buffer = np.zeros((self.fir_delay_samples, 2))
        self.dry_delay_pos = 0
        
        self.filter_state_l = np.zeros(numtaps - 1)
        self.filter_state_r = np.zeros(numtaps - 1)
        
        # Dynamic analysis buffers
        self.peak_history = np.zeros(100)  # Track recent peaks
        self.peak_pos = 0
        self.dynamic_adjustment = 0.0
        
        self.position = 0
        self.total_samples = len(self.audio)
        self.crossfade = 0.0
        self.target_crossfade = 0.0
        self.fade_samples = int(0.05 * self.fs)
        
        self.playing = False
        
    def analyze_optimal_reduction(self, duration_sec):
        """
        Analyze audio to find optimal gain reduction
        """
        # Limit analysis duration
        analysis_samples = min(int(duration_sec * self.fs), len(self.audio))
        analysis_audio = self.audio[:analysis_samples]
        
        print(f"  Analyzing {analysis_samples/self.fs:.1f} seconds of audio...")
        
        # Process audio through FIR filter
        wet_l = signal.lfilter(self.fir_coeffs, 1.0, analysis_audio[:, 0])
        wet_r = signal.lfilter(self.fir_coeffs, 1.0, analysis_audio[:, 1])
        wet = np.column_stack([wet_l, wet_r]) * self.correction_linear
        
        # Align dry signal (simple delay)
        dry = np.zeros_like(analysis_audio)
        delay = self.fir_delay_samples
        dry[delay:] = analysis_audio[:-delay]
        
        # Test different mix ratios
        mix_ratios = [0.3, 0.4, 0.5, 0.6, 0.7]  # Focus on problematic middle range
        peak_levels = []
        rms_levels = []
        
        for ratio in mix_ratios:
            # Equal-power mix
            angle = ratio * np.pi / 2
            gain_dry = np.cos(angle)
            gain_wet = np.sin(angle)
            
            mixed = dry * gain_dry + wet * gain_wet
            
            # Measure peak and RMS
            peak = np.max(np.abs(mixed))
            rms = np.sqrt(np.mean(mixed**2))
            
            peak_levels.append(peak)
            rms_levels.append(rms)
            
            print(f"    Mix {ratio*100:.0f}%: peak={peak:.3f}, RMS={rms:.3f}")
        
        # Find worst case peak
        max_peak = max(peak_levels)
        max_peak_idx = peak_levels.index(max_peak)
        worst_ratio = mix_ratios[max_peak_idx]
        
        # Calculate required reduction for 95% headroom
        target_peak = 0.95
        required_reduction_linear = target_peak / max_peak
        required_reduction_db = 20 * np.log10(required_reduction_linear)
        
        # Add safety margin
        safety_margin_db = -0.5
        optimal_reduction_db = required_reduction_db + safety_margin_db
        
        # Analyze frequency content for adaptive adjustment
        self.analyze_frequency_content(dry, wet)
        
        print(f"\n  Analysis results:")
        print(f"    Worst case at {worst_ratio*100:.0f}% mix")
        print(f"    Maximum peak: {max_peak:.3f}")
        print(f"    Required reduction: {required_reduction_db:.2f} dB")
        print(f"    With safety margin: {optimal_reduction_db:.2f} dB")
        
        return optimal_reduction_db
        
    def analyze_frequency_content(self, dry, wet):
        """
        Analyze frequency content to adjust curve shape
        """
        # Simple frequency analysis
        fft_size = 4096
        
        # Take multiple FFT windows
        num_windows = min(10, len(dry) // fft_size)
        bass_energy_dry = 0
        bass_energy_wet = 0
        
        for i in range(num_windows):
            start = i * fft_size
            end = start + fft_size
            
            # FFT of both signals
            fft_dry = np.fft.rfft(dry[start:end, 0])
            fft_wet = np.fft.rfft(wet[start:end, 0])
            
            # Calculate bass energy (< 200 Hz)
            freq_bins = np.fft.rfftfreq(fft_size, 1/self.fs)
            bass_mask = freq_bins < 200
            
            bass_energy_dry += np.sum(np.abs(fft_dry[bass_mask])**2)
            bass_energy_wet += np.sum(np.abs(fft_wet[bass_mask])**2)
        
        # Calculate bass ratio
        total_energy_dry = np.sum(dry**2)
        total_energy_wet = np.sum(wet**2)
        
        self.bass_ratio_dry = bass_energy_dry / (total_energy_dry + 1e-10)
        self.bass_ratio_wet = bass_energy_wet / (total_energy_wet + 1e-10)
        self.bass_ratio_avg = (self.bass_ratio_dry + self.bass_ratio_wet) / 2
        
        print(f"    Bass content ratio: {self.bass_ratio_avg:.1%}")
        
    def create_adaptive_gain_curve(self):
        """
        Create gain curve adapted to content
        """
        x = np.linspace(0, 1, 101)
        
        # Base parabolic curve
        base_curve = 4 * x * (1 - x)
        
        # Adjust curve shape based on bass content
        # More bass = sharper curve (more reduction needed)
        sharpness = 1.0 + self.bass_ratio_avg
        adaptive_curve = base_curve ** sharpness
        
        # Apply optimal reduction
        self.gain_reduction_curve = self.optimal_reduction_db * adaptive_curve
        
        # Convert to linear
        self.gain_curve_linear = 10 ** (self.gain_reduction_curve / 20)
        
        print(f"\nAdaptive gain curve created:")
        print(f"  At 0%: {self.gain_reduction_curve[0]:.1f} dB")
        print(f"  At 25%: {self.gain_reduction_curve[25]:.1f} dB")
        print(f"  At 50%: {self.gain_reduction_curve[50]:.1f} dB")
        print(f"  At 75%: {self.gain_reduction_curve[75]:.1f} dB")
        print(f"  At 100%: {self.gain_reduction_curve[100]:.1f} dB")
        
    def update_dynamic_adjustment(self, mixed_block):
        """
        Dynamic real-time adjustment based on current content
        """
        # Measure current peak
        current_peak = np.max(np.abs(mixed_block))
        
        # Update peak history
        self.peak_history[self.peak_pos] = current_peak
        self.peak_pos = (self.peak_pos + 1) % len(self.peak_history)
        
        # Calculate recent peak trend
        recent_peak = np.percentile(self.peak_history, 95)
        
        # Adjust if getting too hot
        if recent_peak > 0.90:
            # Need more reduction
            self.dynamic_adjustment = max(self.dynamic_adjustment - 0.01, -3.0)
        elif recent_peak < 0.80:
            # Can reduce less
            self.dynamic_adjustment = min(self.dynamic_adjustment + 0.01, 0.0)
        
        return 10 ** (self.dynamic_adjustment / 20)
        
    def get_gain_compensation(self, crossfade):
        """Get gain compensation with dynamic adjustment"""
        idx = int(crossfade * 100)
        idx = np.clip(idx, 0, 100)
        
        static_gain = self.gain_curve_linear[idx]
        dynamic_factor = 10 ** (self.dynamic_adjustment / 20)
        
        return static_gain * dynamic_factor
        
    def delay_dry_signal(self, dry_block):
        """Delay dry signal to match FIR"""
        delayed = np.zeros_like(dry_block)
        
        for i in range(len(dry_block)):
            delayed[i] = self.dry_delay_buffer[self.dry_delay_pos]
            self.dry_delay_buffer[self.dry_delay_pos] = dry_block[i]
            self.dry_delay_pos = (self.dry_delay_pos + 1) % self.fir_delay_samples
        
        return delayed
        
    def audio_callback(self, outdata, frames, time, status):
        """Audio callback with automatic optimal gain"""
        if status:
            print(f'Audio callback status: {status}')
        
        if self.position + frames > self.total_samples:
            self.position = 0
            self.filter_state_l.fill(0)
            self.filter_state_r.fill(0)
            self.dry_delay_buffer.fill(0)
            self.dry_delay_pos = 0
            self.peak_history.fill(0)
            self.dynamic_adjustment = 0.0
        
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
        
        # Update dynamic adjustment
        self.update_dynamic_adjustment(mixed)
        
        # Apply gain compensation
        gain_comp = self.get_gain_compensation(self.crossfade)
        outdata[:] = mixed * gain_comp
        
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
        print("\n🎵 Auto-Optimal Crossfader Active!")
        print("\nControls:")
        print("  1-9 : Crossfade")
        print("  0   : 100% filtered")
        print("  d   : Show dynamic adjustment")
        print("  q   : Quit")
        print(f"\n✨ Automatic optimal reduction: {self.optimal_reduction_db:.1f}dB at 50% mix")
        print("   + Dynamic real-time adjustment\n")
        
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
        
        # Get current gain
        gain_comp = self.get_gain_compensation(self.target_crossfade)
        gain_db = 20 * np.log10(gain_comp)
        
        state = f"{percentage:3.0f}% (gain: {gain_db:+.1f}dB)"
        
        print(f"\rCrossfade: [{bar}] {state:<25}", end='', flush=True)
        
    def show_dynamic_info(self):
        """Show dynamic adjustment info"""
        recent_peak = np.percentile(self.peak_history, 95)
        print(f"\n\nDynamic Info:")
        print(f"  Recent peak level: {recent_peak:.3f}")
        print(f"  Dynamic adjustment: {self.dynamic_adjustment:.2f} dB")
        print(f"  Bass content: {self.bass_ratio_avg:.1%}")
        print(f"  Optimal reduction: {self.optimal_reduction_db:.2f} dB\n")
        
    def on_key_press(self, key):
        try:
            if hasattr(key, 'char'):
                if key.char == 'q':
                    self.stop()
                    return False
                elif key.char == 'd':
                    self.show_dynamic_info()
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
        description='Automatic optimal gain crossfader'
    )
    
    parser.add_argument('audio_file', help='Audio file')
    parser.add_argument('--analysis-duration', type=float, default=30.0,
                        help='Duration to analyze in seconds (default: 30)')
    parser.add_argument('--taps', type=int, default=4095,
                        help='FIR filter taps (default: 4095)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.audio_file):
        print(f"Error: File '{args.audio_file}' not found")
        sys.exit(1)
    
    try:
        crossfader = AutoOptimalCrossfader(
            args.audio_file,
            numtaps=args.taps,
            analysis_duration=args.analysis_duration
        )
        crossfader.run()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()