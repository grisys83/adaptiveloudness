/**
 * Psychoacoustic Correction Algorithm
 * Based on ISO 226:2003 Equal-Loudness Contours
 * 
 * 이 알고리즘은 재생 음압에 따른 인간 청각의 주파수별 민감도 차이를 보정합니다.
 * 낮은 음압에서 저음과 고음이 잘 들리지 않는 현상을 보상합니다.
 */

#include <vector>
#include <cmath>
#include <array>
#include <algorithm>

class PsychoacousticCorrection {
private:
    // ISO 226:2003 데이터 (일부 발췌)
    // 주파수: 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500 Hz
    static constexpr int NUM_FREQUENCIES = 29;
    static constexpr float FREQUENCIES[NUM_FREQUENCIES] = {
        20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500,
        630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500
    };
    
    // Equal-loudness levels (phon) 
    static constexpr int NUM_PHON_LEVELS = 11;
    static constexpr float PHON_LEVELS[NUM_PHON_LEVELS] = {
        0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100
    };
    
    // SPL values for each frequency at different phon levels (일부 데이터)
    // 실제로는 ISO 226:2003 전체 테이블이 필요합니다
    static constexpr float ISO226_SPL[NUM_PHON_LEVELS][NUM_FREQUENCIES] = {
        // 0 phon (hearing threshold)
        {74.3, 65.0, 56.3, 48.4, 41.7, 35.5, 29.8, 25.1, 20.7, 16.8, 13.8, 11.2, 8.9, 7.2, 6.0, 5.0, 4.4, 4.2, 3.7, 2.6, 1.0, -1.2, -3.6, -3.9, -1.1, 4.3, 11.1, 15.3, 16.4},
        // 10 phon
        {83.2, 74.3, 65.9, 58.0, 51.4, 45.5, 40.0, 35.2, 31.0, 27.0, 23.7, 21.1, 18.8, 17.0, 15.7, 14.6, 13.8, 13.4, 13.0, 12.6, 11.8, 10.6, 8.9, 7.9, 9.6, 14.4, 20.7, 24.7, 25.6},
        // ... 더 많은 데이터
        // 여기서는 간단히 40 phon과 60 phon만 포함
        // 40 phon
        {99.8, 93.1, 86.5, 80.0, 74.1, 68.7, 63.6, 58.9, 54.5, 50.4, 46.6, 43.1, 39.9, 37.1, 34.6, 32.4, 30.4, 29.0, 27.8, 26.6, 25.5, 23.9, 22.0, 20.5, 21.3, 25.4, 31.3, 35.4, 36.6},
        // 60 phon  
        {109.5, 103.7, 98.0, 92.6, 87.4, 82.5, 77.8, 73.4, 69.2, 65.2, 61.4, 57.8, 54.5, 51.4, 48.6, 46.0, 43.5, 41.5, 40.0, 38.5, 37.2, 35.5, 33.5, 31.6, 32.2, 36.0, 41.7, 45.8, 47.1}
    };
    
    float sampleRate;
    int fftSize;
    
public:
    PsychoacousticCorrection(float sr = 48000.0f, int fftSz = 2048) 
        : sampleRate(sr), fftSize(fftSz) {}
    
    /**
     * 현재 재생 레벨에서 목표 레벨로 들리도록 하는 주파수별 보정값 계산
     * @param currentPhon 현재 재생 phon 레벨 (예: 40)
     * @param targetPhon 목표로 하는 phon 레벨 (예: 60)
     * @return 주파수별 보정 게인 (dB)
     */
    std::vector<float> calculateCorrectionCurve(float currentPhon, float targetPhon) {
        std::vector<float> correction(NUM_FREQUENCIES);
        
        for (int i = 0; i < NUM_FREQUENCIES; i++) {
            float currentSPL = interpolatePhonToSPL(FREQUENCIES[i], currentPhon);
            float targetSPL = interpolatePhonToSPL(FREQUENCIES[i], targetPhon);
            
            // 보정값 = 목표 SPL - 현재 SPL
            correction[i] = targetSPL - currentSPL;
        }
        
        return correction;
    }
    
