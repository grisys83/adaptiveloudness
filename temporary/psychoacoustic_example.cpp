/**
 * 심리음향 보정 알고리즘 실제 사용 예제
 * JUCE 프레임워크 통합 버전
 */

#include "psychoacoustic_correction.cpp"
#include <JuceHeader.h>

class PsychoacousticProcessor : public juce::AudioProcessor {
private:
    // 핵심 컴포넌트
    PsychoacousticCorrection corrector;
    
    // FFT 처리
    juce::dsp::FFT fft;
    juce::dsp::WindowingFunction<float> window;
    
    // 버퍼
    static constexpr int fftOrder = 11; // 2^11 = 2048
    static constexpr int fftSize = 1 << fftOrder;
    std::array<float, fftSize * 2> fftData;
    std::array<std::complex<float>, fftSize> spectrum;
    
    // 현재 상태
    std::atomic<float> currentNoiseFloor{40.0f};
    std::atomic<float> targetPhon{52.0f};
    std::vector<float> currentGains;
    
    // 오버랩-애드를 위한 버퍼
    juce::AudioBuffer<float> overlapBuffer;
    int overlapPosition = 0;
    
public:
    PsychoacousticProcessor()
        : AudioProcessor(BusesProperties()
            .withInput("Input", juce::AudioChannelSet::stereo(), true)
            .withOutput("Output", juce::AudioChannelSet::stereo(), true)),
          corrector(48000.0f, fftSize),
          fft(fftOrder),
          window(fftSize, juce::dsp::WindowingFunction<float>::hann),
          currentGains(fftSize / 2 + 1, 1.0f),
          overlapBuffer(2, fftSize) {
        
        overlapBuffer.clear();
    }
    
    void prepareToPlay(double sampleRate, int samplesPerBlock) override {
        // 샘플레이트 업데이트
        corrector = PsychoacousticCorrection(sampleRate, fftSize);
        
        // 초기 보정 곡선 계산
        updateCorrectionCurve();
    }
    
    void processBlock(juce::AudioBuffer<float>& buffer, 
                     juce::MidiBuffer& midiMessages) override {
        
        const int numChannels = buffer.getNumChannels();
        const int numSamples = buffer.getNumSamples();
        
        // 각 채널 처리
        for (int channel = 0; channel < numChannels; ++channel) {
            processChannel(buffer, channel, numSamples);
        }
    }
    
private:
    void processChannel(juce::AudioBuffer<float>& buffer, int channel, int numSamples) {
        auto* channelData = buffer.getWritePointer(channel);
        
        // 오버랩-애드 처리
        for (int sample = 0; sample < numSamples; ++sample) {
            // FFT 버퍼에 샘플 추가
            fftData[overlapPosition] = channelData[sample];
            
            // 50% 오버랩에 도달하면 FFT 처리
            if (overlapPosition == fftSize / 2) {
                processFFTBlock(channel);
            }
            
            // 출력 샘플 읽기
            channelData[sample] = overlapBuffer.getSample(channel, overlapPosition);
            overlapBuffer.setSample(channel, overlapPosition, 0.0f);
            
            // 위치 업데이트
            overlapPosition = (overlapPosition + 1) % fftSize;
        }
    }
    
    void processFFTBlock(int channel) {
        // 현재 블록 복사
        std::array<float, fftSize> processingBuffer;
        
        // 순환 버퍼에서 선형 버퍼로 복사
        for (int i = 0; i < fftSize; ++i) {
            int idx = (overlapPosition + i) % fftSize;
            processingBuffer[i] = fftData[idx];
        }
        
        // 윈도우 적용
        window.multiplyWithWindowingTable(processingBuffer.data(), fftSize);
        
        // FFT 수행
        std::array<std::complex<float>, fftSize> complexData;
        for (int i = 0; i < fftSize; ++i) {
            complexData[i] = processingBuffer[i];
        }
        
        fft.perform(complexData.data(), complexData.data(), false);
        
        // 심리음향 보정 적용
        applyPsychoacousticCorrection(complexData.data());
        
        // IFFT
        fft.perform(complexData.data(), complexData.data(), true);
        
        // 실수부 추출 및 오버랩-애드
        for (int i = 0; i < fftSize; ++i) {
            int outputIdx = (overlapPosition + i) % fftSize;
            float value = complexData[i].real() / fftSize; // FFT 정규화
            
            // 기존 값에 더하기 (오버랩-애드)
            float existing = overlapBuffer.getSample(channel, outputIdx);
            overlapBuffer.setSample(channel, outputIdx, existing + value);
        }
    }
    
    void applyPsychoacousticCorrection(std::complex<float>* spectrum) {
        // 실시간으로 업데이트된 게인 적용
        corrector.applyCorrection(spectrum, currentGains, 1.0f);
    }
    
    void updateCorrectionCurve() {
        float noise = currentNoiseFloor.load();
        float target = targetPhon.load();
        
        // 현재 재생 레벨 (노이즈 + 8dB)
        float currentPhon = noise + 8.0f;
        
        // 보정 곡선 계산
        auto correctionDB = corrector.calculateCorrectionCurve(currentPhon, target);
        auto newGains = corrector.convertToFFTBins(correctionDB);
        
        // 부드러운 전환
        corrector.smoothTransition(newGains, currentGains, 0.99f);
        currentGains = newGains;
    }
    
public:
    // 파라미터 업데이트 (GUI나 자동화에서 호출)
    void setNoiseFloor(float noiseDB) {
        currentNoiseFloor = noiseDB;
        updateCorrectionCurve();
    }
    
