/**
 * Adaptive Loudness Processor - Standalone Version
 * No dependency on AudioWorkletProcessor (for broader compatibility)
 */

// ISO 226:2003 데이터 (20Hz - 20kHz)
const ISO_FREQ = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000
];

const ISO_CURVES = {
    20: [74.3, 64.4, 56.3, 49.5, 44.7, 40.6, 37.5, 35.0, 33.1, 31.6, 30.2, 28.9, 27.7, 26.6, 25.6,
        24.7, 23.8, 22.5, 21.2, 20.3, 19.1, 18.1, 17.2, 16.3, 15.0, 13.4, 11.5, 10.4, 10.1, 11.2, 13.4],
    30: [86.3, 75.3, 66.2, 58.4, 52.7, 48.0, 44.4, 41.3, 39.2, 37.3, 35.7, 34.2, 32.9, 31.7, 30.6,
        29.5, 28.4, 27.1, 25.8, 24.7, 23.3, 22.1, 21.0, 19.9, 18.2, 16.1, 14.6, 13.6, 13.3, 14.6, 17.1],
    40: [96.9, 85.4, 76.3, 68.3, 62.1, 57.0, 52.5, 48.7, 46.2, 44.0, 42.1, 40.4, 38.9, 37.5, 36.3,
        35.1, 33.9, 32.6, 31.2, 29.9, 28.4, 27.1, 25.9, 24.7, 22.9, 20.7, 19.0, 17.8, 17.3, 18.6, 21.4],
    50: [107.6, 95.6, 86.4, 78.3, 71.1, 65.0, 60.1, 56.1, 53.4, 51.0, 48.9, 47.1, 45.4, 43.8, 42.3,
        40.9, 39.4, 38.1, 36.6, 35.1, 33.4, 32.0, 30.6, 29.2, 27.4, 25.1, 23.4, 22.1, 21.6, 22.8, 25.8],
    60: [118.6, 106.1, 96.8, 88.4, 81.3, 75.0, 69.2, 65.1, 62.2, 59.6, 57.3, 55.3, 53.5, 51.7, 50.1,
        48.6, 47.0, 45.6, 44.0, 42.3, 40.5, 38.9, 37.3, 35.6, 33.7, 31.3, 29.6, 28.3, 27.9, 29.1, 32.3],
    70: [129.5, 116.9, 107.1, 98.3, 91.2, 84.7, 78.5, 74.2, 71.1, 68.2, 65.7, 63.5, 61.5, 59.6, 57.9,
        56.2, 54.5, 53.0, 51.3, 49.5, 47.6, 45.8, 44.1, 42.3, 40.1, 37.7, 35.9, 34.6, 34.3, 35.4, 38.7],
    80: [139.9, 127.3, 117.5, 108.6, 101.4, 94.8, 88.4, 83.9, 80.7, 77.6, 74.9, 72.6, 70.4, 68.3, 66.4,
        64.6, 62.8, 61.1, 59.3, 57.4, 55.3, 53.4, 51.4, 49.5, 47.2, 44.8, 43.0, 41.7, 41.2, 42.2, 45.6],
    90: [150.2, 137.5, 127.7, 118.7, 111.4, 104.8, 98.4, 93.8, 90.4, 87.1, 84.2, 81.7, 79.4, 77.1, 75.1,
        73.3, 71.4, 69.6, 67.6, 65.6, 63.5, 61.5, 59.5, 57.4, 55.1, 52.7, 50.8, 49.4, 48.8, 49.8, 53.2],
    100: [160.4, 147.6, 137.8, 128.8, 121.4, 114.8, 108.3, 103.7, 100.3, 96.9, 93.9, 91.4, 88.9, 86.6, 84.5,
        82.5, 80.5, 78.6, 76.6, 74.5, 72.4, 70.3, 68.3, 66.2, 63.9, 61.4, 59.5, 58.1, 57.5, 58.5, 62.0]
};

