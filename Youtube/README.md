# 🎬 Pro Video Editor

A powerful, all-in-one **Python Desktop Video Editor** with a modern dark UI — built with `CustomTkinter` + `FFmpeg`. No subscriptions, no watermarks, fully open-source.

![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-Required-green?logo=ffmpeg&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![UI](https://img.shields.io/badge/UI-CustomTkinter-blueviolet)
![MoviePy](https://img.shields.io/badge/MoviePy-1.0.3+-orange?logo=python&logoColor=white)
![Pillow](https://img.shields.io/badge/Pillow-9.0.0+-blue?logo=python&logoColor=white)

---

## 📖 Table of Contents

- [✨ Features](#-features)
- [🖥️ Screenshots](#️-screenshots)
- [🚀 Quick Start](#-quick-start)
- [📦 Requirements](#-requirements)
- [🗂️ Project Structure](#️-project-structure)
- [🎯 How to Use](#-how-to-use)
- [🧱 Built With](#-built-with)
- [🤝 Contributing](#-contributing)
- [🐛 Bug Reports](#-bug-reports)
- [💡 Feature Requests](#-feature-requests)
- [📄 License](#-license)
- [👤 Author](#-author)

---

## ✨ Features

| Tab | What it does |
|-----|-------------|
| ✂️ **Trim / Split** | Trim by timestamps, split into fixed-length chunks (e.g. 10 or 15 min frames), remove middle sections |
| 🔗 **Merge** | Join multiple videos in any order with drag-to-reorder |
| 📝 **Text & Subtitles** | Add text overlays at any position/time, burn-in `.srt` subtitle files |
| 🖼️ **Logo / Watermark** | Overlay a PNG/JPG logo with custom position, size & opacity |
| 🎨 **Filters & Effects** | Adjust brightness, contrast, saturation, gamma; apply grayscale, blur, flip, vignette |
| 🔊 **Audio** | Control volume, mute, remove audio, extract to MP3, replace audio track, change playback speed |
| 📐 **Crop & Resize** | Resize to presets (1080p, 720p, Reels/TikTok, Square), custom crop, add black padding |
| 🎬 **Intro / Outro** | Attach a starting or ending video clip to any video |
| 📤 **Export** | Choose format (mp4/mkv/avi/mov/webm/gif), codec, CRF quality, FPS, resolution — batch convert all |

### 🔧 Additional Features
- 🗂️ **File Sidebar** — load multiple files, view metadata (duration, resolution, FPS, size), remove files
- 📊 **Progress Bar** — real-time FFmpeg progress display
- 🌑 **Modern Dark UI** — built with CustomTkinter
- ⚡ **Batch Processing** — convert all loaded files at once

---

## 🖥️ Screenshots

> _Run the app and explore the modern dark interface with 9 editing tabs._

---

## 🚀 Quick Start

### 1. Prerequisites

Make sure you have **Python 3.8+** and **FFmpeg** installed.

**Install FFmpeg:**
```bash
# Windows (via winget)
winget install ffmpeg

# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Or download from https://ffmpeg.org/download.html
```

### 2. Clone the Repository
```bash
git clone https://github.com/YOUR_USERNAME/pro-video-editor.git
cd pro-video-editor
```

### 3. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the App
```bash
python video_editor.py
```

---

## 📦 Requirements

```
customtkinter>=5.2.0
moviepy>=1.0.3
Pillow>=9.0.0
```

See [`requirements.txt`](requirements.txt) for full list.

**System Requirements:**
- Python 3.8 or higher
- FFmpeg installed and available in PATH
- 4GB+ RAM recommended for video processing
- 1GB+ free disk space for temporary files

---

## 🗂️ Project Structure

```
Youtube/
  VEdit.py
  requirements.txt
  Input/
    logo.png
    ending.mp4
  Pending/   (ignored by git)
  Done/      (ignored by git)
  settings.json  (ignored by git)
```

```
pro-video-editor/
│
├── video_editor.py        # Main application (single file)
├── requirements.txt       # Python dependencies
├── README.md              # This file
├── CHANGELOG.md           # Version history
├── LICENSE                # MIT License
├── .gitignore             # Git ignore rules
└── .github/
    └── ISSUE_TEMPLATE/
        ├── bug_report.md
        └── feature_request.md
```

---

## 🎯 How to Use

1. **Launch the app** — run `python video_editor.py`
2. **Add videos** — click ➕ Add Video in the left sidebar
3. **Select a video** — click any file in the sidebar to make it active
4. **Choose a tab** — pick the editing operation you need
5. **Set output folder** — click 📁 Output Folder in the top bar
6. **Click the action button** — progress shows in the sidebar

> 💡 **Tip:** For splitting long videos (e.g., a 45-min video into 15-min parts), use the **✂️ Trim / Split** tab → "Split by Fixed Interval" → enter `15`.

---

## 🧱 Built With

- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) — Modern dark UI framework
- [FFmpeg](https://ffmpeg.org/) — Video processing engine
- [MoviePy](https://zulko.github.io/moviepy/) — Python video editing library
- [Pillow](https://pillow.readthedocs.io/) — Image handling

---

## 🤝 Contributing

Contributions are welcome! 🎉 Please read this guide carefully before contributing.

### 🛠️ How to Contribute

#### 1. Fork & Clone
```bash
git clone https://github.com/YOUR_USERNAME/pro-video-editor.git
cd pro-video-editor
```

#### 2. Create a Branch
Use a clear, descriptive branch name:
```bash
git checkout -b feature/add-timeline-scrubber
git checkout -b fix/split-progress-bar
git checkout -b docs/update-readme
```

#### 3. Make Your Changes
- Keep changes focused — one feature or fix per PR
- Follow existing code style (comments, naming)
- Test your changes on at least one video file

#### 4. Commit with Clear Messages
Follow the **Conventional Commits** format:
```
feat: add timeline scrubber to trim tab
fix: correct progress bar for batch export
docs: update README installation steps
refactor: extract ffmpeg helper to utils.py
chore: update requirements.txt versions
```

#### 5. Push & Open a Pull Request
```bash
git push origin feature/your-branch-name
```
Then open a Pull Request on GitHub with a clear description of what you changed and why.

### ✅ Code Style Guidelines

- Use descriptive variable names
- Add comments for complex FFmpeg filter logic
- Keep all UI code inside the `VideoEditorApp` class
- Helper functions go above the class definition
- Use `threading` for all FFmpeg operations (never block the UI)

### 📋 Commit Message Templates

```bash
# Adding a new feature
git commit -m "feat: add video preview player to sidebar"

# Fixing a bug
git commit -m "fix: resolve progress bar stuck at 0% on batch export"

# Improving performance
git commit -m "perf: speed up merge by using stream copy mode"

# Updating docs
git commit -m "docs: add screenshots to README"

# Refactoring code
git commit -m "refactor: extract ffmpeg runner to utils.py module"

# Chores / dependencies
git commit -m "chore: update requirements to latest stable versions"

# UI updates
git commit -m "ui: improve tab layout for smaller screen sizes"
```

---

## 🐛 Bug Reports

Found a bug? Please report it using our bug report template and include:

### Required Information
- Your OS and Python version
- FFmpeg version (`ffmpeg -version`)
- Steps to reproduce the bug
- Error message or screenshot

### Bug Report Template
```markdown
## 🐛 Bug Description
A clear and concise description of what the bug is.

## 📋 Steps to Reproduce
1. Open the app
2. Load video file '...'
3. Go to tab '...'
4. Click '...'
5. See error

## ✅ Expected Behavior
What you expected to happen.

## ❌ Actual Behavior
What actually happened. Include error messages or screenshots.

## 🖥️ Environment
- **OS:** (e.g. Windows 11, Ubuntu 22.04, macOS 14)
- **Python version:** (e.g. 3.11)
- **FFmpeg version:** (run `ffmpeg -version`)
- **App version:** v1.0.0

## 📎 Additional Context
Any other context, log output, or screenshots.
```

---

## 💡 Feature Requests

Have an idea for a new feature? We'd love to hear it!

### Feature Request Template
```markdown
## 💡 Feature Description
A clear description of the feature you'd like to see added.

## 🎯 Problem it Solves
What problem or limitation does this feature address?

## 🛠️ Proposed Solution
How do you think this should work? Describe the UI/UX if relevant.

## 🔄 Alternatives Considered
Any alternative approaches you've considered.

## 📎 Additional Context
Screenshots, mockups, or links to similar tools for reference.
```

---

## 📄 License

This project is licensed under the **MIT License** — see [`LICENSE`](LICENSE) for details.

By contributing, you agree that your contributions will be licensed under the **MIT License**.

---

## 👤 Author

**Nadeem**
- GitHub: [@YOUR_USERNAME](https://github.com/YOUR_USERNAME)

---

## 📊 Version History

See [`CHANGELOG.md`](CHANGELOG.md) for detailed version history and release notes.

### Current Version: v1.0.0 (2025-01-01)

- 🎉 Initial release with all core video editing features
- 🌑 Modern dark UI using CustomTkinter
- ⚡ Real-time FFmpeg progress tracking
- 📱 Cross-platform support (Windows, macOS, Linux)

---

> ⭐ If this project helped you, please give it a star on GitHub!

---

### 🏷️ GitHub Topics

```
python video-editor ffmpeg customtkinter video-processing
desktop-app open-source video-tools trim merge subtitles
```
