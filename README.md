# video2yt

Download a Bilibili video and burn danmaku (bullet comments) into the output MP4.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- `ffmpeg` and `ffprobe` in PATH (macOS: `brew install ffmpeg`)
- Chrome browser installed (for cookie-based login to access 1080p content)

## Install

```bash
uv sync
```

## Usage

```bash
uv run video2yt "https://www.bilibili.com/video/BVxxxxxxxxxx/" --quality 1080
```

Options:

| Flag | Default | Description |
|---|---|---|
| `-o, --output-dir` | `./output` | Where the final MP4 goes |
| `-t, --temp-dir` | `./temp` | Intermediate files (deleted on success) |
| `-q, --quality` | `1080` | Max quality (1080 / 720 / 480) |
| `-b, --browser` | `chrome` | Browser to read cookies from |
| `--keep-temp` | off | Keep intermediate files after success |

## Development

```bash
uv run pytest
```
