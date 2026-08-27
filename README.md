# Audio Converter

A simple GUI app that wraps [yt-dlp](https://github.com/yt-dlp/yt-dlp) to
download YouTube links as audio files.

## Prerequisites

- Python 3.10+
- `tkinter` (Python's GUI toolkit — not installable via pip, see below)

## Setup

Set up a virtual environment:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

On Windows, use `venv\Scripts\pip.exe` instead of `venv/bin/pip`.


## Running

```bash
venv/bin/python app.py
```

(`venv\Scripts\python.exe app.py` on Windows)

Calling the interpreter directly by path picks up the venv's installed
packages automatically — there's no need to `source venv/bin/activate` first.

## Configuration

- **Output folder**: set from the GUI, or edit `output_dir` in `config.toml`.
- **Cookies**: downloads use `--cookies-from-browser firefox` by default, so
  Firefox must be installed and logged into YouTube for age-restricted or
  private content to work. Change this in `app.py` if you use a different
  browser.
- **Logs**: every run's output is appended to `log.log`.