class AdaptiveLoudnessProcessor {
    constructor(sampleRate = 48000, options = {}) {
        this.sampleRate = sampleRate;
        this.options = {
            taps: 513,
            window: 'hann',
            perceptualCompensation: 0.4,
            smoothingFactor: 0.98,
            adaptiveTimeConstant: 300,
            enableAdaptive: true,
            ...options
        };
        
        // Current state
        this.currentTargetPhon = 40;
        this.currentReferencePhon = 60;
        this.listeningStartTime = Date.now();
        
        // FIR filter coefficients cache
        this.currentCoeffs = null;
        this.targetCoeffs = null;
        this.coeffsCache = new Map();
        
        // Delay buffers for each channel
        this.delayBuffers = [];
        
        // Initialize filter
        this.updateFilter(this.currentTargetPhon, this.currentReferencePhon);
    }
    
    /**
     * Interpolate ISO 226 curves
     */
    interpolateISO(phon) {
        const keys = Object.keys(ISO_CURVES).map(Number).sort((a, b) => a - b);
        
        if (ISO_CURVES[phon]) {
            return ISO_CURVES[phon];
        }
        
        phon = Math.max(keys[0], Math.min(keys[keys.length - 1], phon));
        
        let lo = keys[0];
        let hi = keys[keys.length - 1];
        
        for (let i = 0; i < keys.length - 1; i++) {
            if (keys[i] <= phon && keys[i + 1] >= phon) {
                lo = keys[i];
                hi = keys[i + 1];
                break;
            }
        }
        
        const w = (phon - lo) / (hi - lo);
        const result = [];
        
        for (let i = 0; i < ISO_CURVES[lo].length; i++) {
            result[i] = ISO_CURVES[lo][i] * (1 - w) + ISO_CURVES[hi][i] * w;
        }
        
        return result;
    }
    
    /**
     * Calculate frequency-dependent gain (with perceptual compensation)
     */
    calculateGain(targetPhon, referencePhon) {
        const targetCurve = this.interpolateISO(targetPhon);
        const referenceCurve = this.interpolateISO(referencePhon);
        
        const gainDB = [];
        const idx1kHz = ISO_FREQ.indexOf(1000);
        
        for (let i = 0; i < targetCurve.length; i++) {
            let delta = referenceCurve[i] - targetCurve[i];
            gainDB[i] = delta;
        }
        
        // Normalize to 1kHz
        const ref1kHz = gainDB[idx1kHz];
        for (let i = 0; i < gainDB.length; i++) {
            gainDB[i] -= ref1kHz;
        }
        
        // Apply perceptual compensation
        const adaptiveFactor = this.getAdaptiveFactor();
        const compensation = this.options.perceptualCompensation * adaptiveFactor;
        
        for (let i = 0; i < gainDB.length; i++) {
            gainDB[i] *= compensation;
        }
        
        return gainDB;
    }
    
    /**
     * Time-adaptive factor
     */
    getAdaptiveFactor() {
        if (!this.options.enableAdaptive) {
            return 1.0;
        }
        
        const elapsedSeconds = (Date.now() - this.listeningStartTime) / 1000;
        const minutes = elapsedSeconds / 60;
        
        const factor = 1.0 - 0.6 * Math.tanh(minutes / 10);
        return Math.max(0.4, Math.min(1.0, factor));
    }
    
    /**
     * Design FIR filter
     */
    designFIR(targetPhon, referencePhon) {
        const cacheKey = `${targetPhon.toFixed(1)}_${referencePhon.toFixed(1)}`;
        
        if (this.coeffsCache.has(cacheKey)) {
            return this.coeffsCache.get(cacheKey);
        }
        
        const gainDB = this.calculateGain(targetPhon, referencePhon);
        const gainLinear = gainDB.map(db => Math.pow(10, db / 20));
        
        // Filter frequencies up to Nyquist
        const nyq = this.sampleRate / 2;
        const freqFiltered = [0];
        const gainFiltered = [gainLinear[0]];
        
        for (let i = 0; i < ISO_FREQ.length; i++) {
            if (ISO_FREQ[i] < nyq) {
                freqFiltered.push(ISO_FREQ[i]);
                gainFiltered.push(gainLinear[i]);
            }
        }
        
        // Add Nyquist frequency
        freqFiltered.push(nyq);
        gainFiltered.push(gainLinear[gainLinear.length - 1]);
        
        // Call firwin2 (must be loaded from tidal.js)
        const coeffs = firwin2(this.options.taps, freqFiltered, gainFiltered, {
            window: this.options.window,
            fs: this.sampleRate
        });
        
        // Cache result
        if (this.coeffsCache.size > 100) {
            const firstKey = this.coeffsCache.keys().next().value;
            this.coeffsCache.delete(firstKey);
        }
        this.coeffsCache.set(cacheKey, coeffs);
        
        return coeffs;
    }
    
