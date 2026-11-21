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

from __future__ import annotations

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
SAMPLE_RATE = 8000

FFMPEG_ARGS = [
    *["-nostdin", "-v", "error"],
    *["-f", "gsm", "-ar", "8000", "-i", "pipe:0"],  # raw GSM on stdin
    *["-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"],  # raw PCM on stdout
]


def vmo_frame_to_gsm(p: bytes) -> bytes:
    """Convert one 34-byte VMO frame to one 33-byte libgsm frame."""
    s = bytearray(GSM_FRAME_SIZE)
    for k in range(16):
        s[2 * k] = p[2 * k]
        s[2 * k + 1] = p[2 * k + 3]
    s[32] = p[32]
    # libgsm frames start with the 0xD magic nibble.
    s[0] = (s[0] & 0x0F) | 0xD0
    return bytes(s)


def vmo_to_gsm(data: bytes) -> tuple[bytes, int]:
    """Convert the contents of a .vmo file to raw libgsm data.

    Returns a (gsm_data, trailing_bytes) tuple, where trailing_bytes is the
    number of bytes at the end of the input that do not form a whole frame.
    Raises ValueError if the input contains no complete frame.
    """
    frames = len(data) // VMO_FRAME_SIZE
    if frames == 0:
        msg = (
            f"no complete {VMO_FRAME_SIZE}-byte frame found "
            "(empty file or not a .vmo file?)"
        )
        raise ValueError(msg)
    out = bytearray()
    for start in range(0, frames * VMO_FRAME_SIZE, VMO_FRAME_SIZE):
        end = start + VMO_FRAME_SIZE
        out += vmo_frame_to_gsm(data[start:end])
    return bytes(out), len(data) % VMO_FRAME_SIZE


def gsm_to_pcm(gsm: bytes, ffmpeg: str) -> bytes:
    """Decode raw libgsm data to 8 kHz 16-bit mono PCM using FFmpeg."""
    proc = subprocess.run(
        [ffmpeg, *FFMPEG_ARGS], input=gsm, capture_output=True, check=False
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        msg = f"FFmpeg failed: {detail or f'exit code {proc.returncode}'}"
        raise RuntimeError(msg)
    return proc.stdout


def write_output(path: str, data: bytes, *, wav: bool) -> None:
    """Write data to path as raw bytes or as a mono 16-bit WAV file.

    The data is written to a temporary .part file first, so path is only
    replaced once the whole file has been written successfully.
    """
    tmp_path = path + ".part"
    try:
        if wav:
            with wave.open(tmp_path, "wb") as w:
                # pylint infers wave.open() as Wave_read whatever the mode.
                # pylint: disable=no-member
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(data)
        else:
            with open(tmp_path, "wb") as f:
                f.write(data)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def convert(
    path: str, out_path: str, *, ffmpeg: str | None, force: bool
) -> float:
    """Convert one .vmo file and return the duration of the audio in seconds.

    Writes raw GSM if ffmpeg is None, otherwise a WAV file decoded with the
    given FFmpeg executable. Raises OSError, ValueError or RuntimeError.
    """
    if os.path.exists(out_path):
        if os.path.exists(path) and os.path.samefile(path, out_path):
            msg = "output would overwrite the input file"
            raise ValueError(msg)
        if not force:
            msg = f"{out_path} already exists (use -f to overwrite)"
            raise ValueError(msg)
    with open(path, "rb") as f:
        gsm, trailing = vmo_to_gsm(f.read())
    if trailing:
        print(
            f"{path}: warning: ignoring {trailing} trailing bytes "
            "(file may be truncated)",
            file=sys.stderr,
        )
    if ffmpeg is None:
        write_output(out_path, gsm, wav=False)
    else:
        write_output(out_path, gsm_to_pcm(gsm, ffmpeg), wav=True)
    return len(gsm) // GSM_FRAME_SIZE * FRAME_DURATION


def main() -> int:
    """Run the command-line interface and return the exit status."""
    parser = argparse.ArgumentParser(
        description="Convert Siemens .vmo voice memos (GSM 06.10 Full Rate) "
        "to 8 kHz mono WAV, or to raw .gsm with --gsm.",
        epilog="example: %(prog)s *.vmo  (memo.vmo is converted to memo.wav)",
    )
    parser.add_argument(
        "files", nargs="+", metavar="FILE.vmo", help="input .vmo file(s)"
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="output file (only with a single input file); "
        "default: input name with .wav/.gsm extension",
    )
    parser.add_argument(
        "--gsm",
        action="store_true",
        help="write raw libgsm .gsm instead of WAV (no FFmpeg needed); "
        "decode later with 'ffmpeg -f gsm -ar 8000 -i FILE.gsm FILE.wav'",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite existing output files",
    )
    parser.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        metavar="PATH",
        help="FFmpeg executable (default: %(default)s)",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    args = parser.parse_args()

    if args.output and len(args.files) > 1:
        parser.error("--output can only be used with a single input file")
    if not args.gsm and not shutil.which(args.ffmpeg):
        parser.error(
            f"FFmpeg not found ('{args.ffmpeg}'); install it, "
            "pass --ffmpeg PATH, or use --gsm"
        )

    ffmpeg = None if args.gsm else args.ffmpeg
    ext = ".gsm" if args.gsm else ".wav"
    status = 0
    for path in args.files:
        out_path = args.output or os.path.splitext(path)[0] + ext
        try:
            seconds = convert(path, out_path, ffmpeg=ffmpeg, force=args.force)
        except (OSError, ValueError, RuntimeError) as e:
            print(f"{path}: error: {e}", file=sys.stderr)
            status = 1
        else:
            print(f"{path} -> {out_path} ({seconds:.1f} s)")
    return status


if __name__ == "__main__":
    sys.exit(main())
