/**
 * AudioWorklet 프로세서를 위한 최소화된 버전
 * Web Worker 환경에서 실행됨
 */

// tidal.js의 필수 함수들을 포함
function firwin2(numtaps, freq, gain, options = {}) {
    const { window = 'hamming', fs = 2 } = options;
    const nyq = 0.5 * fs;
    
    const freqNorm = freq.map(f => f / nyq);
    
    if (freq.length !== gain.length) {
        throw new Error('freq and gain must be of same length');
    }
    
    const ftype = numtaps % 2 === 0 ? 2 : 1;
    if (ftype === 2 && gain[gain.length - 1] !== 0) {
        gain = gain.slice();
        gain[gain.length - 1] = 0;
    }
    
    const nfreqs = 1 + Math.pow(2, Math.ceil(Math.log2(numtaps)));
    
    const x = new Float32Array(nfreqs);
    for (let i = 0; i < nfreqs; i++) {
        x[i] = i / (nfreqs - 1);
    }
    
    const fx = interp(x, freqNorm, gain);
    
    const fx2 = new Array(nfreqs);
    for (let i = 0; i < nfreqs; i++) {
        const phase = -(numtaps - 1) / 2 * Math.PI * x[i];
        fx2[i] = {
            real: fx[i] * Math.cos(phase),
            imag: fx[i] * Math.sin(phase)
        };
    }
    
    const out_full = irfft(fx2);
    const wind = getWindow(window, numtaps);
    
    const out = new Float32Array(numtaps);
    for (let i = 0; i < numtaps; i++) {
        out[i] = out_full[i] * wind[i];
    }
    
    return out;
}

function interp(xi, x, y) {
    const yi = new Float32Array(xi.length);
    
    for (let i = 0; i < xi.length; i++) {
        const xVal = xi[i];
        
        let j = 0;
        while (j < x.length - 1 && x[j + 1] < xVal) j++;
        
        if (j === x.length - 1) {
            yi[i] = y[y.length - 1];
        } else {
            const x0 = x[j];
            const x1 = x[j + 1];
            const y0 = y[j];
            const y1 = y[j + 1];
            
            const t = (xVal - x0) / (x1 - x0);
            yi[i] = y0 * (1 - t) + y1 * t;
        }
    }
    
    return yi;
}

function irfft(fx2) {
    const n = (fx2.length - 1) * 2;
    const result = new Float32Array(n);
    
    const fullSpectrum = new Float32Array(n * 2);
    
    for (let i = 0; i < fx2.length; i++) {
        fullSpectrum[i * 2] = fx2[i].real || fx2[i];
        fullSpectrum[i * 2 + 1] = fx2[i].imag || 0;
    }
    
    for (let i = 1; i < fx2.length - 1; i++) {
        const idx = n - i;
        fullSpectrum[idx * 2] = fullSpectrum[i * 2];
        fullSpectrum[idx * 2 + 1] = -fullSpectrum[i * 2 + 1];
    }
    
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

function getWindow(windowType, length) {
    const window = new Float32Array(length);
    
    switch (windowType) {
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
        default:
            window.fill(1);
    }
    
    return window;
}

// 간소화된 프로세서 (AudioWorklet 환경)
class AdaptiveLoudnessWorkletProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        
        // 기본 설정
        this.taps = 513;
        this.coeffs = new Float32Array(this.taps);
        this.delayBuffers = [];
        this.perceptualCompensation = 0.4;
        
        // 초기 필터 (플랫)
        this.coeffs[Math.floor(this.taps / 2)] = 1.0;
        
        // 메시지 핸들러
        this.port.onmessage = (event) => {
            if (event.data.type === 'updateFilter') {
                this.coeffs = new Float32Array(event.data.coeffs);
            } else if (event.data.type === 'updateParameters') {
                if (event.data.perceptualCompensation !== undefined) {
                    this.perceptualCompensation = event.data.perceptualCompensation;
                }
            }
        };
    }
    
    process(inputs, outputs, parameters) {
        const input = inputs[0];
        const output = outputs[0];
        
        if (!input || !output || input.length === 0) return true;
        
        // 채널별 지연 버퍼 초기화
        while (this.delayBuffers.length < input.length) {
            this.delayBuffers.push(new Float32Array(this.taps));
        }
        
        // 각 채널 처리
        for (let channel = 0; channel < input.length; channel++) {
            const inputChannel = input[channel];
            const outputChannel = output[channel];
            const delayBuffer = this.delayBuffers[channel];
            
            // FIR 필터 적용
            for (let n = 0; n < inputChannel.length; n++) {
                let sum = 0;
                
                // 컨볼루션
                for (let k = 0; k < this.taps; k++) {
                    const idx = n - k;
                    if (idx >= 0) {
                        sum += inputChannel[idx] * this.coeffs[k];
                    } else {
                        sum += delayBuffer[this.taps + idx] * this.coeffs[k];
                    }
                }
                
                outputChannel[n] = sum;
            }
            
            // 지연 버퍼 업데이트
            const copyLength = Math.min(this.taps, inputChannel.length);
            const copyStart = inputChannel.length - copyLength;
            
            // 이전 데이터 이동
            for (let i = 0; i < this.taps - copyLength; i++) {
                delayBuffer[i] = delayBuffer[i + copyLength];
            }
            
            // 새 데이터 추가
            for (let i = 0; i < copyLength; i++) {
                delayBuffer[this.taps - copyLength + i] = inputChannel[copyStart + i];
            }
        }
        
        return true;
    }
}

registerProcessor('adaptive-loudness-processor', AdaptiveLoudnessWorkletProcessor);