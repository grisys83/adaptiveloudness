# Step 1: Basic Offline Loudness Filter

## 개요
실시간 처리의 복잡성을 피하고, 단계적으로 adaptive loudness 시스템을 구축하기 위한 첫 번째 단계입니다.

## 실행 방법

### 기본 사용법
```bash
python process_audio_offline.py input.wav output.wav --target 40 --reference 60
```

### 파라미터 설명
- `input`: 입력 오디오 파일 (WAV, FLAC 등)
- `output`: 출력 오디오 파일
- `--target`: 재생 음량 레벨 (phon 단위, 기본값: 40)
- `--reference`: 기준 음량 레벨 (phon 단위, 기본값: 60)
- `--compensation`: 인지적 보상 계수 (0-1, 기본값: 0.4 = 40%)
- `--taps`: FIR 필터 탭 수 (기본값: 513)

### 예제

1. 조용한 환경에서 듣기 위한 처리 (40 phon → 50 phon)
```bash
python process_audio_offline.py music.wav music_quiet.wav --target 40 --reference 50
```

2. 60% 보상으로 처리
```bash
python process_audio_offline.py music.wav music_compensated.wav --target 40 --reference 50 --compensation 0.6
```

3. 고품질 필터 (1025 탭)
```bash
python process_audio_offline.py music.wav music_hq.wav --target 40 --reference 50 --taps 1025
```

## 동작 원리

1. **ISO 226:2003 곡선 기반**: 인간의 주파수별 음량 인지 특성을 반영
2. **인지적 보상**: 100% 보정은 과도하므로 40% 정도만 적용
3. **FIR 필터링**: 위상 왜곡 없는 선형 위상 필터 사용

## 다음 단계
- Step 2: Gain 파라미터를 입력받아 처리하는 프로그램
- Step 3: Wet/Dry 크로스페이드 구현
- Step 4: 시간에 따른 adaptive compensation
- Step 5: 환경 노이즈 기반 자동 조정