    /**
     * Update filter coefficients
     */
    updateFilter(targetPhon, referencePhon) {
        this.targetCoeffs = this.designFIR(targetPhon, referencePhon);
        
        if (!this.currentCoeffs) {
            this.currentCoeffs = new Float32Array(this.targetCoeffs);
        }
    }
    
    /**
     * Update environment parameters
     */
    updateEnvironment(noiseFloorDB, playbackLevelDB) {
        const newTargetPhon = playbackLevelDB;
        const newReferencePhon = playbackLevelDB + 5;
        
        if (Math.abs(newTargetPhon - this.currentTargetPhon) > 0.5) {
            this.currentTargetPhon = newTargetPhon;
            this.currentReferencePhon = newReferencePhon;
            this.updateFilter(newTargetPhon, newReferencePhon);
        }
    }
    
    /**
     * Process audio buffer
     */
    processBuffer(inputBuffer, outputBuffer) {
        const numChannels = inputBuffer.numberOfChannels;
        const numSamples = inputBuffer.length;
        
        // Initialize delay buffers if needed
        while (this.delayBuffers.length < numChannels) {
            this.delayBuffers.push(new Float32Array(this.options.taps));
        }
        
        // Smooth filter transition
        this.smoothTransition();
        
        // Process each channel
        for (let ch = 0; ch < numChannels; ch++) {
            const input = inputBuffer.getChannelData(ch);
            const output = outputBuffer.getChannelData(ch);
            const delayBuffer = this.delayBuffers[ch];
            
            // Apply FIR filter
            this.applyFIR(input, output, numSamples, delayBuffer);
        }
    }
    
    /**
     * Apply FIR filtering
     */
    applyFIR(input, output, numSamples, delayBuffer) {
        const coeffs = this.currentCoeffs;
        const taps = coeffs.length;
        
        for (let n = 0; n < numSamples; n++) {
            let sum = 0;
            
            // Convolution
            for (let k = 0; k < taps; k++) {
                const idx = n - k;
                if (idx >= 0) {
                    sum += input[idx] * coeffs[k];
                } else {
                    sum += delayBuffer[taps + idx] * coeffs[k];
                }
            }
            
            output[n] = sum;
        }
        
        // Update delay buffer
        const copyStart = Math.max(0, numSamples - taps);
        const copyLength = Math.min(taps, numSamples);
        
        // Shift old samples
        for (let i = 0; i < taps - copyLength; i++) {
            delayBuffer[i] = delayBuffer[i + copyLength];
        }
        
        // Copy new samples
        for (let i = 0; i < copyLength; i++) {
            delayBuffer[taps - copyLength + i] = input[copyStart + i];
        }
    }
    
    /**
     * Smooth filter transition
     */
    smoothTransition() {
        if (!this.targetCoeffs) return;
        
        const smooth = this.options.smoothingFactor;
        
        for (let i = 0; i < this.currentCoeffs.length; i++) {
            this.currentCoeffs[i] = this.currentCoeffs[i] * smooth + 
                                   this.targetCoeffs[i] * (1 - smooth);
        }
    }
    
    /**
     * Get debug information
     */
    getDebugInfo() {
        return {
            currentPhon: this.currentTargetPhon,
            referencePhon: this.currentReferencePhon,
            adaptiveFactor: this.getAdaptiveFactor(),
            perceptualCompensation: this.options.perceptualCompensation,
            effectiveCompensation: this.options.perceptualCompensation * this.getAdaptiveFactor(),
            listeningMinutes: (Date.now() - this.listeningStartTime) / 60000
        };
    }
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AdaptiveLoudnessProcessor };
}