# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for vmo2wav. Run with "python3 -m unittest" from the repo root."""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

import vmo2wav

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "vmo2wav.py")

EXIT_ERROR = 1
EXIT_USAGE = 2


def gsm_frame_to_vmo(s: bytes, flag: int = 0x20) -> bytes:
    """Inverse of vmo2wav.vmo_frame_to_gsm, used to build test input."""
    p = bytearray(34)
    for k in range(16):
        p[2 * k] = s[2 * k]
        p[2 * k + 3] = s[2 * k + 1]
    p[32] = s[32]
    p[1] = flag
    return bytes(p)


def random_gsm_frame(rng: random.Random) -> bytes:
    """Return a random libgsm frame with a valid magic nibble."""
    s = bytearray(rng.getrandbits(8) for _ in range(33))
    s[0] = (s[0] & 0x0F) | 0xD0
    return bytes(s)


def random_vmo(frames: int, seed: int = 1) -> tuple[bytes, bytes]:
    """Return random (vmo_data, expected_gsm_data) with the given length."""
    rng = random.Random(seed)
    gsm = [random_gsm_frame(rng) for _ in range(frames)]
    return b"".join(gsm_frame_to_vmo(f) for f in gsm), b"".join(gsm)


class FrameMappingTest(unittest.TestCase):
    """Tests for the conversion of VMO frames to libgsm frames."""

    def test_known_frame(self) -> None:
        vmo = bytes(range(34))
        expected = bytes.fromhex(
            "d0 03 02 05 04 07 06 09 08 0b 0a 0d 0c 0f 0e 11 10 "
            "13 12 15 14 17 16 19 18 1b 1a 1d 1c 1f 1e 21 20"
        )
        self.assertEqual(vmo2wav.vmo_frame_to_gsm(vmo), expected)

    def test_flag_byte_is_ignored(self) -> None:
        vmo = bytearray(range(34))
        a = vmo2wav.vmo_frame_to_gsm(bytes(vmo))
        vmo[1] = 0xFF
        self.assertEqual(vmo2wav.vmo_frame_to_gsm(bytes(vmo)), a)

    def test_round_trip(self) -> None:
        vmo, gsm = random_vmo(50)
        out, trailing = vmo2wav.vmo_to_gsm(vmo)
        self.assertEqual(out, gsm)
        self.assertEqual(trailing, 0)

    def test_trailing_bytes(self) -> None:
        vmo, gsm = random_vmo(3)
        out, trailing = vmo2wav.vmo_to_gsm(vmo + b"\x00" * 10)
        self.assertEqual(out, gsm)
        self.assertEqual(trailing, 10)

    def test_no_complete_frame(self) -> None:
        for data in (b"", b"\x00" * 33):
            with self.assertRaises(ValueError):
                vmo2wav.vmo_to_gsm(data)


class CommandLineTest(unittest.TestCase):
    """End-to-end tests that run vmo2wav.py as a separate process."""

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.vmo, self.gsm = random_vmo(100)
        self.vmo_path = self.path("memo.vmo")
        with open(self.vmo_path, "wb") as f:
            f.write(self.vmo)

    def path(self, name: str) -> str:
        """Return the path of a file in the test's temporary directory."""
        return os.path.join(self.dir, name)

    def read(self, name: str) -> bytes:
        """Return the contents of a file in the temporary directory."""
        with open(self.path(name), "rb") as f:
            return f.read()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run vmo2wav.py with the given arguments and capture its output."""
        return subprocess.run(
            [sys.executable, SCRIPT, *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_gsm_output(self) -> None:
        proc = self.run_cli("--gsm", self.vmo_path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read("memo.gsm"), self.gsm)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg not installed")
    def test_wav_output(self) -> None:
        proc = self.run_cli(self.vmo_path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(2.0 s)", proc.stdout)
        with wave.open(self.path("memo.wav")) as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getframerate(), 8000)
            self.assertEqual(w.getnframes(), 100 * 160)
        # A plain 44-byte WAV header with no extra metadata chunks.
        self.assertEqual(len(self.read("memo.wav")), 44 + 100 * 320)

    def test_existing_output_is_kept(self) -> None:
        with open(self.path("memo.gsm"), "wb") as f:
            f.write(b"keep")
        proc = self.run_cli("--gsm", self.vmo_path)
        self.assertEqual(proc.returncode, EXIT_ERROR)
        self.assertIn("already exists", proc.stderr)
        self.assertEqual(self.read("memo.gsm"), b"keep")
        proc = self.run_cli("--gsm", "-f", self.vmo_path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read("memo.gsm"), self.gsm)

    def test_never_overwrites_input(self) -> None:
        proc = self.run_cli("--gsm", "-f", "-o", self.vmo_path, self.vmo_path)
        self.assertEqual(proc.returncode, EXIT_ERROR)
        self.assertIn("overwrite the input", proc.stderr)
        self.assertEqual(self.read("memo.vmo"), self.vmo)

    def test_empty_file_fails(self) -> None:
        with open(self.path("empty.vmo"), "wb"):
            pass
        proc = self.run_cli("--gsm", self.path("empty.vmo"))
        self.assertEqual(proc.returncode, EXIT_ERROR)
        self.assertIn("no complete", proc.stderr)
        self.assertFalse(os.path.exists(self.path("empty.gsm")))

    def test_missing_file_does_not_stop_others(self) -> None:
        proc = self.run_cli("--gsm", self.path("missing.vmo"), self.vmo_path)
        self.assertEqual(proc.returncode, EXIT_ERROR)
        self.assertEqual(self.read("memo.gsm"), self.gsm)

    def test_output_with_multiple_inputs_is_rejected(self) -> None:
        proc = self.run_cli("-o", "x.wav", self.vmo_path, self.vmo_path)
        self.assertEqual(proc.returncode, EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
