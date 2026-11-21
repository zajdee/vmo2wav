#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Convert Siemens .vmo voice memos to WAV (or raw GSM).

Siemens x45-era phones (such as the SL45, SL45i and ME45) store dictaphone
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
import wave

__version__ = "1.0.0"

VMO_FRAME_SIZE = 34
GSM_FRAME_SIZE = 33
FRAME_DURATION = 0.02  # seconds of audio per frame


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
    """Convert the contents of a .vmo file to raw libgsm data.

    Returns a (gsm_data, trailing_bytes) tuple, where trailing_bytes is the
    number of bytes at the end of the input that do not form a whole frame.
    Raises ValueError if the input contains no complete frame.
    """
    frames = len(data) // VMO_FRAME_SIZE
    if frames == 0:
        raise ValueError(f"no complete {VMO_FRAME_SIZE}-byte frame found "
                         "(empty file or not a .vmo file?)")
    out = bytearray()
    for off in range(0, frames * VMO_FRAME_SIZE, VMO_FRAME_SIZE):
        out += vmo_frame_to_gsm(data[off:off + VMO_FRAME_SIZE])
    return bytes(out), len(data) % VMO_FRAME_SIZE


def gsm_to_pcm(gsm, ffmpeg):
    """Decode raw libgsm data to 8 kHz 16-bit mono PCM using FFmpeg."""
    proc = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-f", "gsm", "-ar", "8000",
         "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"],
        input=gsm, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"FFmpeg failed: {msg or f'exit code {proc.returncode}'}")
    return proc.stdout


def write_output(path, gsm=None, pcm=None):
    """Write raw GSM or a WAV file, replacing path only on success."""
    tmp_path = path + ".part"
    try:
        if pcm is None:
            with open(tmp_path, "wb") as f:
                f.write(gsm)
        else:
            with wave.open(tmp_path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(pcm)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Convert Siemens .vmo voice memos (GSM 06.10 Full Rate) "
                    "to 8 kHz mono WAV, or to raw .gsm with --gsm.",
        epilog="example: %(prog)s *.vmo  (memo.vmo is converted to memo.wav)")
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
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
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
        try:
            if os.path.exists(out_path):
                if os.path.exists(path) and os.path.samefile(path, out_path):
                    raise ValueError("output would overwrite the input file")
                if not args.force:
                    raise ValueError(f"{out_path} already exists "
                                     "(use -f to overwrite)")
            with open(path, "rb") as f:
                gsm, trailing = vmo_to_gsm(f.read())
            if trailing:
                print(f"{path}: warning: ignoring {trailing} trailing bytes "
                      "(file may be truncated)", file=sys.stderr)
            if args.gsm:
                write_output(out_path, gsm=gsm)
            else:
                write_output(out_path, pcm=gsm_to_pcm(gsm, args.ffmpeg))
        except (OSError, ValueError, RuntimeError) as e:
            print(f"{path}: error: {e}", file=sys.stderr)
            status = 1
            continue
        seconds = len(gsm) // GSM_FRAME_SIZE * FRAME_DURATION
        print(f"{path} -> {out_path} ({seconds:.1f} s)")
    return status


if __name__ == "__main__":
    sys.exit(main())
