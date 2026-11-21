#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Convert Siemens .vmo voice memos to WAV (or raw GSM).

Siemens x45-era phones (SL45, SL45i, ME45, S45, ...) store dictaphone
recordings as .vmo files. These contain GSM 06.10 Full Rate speech in
34-byte frames (20 ms each) whose bytes are shuffled relative to the
standard 33-byte libgsm frame layout. This tool reorders the bytes back
into standard libgsm frames and lets FFmpeg decode them to 8 kHz mono WAV.

The byte mapping comes from the vmo2wav converter in the SieFS project
(https://github.com/tapwag/siefs, converter/vmconvert.c).
"""

import argparse
import os
import shutil
import subprocess
import sys

VMO_FRAME_SIZE = 34
GSM_FRAME_SIZE = 33


def vmo_frame_to_gsm(p):
    """Convert one 34-byte VMO frame to one 33-byte libgsm frame."""
    s = bytearray(GSM_FRAME_SIZE)
    for k in range(16):
        s[2 * k] = p[2 * k]
        s[2 * k + 1] = p[2 * k + 3]
    s[32] = p[32]
    # libgsm frames start with the 0xD magic nibble.
    s[0] = (s[0] & 0x0F) | 0xD0
    return s


def vmo_to_gsm(data):
    """Convert the contents of a .vmo file to raw libgsm data."""
    if len(data) % VMO_FRAME_SIZE:
        print(f"warning: {len(data) % VMO_FRAME_SIZE} trailing bytes ignored",
              file=sys.stderr)
    out = bytearray()
    for off in range(0, len(data) - VMO_FRAME_SIZE + 1, VMO_FRAME_SIZE):
        out += vmo_frame_to_gsm(data[off:off + VMO_FRAME_SIZE])
    return bytes(out)


def gsm_to_wav(gsm, wav_path, ffmpeg):
    """Decode raw libgsm data to a WAV file using FFmpeg."""
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "gsm", "-ar", "8000",
         "-i", "pipe:0", wav_path],
        input=gsm, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Convert Siemens .vmo voice memos (GSM 06.10 Full Rate) "
                    "to WAV, or to raw .gsm with --gsm.",
        epilog="Example: %(prog)s *.vmo   (writes memo.wav next to memo.vmo)")
    parser.add_argument("files", nargs="+", metavar="FILE.vmo",
                        help="input .vmo file(s)")
    parser.add_argument("-o", "--output", metavar="PATH",
                        help="output file (only with a single input file); "
                             "default: input name with .wav/.gsm extension")
    parser.add_argument("--gsm", action="store_true",
                        help="write raw libgsm .gsm instead of WAV "
                             "(no FFmpeg needed); decode later with "
                             "'ffmpeg -f gsm -ar 8000 -i FILE.gsm FILE.wav'")
    parser.add_argument("-f", "--force", action="store_true",
                        help="overwrite existing output files")
    parser.add_argument("--ffmpeg", default="ffmpeg", metavar="PATH",
                        help="FFmpeg executable (default: %(default)s)")
    args = parser.parse_args()

    if args.output and len(args.files) > 1:
        parser.error("--output can only be used with a single input file")
    if not args.gsm and not shutil.which(args.ffmpeg):
        parser.error(f"FFmpeg not found ('{args.ffmpeg}'); install it, "
                     "pass --ffmpeg PATH, or use --gsm")

    ext = ".gsm" if args.gsm else ".wav"
    status = 0
    for path in args.files:
        out_path = args.output or os.path.splitext(path)[0] + ext
        if os.path.exists(out_path) and not args.force:
            print(f"{path}: {out_path} exists, skipping (use -f to overwrite)",
                  file=sys.stderr)
            status = 1
            continue
        try:
            with open(path, "rb") as f:
                gsm = vmo_to_gsm(f.read())
            if args.gsm:
                with open(out_path, "wb") as f:
                    f.write(gsm)
            else:
                gsm_to_wav(gsm, out_path, args.ffmpeg)
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"{path}: error: {e}", file=sys.stderr)
            status = 1
            continue
        seconds = len(gsm) // GSM_FRAME_SIZE * 0.02
        print(f"{path} -> {out_path} ({seconds:.1f} s)")
    return status


if __name__ == "__main__":
    sys.exit(main())
