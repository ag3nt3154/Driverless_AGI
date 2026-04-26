"""
Talk to User - Windows SAPI Text-to-Speech Interface
Usage: python talk.py "Your message here"
"""

import sys
import win32com.client


def speak(text: str) -> bool:
    """Speak the given text using Windows SAPI."""
    try:
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        speaker.Speak(text)
        return True
    except Exception as e:
        print(f"Speech error: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        text = " ".join(sys.argv[1:])
    else:
        text = sys.stdin.read().strip()

    if not text:
        print('Usage: python talk.py "Your message" OR echo "text" | python talk.py')
        sys.exit(1)

    success = speak(text)
    sys.exit(0 if success else 1)
