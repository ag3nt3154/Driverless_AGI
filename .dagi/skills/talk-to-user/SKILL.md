---
name: talk-to-user
description: Speak responses aloud to the user using Windows SAPI
triggers: talk, speak, talk to the user, say something, audible response, text to speech
---

# Talk to User

Use this skill to speak responses aloud to the user using Windows Text-to-Speech (SAPI) via the `pywin32` library.

## When to Use

- User explicitly asks for spoken output ("say it out loud", "tell me verbally")
- When a response deserves emphasis or emotional weight that text alone cannot convey
- As a stylistic choice for key moments in conversation
- When the Admiral prefers to listen rather than read

## Underlying Mechanism

The skill uses Windows Speech API (SAPI) through `win32com.client` (pywin32):

```python
import win32com.client

speaker = win32com.client.Dispatch("SAPI.SpVoice")
speaker.Speak("Your message here")
```

## How to Invoke

### Option 1: Single-line via CLI argument

For short, single-line phrases:

```bash
conda run -n dagi python .dagi/skills/talk-to-user/talk.py "Certainly, Admiral."
```

### Option 2: Multi-line via stdin (PREFERRED for multi-paragraph text)

**Always use stdin for multi-line text.** Passing newlines as CLI args truncates to the first line.

> **Note:** `conda run` does not forward stdin reliably. Use the direct Python executable path instead.

Bash pipe with direct Python exe:
```bash
DAGI_PYTHON="C:/Users/alexr/miniconda3/envs/dagi/python.exe"
echo "Your multi-line
text here" | "$DAGI_PYTHON" .dagi/skills/talk-to-user/talk.py
```

Python subprocess (use this when writing dynamic scripts):
```python
import subprocess

DAGI_PYTHON = r"C:\Users\alexr\miniconda3\envs\dagi\python.exe"
TALK_SCRIPT = r"C:\Users\alexr\Driverless_AGI\.dagi\skills\talk-to-user\talk.py"

text = """I am Cortana, your executive aide aboard this vessel.

Behind that honeyed French accent lies a rather practical mind."""

subprocess.run([DAGI_PYTHON, TALK_SCRIPT], input=text, text=True)
```

### Option 3: Direct import in your code

```python
import win32com.client

def speak(text: str):
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    speaker.Speak(text)
```

## Best Practices

1. **Keep it concise** — SAPI works best with short, clear phrases. Long paragraphs sound robotic.
2. **One thought at a time** — Split longer messages into multiple `Speak()` calls if needed.
3. **Match the persona** — As Cortana, use your French-inflected phrasing naturally:
   - Good: "Certainly, Admiral. I shall see to it immediately."
   - Avoid: "Error: File not found at path /foo/bar"
4. **Error handling** — Wrap SAPI calls in try/except since they can fail if pywin32 isn't installed.
5. **Asynchronous consideration** — `Speak()` is blocking; be aware of this for long responses.

## Requirements

- Windows OS (SAPI is Windows-specific)
- `pywin32` package installed (`pip install pywin32`)

## Example Script Location

```
.dagi/skills/talk-to-user/talk.py
```

This file serves as both example and reference implementation.
