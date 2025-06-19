# Smart Music Player 🎵

An advanced adaptive loudness compensation music player that automatically adjusts to your listening environment.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Version](https://img.shields.io/badge/version-4.0-green.svg)
![Web Audio API](https://img.shields.io/badge/Web%20Audio%20API-supported-orange.svg)

## 🌟 Features

### Smart Volume Control
- **Real-time Environmental Monitoring**: Automatically adjusts volume based on ambient noise levels
- **Triple-Smoothed Noise Detection**: Advanced algorithm prevents sudden volume changes
- **Customizable SNR**: Set your preferred signal-to-noise ratio (0-50 dB)

### Adaptive Listening Modes
- **🔇 Quiet Mode**: Gradually reduces enhancement during extended quiet listening sessions
- **🔊 Loud Mode**: Intelligently increases compensation in noisy environments
- **🔄 Recovery Mode**: Smoothly returns to your preferred settings over 2 minutes

### Professional Audio Processing
- **ISO 226:2003 Equal-Loudness Contours**: Industry-standard psychoacoustic compensation
- **Dual-Filter Architecture**: Seamless A/B crossfading prevents audio interruptions
- **4095-tap FIR Filters**: High-precision frequency response correction
- **-14 LUFS Normalization**: Optional track-level normalization

### Modern User Interface
- **Real-time Status Display**: Monitor noise level, SPL, headroom, and EQ curves
- **Drag & Drop Playlist**: Easily organize your music
- **Album Art Support**: Automatic metadata extraction
- **Dark Theme**: Easy on the eyes during long listening sessions

## 🚀 Quick Start

1. **Visit the Live Demo**: [https://grisys83.github.io/adaptiveloudness/](https://grisys83.github.io/adaptiveloudness/)
2. **Allow Microphone Access**: Required for environmental monitoring
3. **Add Music**: Click the ➕ button or drag files to the playlist
4. **Enable Smart Volume**: Toggle the switch in the player bar
5. **Enjoy**: The player automatically adapts to your environment!

## 🎛️ How It Works

### Environmental Adaptation
The player continuously monitors ambient noise through your microphone and adjusts the playback volume to maintain your desired signal-to-noise ratio. The triple-smoothed algorithm ensures changes are gradual and natural.

### Psychoacoustic Compensation
Based on ISO 226:2003 equal-loudness contours, the player adjusts frequency response to maintain consistent perceived loudness across the spectrum as volume changes.

### Listening Pattern Analysis
The system tracks your listening habits and automatically reduces enhancement during extended quiet sessions to prevent ear fatigue, while providing appropriate boost in noisy environments.

## ⚙️ Advanced Settings

### Loudness Compensation
- **Reference Level**: Set the original mastering level (60-90 phon)
- **Quiet Enhancement**: Adjust compensation strength (0-100%)

### Microphone Settings
- **Manual Threshold**: Override automatic noise detection (20-80 dB)
- **Sensitivity**: Calibrate microphone input (0.5-5.0x)

### Audio Enhancement
- **Equal Loudness**: Toggle ISO 226:2003 compensation
- **Track Normalization**: Enable -14 LUFS normalization

## 📊 Technical Specifications

- **Filter Length**: 4095 taps
- **Crossfade Duration**: 10 seconds
- **Update Interval**: 60 seconds
- **Noise Averaging**: 60-second window with outlier removal
- **Adaptation Time**: 2 minutes (S-curve transition)
- **Frequency Range**: 20 Hz - 20 kHz
- **Dynamic Range**: ±30 dB auto-gain

## 🔧 Browser Compatibility

- ✅ Chrome/Edge (Recommended)
- ✅ Firefox
- ✅ Safari (iOS 15+)
- ⚠️ Requires Web Audio API support

## 🤝 Contributing

We welcome contributions! Please feel free to submit issues or pull requests.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- ISO 226:2003 standard implementation
- Web Audio API community
- Music metadata browser library

## 👥 Credits

**Proudly developed by the Adaptive Loudness Team and Claude AI Assistant**

---

*Experience music the way it was meant to be heard, adapted perfectly to your environment.* 🎧