    /**
     * 보정 곡선을 FFT 빈으로 변환
     * @param correctionCurve 주파수별 보정값 (dB)
     * @return FFT 빈별 게인 (linear)
     */
    std::vector<float> convertToFFTBins(const std::vector<float>& correctionCurve) {
        int numBins = fftSize / 2 + 1;
        std::vector<float> fftGains(numBins, 1.0f);
        
        for (int bin = 0; bin < numBins; bin++) {
            float freq = (float)bin * sampleRate / fftSize;
            
            // 주변 주파수 포인트 찾기 (선형 보간)
            int idx = 0;
            while (idx < NUM_FREQUENCIES - 1 && FREQUENCIES[idx + 1] < freq) {
                idx++;
            }
            
            if (idx < NUM_FREQUENCIES - 1) {
                // 선형 보간
                float f1 = FREQUENCIES[idx];
                float f2 = FREQUENCIES[idx + 1];
                float g1 = correctionCurve[idx];
                float g2 = correctionCurve[idx + 1];
                
                float ratio = (freq - f1) / (f2 - f1);
                float gainDB = g1 + ratio * (g2 - g1);
                
                // dB를 linear gain으로 변환
                fftGains[bin] = std::pow(10.0f, gainDB / 20.0f);
            }
        }
        
        return fftGains;
    }
    
    /**
     * 실시간 오디오 처리를 위한 스무딩 필터
     * @param newGains 새로운 게인 값들
     * @param currentGains 현재 게인 값들
     * @param smoothingFactor 스무딩 계수 (0.0 ~ 1.0)
     */
    void smoothTransition(std::vector<float>& newGains, 
                         const std::vector<float>& currentGains,
                         float smoothingFactor = 0.95f) {
        for (size_t i = 0; i < newGains.size(); i++) {
            newGains[i] = currentGains[i] * smoothingFactor + 
                         newGains[i] * (1.0f - smoothingFactor);
        }
    }
    
    /**
     * 적응형 보정 적용
     * @param spectrum 입력 스펙트럼 (복소수)
     * @param gains FFT 빈별 게인
     * @param adaptiveFactor 적응 강도 (0.0 ~ 1.0)
     */
    void applyCorrection(std::complex<float>* spectrum, 
                        const std::vector<float>& gains,
                        float adaptiveFactor = 1.0f) {
        int numBins = fftSize / 2 + 1;
        
        for (int bin = 0; bin < numBins; bin++) {
            // 적응형 게인 적용
            float gain = 1.0f + (gains[bin] - 1.0f) * adaptiveFactor;
            spectrum[bin] *= gain;
            
            // 대칭성 유지 (Nyquist 제외)
            if (bin > 0 && bin < numBins - 1) {
                spectrum[fftSize - bin] = std::conj(spectrum[bin]);
            }
        }
    }
    
private:
    /**
     * 주어진 주파수와 phon 레벨에서 SPL 값 보간
     */
    float interpolatePhonToSPL(float frequency, float phonLevel) {
        // 간단한 구현을 위해 40 phon과 60 phon 데이터만 사용
        // 실제로는 모든 phon 레벨에 대한 보간이 필요
        
        int freqIdx = 0;
        for (int i = 0; i < NUM_FREQUENCIES - 1; i++) {
            if (frequency >= FREQUENCIES[i] && frequency <= FREQUENCIES[i + 1]) {
                freqIdx = i;
                break;
            }
        }
        
        // phon 레벨 인덱스 찾기
        int phonIdx = 2; // 40 phon (예시)
        if (phonLevel > 50) phonIdx = 3; // 60 phon
        
        // 주파수 보간
        float f1 = FREQUENCIES[freqIdx];
        float f2 = FREQUENCIES[freqIdx + 1];
        float spl1 = ISO226_SPL[phonIdx][freqIdx];
        float spl2 = ISO226_SPL[phonIdx][freqIdx + 1];
        
        float ratio = (frequency - f1) / (f2 - f1);
        return spl1 + ratio * (spl2 - spl1);
    }
};

