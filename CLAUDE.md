# Smart Music Player v4 - Technical Documentation

## Project Overview
An advanced adaptive loudness compensation music player that automatically adjusts audio based on environmental noise and psychoacoustic principles. The system implements ISO 226:2003 equal-loudness contours with real-time FIR filtering, smart volume control, and adaptive quiet mode detection.

## Core Architecture

### Audio Processing Pipeline
```
Input → Track Normalization → FIR Filter (A/B) → Wet Crossfader → 
→ Compensation Gain → Auto Gain → Master Volume → Output
```

### Key Design Decisions
1. **100% Wet Signal**: No dry path to avoid phase cancellation issues
2. **Dual FIR Filter System**: Enables seamless real-time filter updates without audio interruption
3. **Negative Auto-Gain**: Allows volume reduction in quiet environments (-30 to +30 dB range)
4. **Adaptive Quiet Mode**: Automatically reduces compensation when listening quietly

## Major Features

### 1. Smart Volume System
- **Environmental Monitoring**: Real-time noise analysis via microphone
- **Adaptive Gain**: Maintains desired SNR (Signal-to-Noise Ratio)
- **Range**: -30 to +30 dB automatic adjustment
- **Default SNR**: +20 dB above ambient (adjustable 0-50 dB)
- **Calibration**: 85 dB SPL = 0 LUFS reference

### 2. Equal-Loudness Compensation
- **ISO 226:2003**: Full implementation with interpolated curves
- **FIR Filters**: 4095-tap filters designed with Parks-McClellan algorithm
- **Dual System**: A/B filters with 10-second crossfade
- **Quiet Enhancement**: 80% default strength (adjustable 0-100%)

### 3. Adaptive Quiet Mode (NEW)
- **Detection**: Activates when volume is 3dB below 5-minute average for 30+ seconds
- **Adaptation**: S-curve reduction from 80% to 50% over 2 minutes
- **Recovery**: Gradual return to normal (0.5% per second)
- **Purpose**: Prevents over-compensation during quiet listening

### 4. Dynamic Filter Generation
- **Smart Mode**: Automatically adjusts target phon based on actual listening level
- **Formula**: `dynamicTargetPhon = round((noiseLevel + SNR) / 10) * 10`
- **Protection**: Ensures target < reference with automatic adjustment

### 5. Track Normalization
- **Target**: -14 LUFS (streaming standard)
- **Analysis**: Simplified K-weighted loudness measurement
- **Peak Protection**: Prevents clipping while maximizing loudness
- **Toggle**: Can be disabled for audiophile listening

### 6. Metadata & Album Art
- **Formats**: ID3v2, MP4, Vorbis Comments
- **Display**: Title, Artist, Album
- **Album Art**: Extracted and displayed with memory management

## Technical Specifications

### Audio Processing
- **Sample Rate**: Native (44.1/48 kHz)
- **Buffer Size**: 4096 samples
- **FIR Design**: 512 log-spaced frequency points
- **Window**: Hamming window for FIR coefficients
- **Crossfade**: 10 seconds between filter changes

### Update Cycles
- **Filter Updates**: Every 30 seconds (when in 'filter' mode)
- **Volume Updates**: Every 30 seconds (when in 'volume' mode)
- **Mode Alternation**: Switches between filter/volume updates
- **Noise Averaging**: 60-second window (current + previous 30s)

### Listening Session Tracking
```javascript
listeningSession = {
    volumeHistory: [],        // 5 minutes of samples (1/sec)
    averageVolume: 0,        // Moving average
    quietModeStartTime: null, // Quiet mode timestamp
    isQuietMode: false,      // Current state
    currentAdaptation: 1.0   // 1.0 to 0.625 (80% to 50%)
}
```

### Psychoacoustic Parameters
- **Default Target**: 50 phon (reduced from 60 for quieter default)
- **Reference Range**: 60-90 phon (user adjustable)
- **Extra Boost**: Optional +3dB bass (<100Hz), +2dB treble (>8kHz)
- **Noise Threshold**: 45 dB for environmental detection

## Key Algorithms

### Noise Level Measurement
```javascript
// RMS calculation with calibration
const rms = Math.sqrt(sum / bufferLength);
const dBFS = 20 * Math.log10(Math.max(0.00001, adjustedRms));
const dB_SPL = dBFS + 90; // Calibration offset
```

### Auto Gain Calculation
```javascript
const targetMusicLevel = avgNoiseLevel + desiredSNR;
let newAutoGain = targetMusicLevel - targetPhon;
newAutoGain = Math.max(-30, Math.min(30, newAutoGain));
```

### Quiet Mode Adaptation
```javascript
// S-curve over 2 minutes
const t = Math.min(elapsedSeconds / 120, 1);
const sigmoid = 1 / (1 + Math.exp(-10 * (t - 0.5)));
currentAdaptation = 1.0 - 0.375 * sigmoid; // 100% to 62.5%
```

### Filter Compensation
```javascript
// With adaptive quiet mode
compensation = targetSPL - referenceSPL;
const adaptedEnhancement = quietEnhancement * currentAdaptation;
compensation *= (adaptedEnhancement / 100);
```

## UI/UX Design

### Layout
- **YouTube Music Style**: Modern dark theme with green accents
- **Three Sections**: Main view, right sidebar (playlist), bottom player
- **Responsive**: Adapts to window size

### Smart Controls
- **Player Bar Integration**: All smart features in one green-bordered container
- **Status Display**: Real-time noise, headroom, EQ curve, quiet mode
- **Visual Feedback**: iOS-style green theme for smart features

### Settings Organization
- **Advanced Settings**: Hidden complexity for power users
- **Quick Access**: Smart Volume slider in player bar
- **Persistent**: Settings saved to localStorage

## Usage Guidelines

### Initial Setup
1. Smart Mode auto-starts on load
2. Microphone permission requested
3. System volume should be at 100%

### Calibration
- Assumes 85 dB SPL at 100% system volume
- Adjustable mic sensitivity (0.5-5.0x)
- Manual threshold when mic disabled

### Best Practices
- Use in-app volume control when Smart Mode active
- Green slider controls music level above noise
- Let system adapt to your listening patterns

## Implementation Notes

### Browser Requirements
- Web Audio API
- getUserMedia (microphone)
- ES6 modules
- localStorage

### Performance Optimizations
- Throttled UI updates (1Hz)
- Efficient buffer management
- Lazy filter calculation

### Known Limitations
- Initial 10-second filter calculation
- Requires user interaction to start
- Phase issues prevented by 100% wet design

## Version History

### v4 (Current)
- Adaptive Quiet Mode
- Negative auto-gain support
- Improved normalization
- Metadata/album art support
- Refined UI/UX

### v3
- YouTube Music style UI
- Smart Volume integration
- Basic features only

### v2
- Full DSP implementation
- LUFS analysis
- Dual buffer system

### v1
- Basic adaptive loudness
- Simple UI

## Development Commands
```bash
# No build required - pure HTML/JS/CSS
# Local testing:
python3 -m http.server 8000
# or
npx serve .
```

## Future Enhancements
1. AudioWorklet migration
2. Cloud profile sync
3. Room correction
4. Multi-band dynamics
5. Bluetooth latency compensation