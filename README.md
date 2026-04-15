# VoiceTyper Pro (v17) 🎤✨

VoiceTyper Pro is a high-performance, AI-assisted voice-to-text application specifically designed for Windows. It features a premium, borderless "Micro UI" and a hybrid typing engine that combines blazing-fast speed with 100% accuracy.

![Logo](https://img.shields.io/badge/Version-17.0-cyan)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## 🚀 Key Features

- **Hybrid Typing Engine**: Uses direct keyboard simulation for speed and clipboard fallback for complex characters (Hindi/Special characters).
- **Smart Polish Engine**: Automatically removes filler words (um, uh, like) for professional results.
- **Voice Commands**: Control your cursor with phrases like *"New Line"*, *"Backspace"*, and *"Tab space"*.
- **Premium Micro UI**: A sleek, borderless, rounded-corner interface that floats stay on top of any app.
- **Ultimate Minimize Fix**: Custom "Dummy Root" architecture ensures 100% stable minimization to the Windows Taskbar.
- **Multi-Language Support**: Choose between Hindi, English, and Auto-detection.
- **Real-time Visualization**: Cyber-Cyan breathing border animation and live mic energy levels.

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
   python viceTyperPro.py
   ```

## ⌨️ Controls

- **Start/Stop Listening**: `Ctrl + Space` (Global Hotkey) or the UI Start button.
- **Switch Language**: Use the interactable "Chips" in the dashboard.
- **Adjust Sensitivity**: Use the slider to balance between "Whisper" and "Noise" modes.
- **Stealth Mode**: Click the **◈** icon (if available) or use the **—** to minimize to the taskbar.

## 🌟 Acknowledgments
- Inspired by Wispr Flow.
- Built with Python, Tkinter, and Win32 APIs (ctypes).

---
*Created by Prakash Shiromani*