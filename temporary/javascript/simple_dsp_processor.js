/**
 * Simplified DSP Processor for ScriptProcessor compatibility
 */

class SimpleDSPProcessor {
    constructor(sampleRate, options = {}) {
        this.sampleRate = sampleRate;
        this.options = {
            perceptualCompensation: 0.4,
            ...options
        };
        
        // Simple 3-band EQ parameters
        this.bassGain = 1.0;
        this.midGain = 1.0;
        this.trebleGain = 1.0;
        
        // Biquad filter coefficients for 3-band EQ
        this.setupFilters();
        
        // Filter states for each channel
        this.filterStates = {
            left: {
                bass: { x1: 0, x2: 0, y1: 0, y2: 0 },
                treble: { x1: 0, x2: 0, y1: 0, y2: 0 }
            },
            right: {
                bass: { x1: 0, x2: 0, y1: 0, y2: 0 },
                treble: { x1: 0, x2: 0, y1: 0, y2: 0 }
            }
        };
    }
    
    setupFilters() {
        // Low shelf at 200Hz
        const f0 = 200 / this.sampleRate;
        const w0 = 2 * Math.PI * f0;
        const S = 1; // Shelf slope
        const A = Math.sqrt(2);
        
        const cosw0 = Math.cos(w0);
        const sinw0 = Math.sin(w0);
        const alpha = sinw0 / 2 * Math.sqrt((A + 1/A) * (1/S - 1) + 2);
        
        // Low shelf coefficients
        const b0 = A * ((A + 1) - (A - 1) * cosw0 + 2 * Math.sqrt(A) * alpha);
        const b1 = 2 * A * ((A - 1) - (A + 1) * cosw0);
        const b2 = A * ((A + 1) - (A - 1) * cosw0 - 2 * Math.sqrt(A) * alpha);
        const a0 = (A + 1) + (A - 1) * cosw0 + 2 * Math.sqrt(A) * alpha;
        const a1 = -2 * ((A - 1) + (A + 1) * cosw0);
        const a2 = (A + 1) + (A - 1) * cosw0 - 2 * Math.sqrt(A) * alpha;
        
        this.bassCoeffs = {
            b0: b0 / a0,
            b1: b1 / a0,
            b2: b2 / a0,
            a1: a1 / a0,
            a2: a2 / a0
        };
        
        // High shelf at 8000Hz
        const f1 = 8000 / this.sampleRate;
        const w1 = 2 * Math.PI * f1;
        const cosw1 = Math.cos(w1);
        const sinw1 = Math.sin(w1);
        const alpha1 = sinw1 / 2 * Math.sqrt((A + 1/A) * (1/S - 1) + 2);
        
        // High shelf coefficients
        const hb0 = A * ((A + 1) + (A - 1) * cosw1 + 2 * Math.sqrt(A) * alpha1);
        const hb1 = -2 * A * ((A - 1) + (A + 1) * cosw1);
        const hb2 = A * ((A + 1) + (A - 1) * cosw1 - 2 * Math.sqrt(A) * alpha1);
        const ha0 = (A + 1) - (A - 1) * cosw1 + 2 * Math.sqrt(A) * alpha1;
        const ha1 = 2 * ((A - 1) - (A + 1) * cosw1);
        const ha2 = (A + 1) - (A - 1) * cosw1 - 2 * Math.sqrt(A) * alpha1;
        
        this.trebleCoeffs = {
            b0: hb0 / ha0,
            b1: hb1 / ha0,
            b2: hb2 / ha0,
            a1: ha1 / ha0,
            a2: ha2 / ha0
        };
    }
    
    updateEnvironment(noiseFloor, playbackLevel) {
        // Simple loudness compensation
        const phonDiff = playbackLevel - 60; // Reference to 60 phon
        
        // Apply perceptual compensation
        const compensation = this.options.perceptualCompensation;
        
        // Calculate gains (simplified)
        if (phonDiff < -10) {
            // Quiet playback - boost bass and treble
            this.bassGain = 1 + (Math.abs(phonDiff) / 20) * compensation;
            this.trebleGain = 1 + (Math.abs(phonDiff) / 40) * compensation;
            this.midGain = 1.0;
        } else if (phonDiff > 10) {
            // Loud playback - reduce bass slightly
            this.bassGain = 1 - (phonDiff / 40) * compensation * 0.5;
            this.trebleGain = 1.0;
            this.midGain = 1.0;
        } else {
            // Normal range
            this.bassGain = 1.0;
            this.midGain = 1.0;
            this.trebleGain = 1.0;
        }
        
        // Limit gains
        this.bassGain = Math.max(0.5, Math.min(2.0, this.bassGain));
        this.midGain = Math.max(0.5, Math.min(2.0, this.midGain));
        this.trebleGain = Math.max(0.5, Math.min(2.0, this.trebleGain));
    }
    
    processSample(input, state, coeffs, gain) {
        // Biquad filter processing
        const output = coeffs.b0 * input + coeffs.b1 * state.x1 + coeffs.b2 * state.x2
                     - coeffs.a1 * state.y1 - coeffs.a2 * state.y2;
        
        // Update state
        state.x2 = state.x1;
        state.x1 = input;
        state.y2 = state.y1;
        state.y1 = output;
        
        // Apply gain and mix with dry signal
        return input + (output - input) * (gain - 1);
    }
    
    processChannel(inputArray, outputArray, channelState) {
        for (let i = 0; i < inputArray.length; i++) {
            let sample = inputArray[i];
            
            // Apply bass shelf
            sample = this.processSample(sample, channelState.bass, this.bassCoeffs, this.bassGain);
            
            // Apply treble shelf
            sample = this.processSample(sample, channelState.treble, this.trebleCoeffs, this.trebleGain);
            
            // Apply mid gain (simple multiplication)
            sample *= this.midGain;
            
            // Soft clipping to prevent distortion
            if (Math.abs(sample) > 0.95) {
                sample = Math.sign(sample) * (0.95 + 0.05 * Math.tanh((Math.abs(sample) - 0.95) * 10));
            }
            
            outputArray[i] = sample;
        }
    }
    
    getDebugInfo() {
        return {
            bassGain: this.bassGain.toFixed(2),
            midGain: this.midGain.toFixed(2),
            trebleGain: this.trebleGain.toFixed(2),
            perceptualCompensation: this.options.perceptualCompensation
        };
    }
}