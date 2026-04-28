# VoiceTyper Pro (v20) 🎤✨

VoiceTyper Pro is a high-performance, AI-assisted voice-to-text application specifically designed for Windows. It features a premium, borderless "Micro UI" and a hybrid typing engine that combines blazing-fast speed with 100% accuracy.

![Version](https://img.shields.io/badge/Version-20.0-cyan)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![API](https://img.shields.io/badge/API-Google%20Web%20Speech-orange)

## 🚀 Key Features

- **Smart Recognizer Pool** *(New in v20)*: A pool of 4 independent recognizer instances with automatic rotation — if one is slow or failing, the system instantly switches to the fastest available instance.
- **Auto Cooldown & Fallback** *(New in v20)*: Any recognizer that takes >3.5s or fails 3 times consecutively is put on a 30-second cooldown. All other instances keep working without interruption.
- **Hybrid Typing Engine**: Uses direct keyboard simulation for speed and clipboard fallback for complex characters (Hindi/Special characters).
- **Smart Polish Engine**: Automatically removes filler words (um, uh, like) for professional results.
- **Voice Commands**: Control your cursor with phrases like *"New Line"*, *"Backspace"*, and *"Tab space"*.
- **Premium Micro UI**: A sleek, borderless, rounded-corner interface that floats on top of any app.
- **Ultimate Minimize Fix**: Custom "Dummy Root" architecture ensures 100% stable minimization to the Windows Taskbar.
- **Multi-Language Support**: Choose between Hindi, English, and Auto-detection.
- **Real-time Visualization**: Cyber-Cyan breathing border animation and live mic energy levels.

## 🔄 Smart API Pool — How It Works

```
┌─────────────────────────────────────────────┐
│           SmartRecognizerPool (4 slots)      │
│                                              │
│  Slot #0  [avg: 380ms]  ✅ Active           │
│  Slot #1  [avg: 420ms]  ✅ Active           │
│  Slot #2  [avg: 4200ms] ⏳ Cooldown 28s     │
│  Slot #3  [avg: 390ms]  ✅ Active           │
│                                              │
│  Strategy: Lowest avg response time first   │
│  Fallback: Auto-retry on next best slot     │
└─────────────────────────────────────────────┘
```

| Setting | Value |
|---|---|
| Pool Size | 4 recognizer instances |
| Slow Threshold | 3.5 seconds |
| Cooldown Duration | 30 seconds |
| Max Fail Streak | 3 consecutive failures |

## 🛠️ Installation & Setup

1. **Requirements**:
   - Python 3.10 or higher.
   - Working Microphone.

2. **Dependencies**:
   ```bash
   pip install speechrecognition pyperclip keyboard PyAudio
   ```

3. **Running the app**:
   ```bash
   python voiceTyperPro.py
   ```

4. **Building EXE**:
   ```bash
   pyinstaller --clean VoiceTyperPro.spec
   ```

## ⌨️ Controls

- **Start/Stop Listening**: `Ctrl + Space` (Global Hotkey) or the UI Start button.
- **Switch Language**: Use the interactable "Chips" in the dashboard.
- **Adjust Sensitivity**: Use the slider to balance between "Whisper" and "Noise" modes.
- **Minimize**: Click the **—** button to minimize to the taskbar.

## 📋 Changelog

| Version | Changes |
|---|---|
| v20 | Smart Recognizer Pool — 4 instances, auto-rotation, cooldown, fallback |
| v19 | Speed Edition — Win32 SendInput, pre-compiled filler regex, 3 parallel workers |
| v17 | Ultimate minimize fix, Dummy Root architecture |

## 🌟 Acknowledgments
- Inspired by Wispr Flow.
- Built with Python, Tkinter, and Win32 APIs (ctypes).

---
*Created by Prakash Shiromani*