// Complete tidal.js implementation with all required functions

// Linear interpolation function
function interp(xi, x, y) {
    const yi = new Float32Array(xi.length);
    
    for (let i = 0; i < xi.length; i++) {
        const xVal = xi[i];
        
        // Find the interval containing xVal
        let j = 0;
        while (j < x.length - 1 && x[j + 1] < xVal) j++;
        
        if (j === x.length - 1) {
            yi[i] = y[y.length - 1];
        } else {
            const x0 = x[j];
            const x1 = x[j + 1];
            const y0 = y[j];
            const y1 = y[j + 1];
            
            // Linear interpolation
            const t = (xVal - x0) / (x1 - x0);
            yi[i] = y0 * (1 - t) + y1 * t;
        }
    }
    
    return yi;
}

// Window function generator
function getWindow(windowType, length) {
    const window = new Float32Array(length);
    
    switch (windowType.toLowerCase()) {
        case 'hann':
        case 'hanning':
            for (let i = 0; i < length; i++) {
                window[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (length - 1));
            }
            break;
            
        case 'hamming':
            for (let i = 0; i < length; i++) {
                window[i] = 0.54 - 0.46 * Math.cos(2 * Math.PI * i / (length - 1));
            }
            break;
            
        case 'blackman':
            for (let i = 0; i < length; i++) {
                const a0 = 0.42;
                const a1 = 0.5;
                const a2 = 0.08;
                window[i] = a0 - a1 * Math.cos(2 * Math.PI * i / (length - 1)) + 
                           a2 * Math.cos(4 * Math.PI * i / (length - 1));
            }
            break;
            
        case 'kaiser':
            // Simplified Kaiser window (beta = 8.6)
            const beta = 8.6;
            const alpha = (length - 1) / 2;
            for (let i = 0; i < length; i++) {
                const x = (i - alpha) / alpha;
                window[i] = besseli0(beta * Math.sqrt(1 - x * x)) / besseli0(beta);
            }
            break;
            
        default:
            // Rectangular window
            window.fill(1);
    }
    
    return window;
}

// Modified Bessel function of the first kind, order 0 (for Kaiser window)
function besseli0(x) {
    let sum = 1.0;
    let term = 1.0;
    let k = 1;
    
    while (Math.abs(term) > 1e-10) {
        term *= (x / (2 * k)) * (x / (2 * k));
        sum += term;
        k++;
    }
    
    return sum;
}

// IRFFT implementation (Inverse Real FFT)
function irfft(fx2) {
    const n = (fx2.length - 1) * 2;
    const result = new Float32Array(n);
    
    // Reconstruct the full complex spectrum from the positive frequencies
    const fullSpectrum = new Float32Array(n * 2); // Real and imaginary parts interleaved
    
    // Copy positive frequencies
    for (let i = 0; i < fx2.length; i++) {
        fullSpectrum[i * 2] = fx2[i].real || fx2[i];
        fullSpectrum[i * 2 + 1] = fx2[i].imag || 0;
    }
    
    // Mirror negative frequencies (conjugate symmetry)
    for (let i = 1; i < fx2.length - 1; i++) {
        const idx = n - i;
        fullSpectrum[idx * 2] = fullSpectrum[i * 2]; // Real part stays the same
        fullSpectrum[idx * 2 + 1] = -fullSpectrum[i * 2 + 1]; // Imaginary part negated
    }
    
    // Perform IFFT using DFT formula
    for (let k = 0; k < n; k++) {
        let real = 0;
        for (let j = 0; j < n; j++) {
            const angle = 2 * Math.PI * j * k / n;
            real += fullSpectrum[j * 2] * Math.cos(angle) - fullSpectrum[j * 2 + 1] * Math.sin(angle);
        }
        result[k] = real / n;
    }
    
    return result;
}

// FIR filter design using the window method (firwin2)
function firwin2(numtaps, freq, gain, options = {}) {
    const { window = 'hamming', fs = 2 } = options;
    const nyq = 0.5 * fs;
    
    // Normalize frequencies to [0, 1] where 1 is Nyquist
    const freqNorm = freq.map(f => f / nyq);
    
    // Check inputs
    if (freq.length !== gain.length) {
        throw new Error('freq and gain must be of same length');
    }
    
    if (freqNorm[0] !== 0 || Math.abs(freqNorm[freqNorm.length - 1] - 1) > 0.001) {
        throw new Error('freq must start with 0 and end with fs/2');
    }
    
    // For even-length filters, force gain at Nyquist to 0
    const ftype = numtaps % 2 === 0 ? 2 : 1;
    if (ftype === 2 && gain[gain.length - 1] !== 0) {
        gain = gain.slice();
        gain[gain.length - 1] = 0;
    }
    
    // Determine nfreqs (power of 2 + 1, larger than numtaps)
    const nfreqs = 1 + Math.pow(2, Math.ceil(Math.log2(numtaps)));
    
    // Create uniform frequency grid from 0 to Nyquist
    const x = new Float32Array(nfreqs);
    for (let i = 0; i < nfreqs; i++) {
        x[i] = i / (nfreqs - 1);  // 0 to 1
    }
    
    // Linearly interpolate the desired magnitude response
    const fx = interp(x, freqNorm, gain);
    
    // Create complex array with linear phase shift
    const fx2 = new Array(nfreqs);
    for (let i = 0; i < nfreqs; i++) {
        const phase = -(numtaps - 1) / 2 * Math.PI * x[i];
        fx2[i] = {
            real: fx[i] * Math.cos(phase),
            imag: fx[i] * Math.sin(phase)
        };
    }
    
    // Use inverse real FFT to get time domain coefficients
    const out_full = irfft(fx2);
    
    // Apply window
    const wind = getWindow(window, numtaps);
    
    // Keep only the first numtaps coefficients and multiply by window
    const out = new Float32Array(numtaps);
    for (let i = 0; i < numtaps; i++) {
        out[i] = out_full[i] * wind[i];
    }
    
    return out;
}

// Export functions if in module context
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        firwin2,
        interp,
        getWindow,
        irfft
    };
}