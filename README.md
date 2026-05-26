# PyStage

PyStage is a lightweight ASCII-based video player written in Python.  
It renders video frames as text directly inside the terminal, creating a retro console-style viewing experience.

---
# PyStage – ASCII Video Player

[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Turn any video into beautiful ASCII art – right in your terminal (with a GUI)!

---

## ⚠️ Audio Notice – Please Read

**PyStage plays video audio ONLY if your file uses a format that `pygame.mixer` supports:**
- ✅ MP3
- ✅ OGG
- ✅ WAV
- ✅ MIDI, MOD, XM

**Most MP4 videos use AAC audio**, which pygame **cannot decode**.  
If your video plays silently, you need to convert its audio track to MP3.

### Quick Fix (FFmpeg – one command):
```bash
ffmpeg -i input.mp4 -c:v copy -c:a libmp3lame fixed.mp4
```

---

## Requirements
### With the source code:
- Python 3.10 or newer
- UTF-8 compatible terminal
### With the Windows Executable (.exe) file:
- At least Windows 10 1903 or newer

---

## Installation

- Download the installer [here](https://github.com/Tinnth7/PyStage/releases/)
- Run the installer
- Complete the installation
- Done!

---

## Roadmap

Planned features:

- Performance improvements
- Additional ASCII rendering modes
- Better color support
- Audio synchronization
- Webcam/live rendering
- Dynamic terminal resizing support

---

## Contributing

Contributions, bug reports, and suggestions are welcome.

1. Fork the repository
2. Create a branch
3. Commit changes
4. Open a pull request

---

## License

This project is licensed under the MIT License.  
See the [LICENSE](LICENSE) file for details.