/**
 * 사용 예제
 */
class AdaptiveLoudnessEQ {
private:
    PsychoacousticCorrection corrector;
    std::vector<float> currentGains;
    float currentPhon = 40.0f;
    float targetPhon = 60.0f;
    
public:
    AdaptiveLoudnessEQ(float sampleRate) 
        : corrector(sampleRate), currentGains(1025, 1.0f) {} // 2048 FFT = 1025 bins
    
    void updateEnvironment(float noiseFloorDB, float playbackLevelDB) {
        // 환경 소음 + 8dB = 재생 레벨
        currentPhon = playbackLevelDB;
        
        // 심리적으로 5 phon 더 크게 들리도록
        targetPhon = currentPhon + 5.0f;
        
        // 보정 곡선 계산
        auto correctionDB = corrector.calculateCorrectionCurve(currentPhon, targetPhon);
        auto newGains = corrector.convertToFFTBins(correctionDB);
        
        // 부드러운 전환
        corrector.smoothTransition(newGains, currentGains, 0.98f);
        currentGains = newGains;
    }
    
    void processAudioBlock(float* audioData, int numSamples) {
        // FFT 수행 (여기서는 의사 코드)
        std::complex<float> spectrum[2048];
        // performFFT(audioData, spectrum);
        
        // 심리음향 보정 적용
        corrector.applyCorrection(spectrum, currentGains);
        
        // IFFT 수행
        // performIFFT(spectrum, audioData);
    }
};

/**
 * 추가 최적화 기법
 */
class OptimizedPsychoacousticEQ {
private:
    // Bark scale 대역 사용 (24 bands instead of 1025 bins)
    static constexpr int NUM_BARK_BANDS = 24;
    float barkGains[NUM_BARK_BANDS];
    
    // 저음/중음/고음 간단한 3밴드 버전
    struct SimplifiedEQ {
        float bassGain;    // 20-250 Hz
        float midGain;     // 250-4000 Hz  
        float trebleGain;  // 4000-20000 Hz
    };
    
public:
    SimplifiedEQ calculateSimplifiedCorrection(float currentPhon, float targetPhon) {
        SimplifiedEQ eq;
        
        float phonDiff = targetPhon - currentPhon;
        
        // 인지적 보상을 고려한 보수적 접근
        // 실제 필요한 보정은 ISO 226의 30-50% 정도
        float compensationFactor = 0.4f; // 40% 보정
        
        // 저음: ISO 226 차이의 40%만 보정
        // (뇌가 이미 부분적으로 보상하고 있음)
        eq.bassGain = phonDiff * 0.8f * compensationFactor;
        
        // 중음: 최소 보정 (뇌의 보상이 가장 효과적)
        eq.midGain = phonDiff * 0.1f * compensationFactor;
        
        // 고음: 중간 정도 보정
        eq.trebleGain = phonDiff * 0.3f * compensationFactor;
        
        // 부드러운 제한 (과도한 보정 방지)
        eq.bassGain = std::clamp(eq.bassGain, -6.0f, 6.0f);
        eq.midGain = std::clamp(eq.midGain, -2.0f, 2.0f);
        eq.trebleGain = std::clamp(eq.trebleGain, -3.0f, 3.0f);
        
        return eq;
    }
    
    // 적응형 보상 팩터 (청취 시간에 따라 조정)
    float getAdaptiveCompensationFactor(float listeningDuration) {
        // 처음: 50% 보정 (뇌가 아직 적응 안 함)
        // 5분 후: 30% 보정 (뇌가 적응 중)
        // 15분 후: 20% 보정 (뇌가 완전히 적응)
        
        float minutes = listeningDuration / 60.0f;
        float factor = 0.5f - (0.3f * std::tanh(minutes / 10.0f));
        return std::clamp(factor, 0.2f, 0.5f);
    }
};