# Adaptive Loudness System 설계 명세서

## 1. 프로젝트 개요

### 1.1 목적
환경 노이즈, 콘텐츠 특성, 심리음향학적 요소를 동시에 고려하여 실시간으로 최적의 청취 경험을 제공하는 적응형 음압 제어 시스템 개발

### 1.2 핵심 기능
- 실시간 환경 노이즈 분석 및 적응
- ISO 226 기반 심리음향 주파수 보정
- 동적 음압 제어 및 최적화
- LUFS 기반 정확한 음압 측정

### 1.3 차별화 요소
- 환경 노이즈 + 심리음향 보정 + 동적 처리를 통합한 최초의 오픈소스 솔루션
- JUCE 기반 크로스플랫폼 지원
- VST3/AU/AAX 플러그인 및 독립 실행형 앱 동시 지원

## 2. 시스템 아키텍처

### 2.1 전체 구조
```
[Audio Input] → [Realtime Analyzer] → [Psychoacoustic Corrector] → [Adaptive Dynamics] → [Audio Output]
                         ↓                      ↓                          ↓
                  [Noise Estimator]      [EQ Curve Generator]      [Gain Controller]
                         ↓                      ↓                          ↓
                  [LUFS Meter]          [ISO 226 Model]           [Limiter/Compressor]
```

### 2.2 모듈별 설계

#### 2.2.1 Realtime Analyzer Module
- **기능**: 실시간 오디오 분석 및 환경 노이즈 추정
- **오픈소스 활용**: libebur128 (EBU R128 표준 LUFS 측정)
- **직접 구현**: 
  - 환경 노이즈 플로어 추정 알고리즘
  - 스펙트럼 분석 및 통계 수집
  - 이동 평균 필터링

#### 2.2.2 Psychoacoustic Corrector Module
- **기능**: ISO 226 기반 주파수별 음압 보정
- **오픈소스 활용**: ISO 226 equal-loudness contour 데이터
- **직접 구현**:
  - Equal-loudness curve 보간 알고리즘
  - 다중대역 파라메트릭 EQ 계산
  - 부드러운 전환을 위한 스무딩 알고리즘

#### 2.2.3 Adaptive Dynamics Module
- **기능**: 환경에 적응하는 동적 음압 제어
- **오픈소스 활용**: DynamiQ 베이스 관리 알고리즘 참고
- **직접 구현**:
  - 멀티밴드 컴프레서
  - Look-ahead 리미터
  - 적응형 게인 제어 시스템

### 2.3 데이터 플로우
1. 오디오 입력 → 버퍼링 (512-2048 샘플)
2. 병렬 처리: LUFS 측정 + 스펙트럼 분석 + 노이즈 추정
3. 심리음향 EQ 커브 계산 (10ms 업데이트)
4. 동적 처리 적용 (attack: 5ms, release: 50ms)
5. 최종 출력 + 피드백 루프

## 3. 기술 스택

### 3.1 개발 환경
- **언어**: C++ 17
- **프레임워크**: JUCE 7.0
- **빌드 시스템**: CMake
- **개발 OS**: macOS (초기), Windows/Linux (추후)

### 3.2 주요 라이브러리
| 라이브러리 | 용도 | 라이선스 |
|-----------|------|---------|
| JUCE 7.0 | 오디오 프레임워크 | GPL/Commercial |
| libebur128 | LUFS 측정 | MIT |
| KFR | DSP 연산 (선택적) | MIT |
| Eigen | 행렬 연산 | MPL2 |

### 3.3 오픈소스 참고 프로젝트
- equal-loudness (ISO 226 구현)
- Wale (실시간 볼륨 제어)
- flowEQ (적응형 EQ)
- DynamiQ (동적 베이스 관리)

## 4. 성능 요구사항

### 4.1 실시간 처리
- 최대 레이턴시: 10ms (512 샘플 @ 48kHz)
- CPU 사용률: < 5% (Intel i5 기준)
- 메모리 사용: < 50MB

### 4.2 오디오 품질
- 샘플레이트: 44.1kHz ~ 192kHz
- 비트 뎁스: 16/24/32 bit float
- THD+N: < 0.01%

## 5. 인터페이스 설계

### 5.1 파라미터
```cpp
struct AdaptiveLoudnessParameters {
    float targetLoudness;      // -23 ~ -16 LUFS
    float adaptationSpeed;     // 0.1 ~ 10.0 seconds
    float noiseFloorOffset;    // -60 ~ -20 dB
    bool enablePsychoacoustic; // on/off
    float listeningLevel;      // 60 ~ 90 dB SPL
};
```

### 5.2 GUI 구성
- 실시간 LUFS 미터
- 스펙트럼 분석기
- EQ 커브 시각화
- 환경 노이즈 레벨 인디케이터
- 프리셋 관리

## 6. 개발 로드맵

### Phase 1: MVP (10주)
- Week 1-2: JUCE + libebur128 통합
- Week 3-4: 실시간 분석 모듈 구현
- Week 5-6: 심리음향 EQ 구현
- Week 7-8: 동적 처리 및 통합
- Week 9-10: 기본 UI 및 테스트

### Phase 2: 확장 (8주)
- 고급 노이즈 추정 알고리즘
- 머신러닝 기반 콘텐츠 분류
- 멀티채널 지원 (5.1, 7.1)
- 고급 UI/UX

### Phase 3: 최적화 (4주)
- SIMD 최적화
- GPU 가속 (Metal/CUDA)
- 플러그인 포맷 확장

## 7. 테스트 계획

### 7.1 단위 테스트
- 각 모듈별 독립 테스트
- JUCE 단위 테스트 프레임워크 활용

### 7.2 통합 테스트
- 다양한 오디오 콘텐츠 (음악, 음성, 효과음)
- 다양한 환경 노이즈 시뮬레이션
- A/B 청취 테스트

### 7.3 성능 테스트
- CPU/메모리 프로파일링
- 레이턴시 측정
- 장시간 안정성 테스트

## 8. 라이선스 및 배포

### 8.1 라이선스
- 오픈소스 버전: GPL v3
- 상용 버전: Proprietary (JUCE 상용 라이선스)

### 8.2 배포 형태
- VST3/AU/AAX 플러그인
- 독립 실행형 애플리케이션
- 소스 코드 (GitHub)

## 9. 향후 확장 가능성

- AI 기반 콘텐츠 인식 및 자동 최적화
- 클라우드 기반 프리셋 공유
- 모바일 플랫폼 지원
- 하드웨어 DSP 통합
- 공간 음향 (Spatial Audio) 지원

## 10. 참고 문헌

- ISO 226:2003 - Acoustics — Normal equal-loudness-level contours
- ITU-R BS.1770-4 - Algorithms to measure audio programme loudness
- EBU R128 - Loudness normalisation and permitted maximum level
- Fletcher, H., & Munson, W. A. (1933). Loudness, its definition, measurement and calculation