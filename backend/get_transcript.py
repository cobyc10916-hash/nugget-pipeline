#!/usr/bin/env python3
"""Print a YouTube transcript (via the Webshare proxy). Used by the Max routine (PROMPT.md)."""
import sys
from pipeline import transcript

if len(sys.argv) < 2:
    sys.exit("usage: python get_transcript.py <video_id>")
print(transcript(sys.argv[1]))