    void setTargetPhon(float phon) {
        targetPhon = phon;
        updateCorrectionCurve();
    }
    
    // 디버깅용 현재 보정 곡선 반환
    std::vector<float> getCurrentCorrectionCurve() const {
        std::vector<float> curveDB;
        
        for (float gain : currentGains) {
            float db = 20.0f * std::log10(gain);
            curveDB.push_back(db);
        }
        
        return curveDB;
    }
    
    // GUI 표시용 주파수 응답
    void getFrequencyResponse(float* magnitudes, float* frequencies, int numPoints) {
        for (int i = 0; i < numPoints; ++i) {
            float freq = 20.0f * std::pow(10.0f, i * 3.0f / numPoints); // 20Hz - 20kHz log scale
            int bin = (int)(freq * fftSize / getSampleRate());
            
            if (bin < currentGains.size()) {
                frequencies[i] = freq;
                magnitudes[i] = 20.0f * std::log10(currentGains[bin]);
            }
        }
    }
    
    // 필수 AudioProcessor 메서드들
    const juce::String getName() const override { return "Psychoacoustic EQ"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int index) override {}
    const juce::String getProgramName(int index) override { return {}; }
    void changeProgramName(int index, const juce::String& newName) override {}
    juce::AudioProcessorEditor* createEditor() override { return nullptr; }
    bool hasEditor() const override { return false; }
    void getStateInformation(juce::MemoryBlock& destData) override {}
    void setStateInformation(const void* data, int sizeInBytes) override {}
};

/**
 * 간단한 3밴드 버전 (CPU 효율적)
 */
class SimplePsychoacousticEQ : public juce::AudioProcessor {
private:
    // 3밴드 필터
    juce::dsp::ProcessorDuplicator<juce::dsp::IIR::Filter<float>, 
                                   juce::dsp::IIR::Coefficients<float>> lowShelf;
    juce::dsp::ProcessorDuplicator<juce::dsp::IIR::Filter<float>, 
                                   juce::dsp::IIR::Coefficients<float>> midPeak;
    juce::dsp::ProcessorDuplicator<juce::dsp::IIR::Filter<float>, 
                                   juce::dsp::IIR::Coefficients<float>> highShelf;
    
    OptimizedPsychoacousticEQ optimizer;
    
    // 현재 설정
    float currentNoiseFloor = 40.0f;
    float currentPhon = 48.0f;
    float targetPhon = 53.0f;
    
public:
    SimplePsychoacousticEQ() : AudioProcessor(
        BusesProperties()
            .withInput("Input", juce::AudioChannelSet::stereo(), true)
            .withOutput("Output", juce::AudioChannelSet::stereo(), true)) {}
    
    void prepareToPlay(double sampleRate, int samplesPerBlock) override {
        juce::dsp::ProcessSpec spec;
        spec.sampleRate = sampleRate;
        spec.maximumBlockSize = samplesPerBlock;
        spec.numChannels = getTotalNumOutputChannels();
        
        lowShelf.prepare(spec);
        midPeak.prepare(spec);
        highShelf.prepare(spec);
        
        updateFilters();
    }
    
    void processBlock(juce::AudioBuffer<float>& buffer, 
                     juce::MidiBuffer& midiMessages) override {
        juce::dsp::AudioBlock<float> block(buffer);
        juce::dsp::ProcessContextReplacing<float> context(block);
        
        // 3밴드 EQ 처리
        lowShelf.process(context);
        midPeak.process(context);
        highShelf.process(context);
    }
    
private:
    void updateFilters() {
        auto eq = optimizer.calculateSimplifiedCorrection(currentPhon, targetPhon);
        
        // Low shelf: 100 Hz, Q=0.7
        *lowShelf.state = *juce::dsp::IIR::Coefficients<float>::makeLowShelf(
            getSampleRate(), 100.0f, 0.7f, 
            juce::Decibels::decibelsToGain(eq.bassGain));
        
        // Mid peak: 1000 Hz, Q=0.5
        *midPeak.state = *juce::dsp::IIR::Coefficients<float>::makePeakFilter(
            getSampleRate(), 1000.0f, 0.5f,
            juce::Decibels::decibelsToGain(eq.midGain));
        
        // High shelf: 8000 Hz, Q=0.7
        *highShelf.state = *juce::dsp::IIR::Coefficients<float>::makeHighShelf(
            getSampleRate(), 8000.0f, 0.7f,
            juce::Decibels::decibelsToGain(eq.trebleGain));
    }
    
public:
    void updateEnvironment(float noiseDB) {
        currentNoiseFloor = noiseDB;
        currentPhon = noiseDB + 8.0f;
        targetPhon = currentPhon + 5.0f;
        updateFilters();
    }
    
    // AudioProcessor 필수 메서드들 (위와 동일)
    const juce::String getName() const override { return "Simple Psychoacoustic EQ"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int index) override {}
    const juce::String getProgramName(int index) override { return {}; }
    void changeProgramName(int index, const juce::String& newName) override {}
    juce::AudioProcessorEditor* createEditor() override { return nullptr; }
    bool hasEditor() const override { return false; }
    void getStateInformation(juce::MemoryBlock& destData) override {}
    void setStateInformation(const void* data, int sizeInBytes) override {}
};