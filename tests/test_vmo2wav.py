# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for vmo2wav. Run with: python3 -m unittest discover tests"""

import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "vmo2wav.py")
sys.path.insert(0, ROOT)

import vmo2wav  # noqa: E402


def gsm_frame_to_vmo(s, flag=0x20):
    """Inverse of vmo2wav.vmo_frame_to_gsm, used to build test input."""
    p = bytearray(34)
    for k in range(16):
        p[2 * k] = s[2 * k]
        p[2 * k + 3] = s[2 * k + 1]
    p[32] = s[32]
    p[1] = flag
    return bytes(p)


def random_gsm_frame(rng):
    s = bytearray(rng.getrandbits(8) for _ in range(33))
    s[0] = (s[0] & 0x0F) | 0xD0
    return bytes(s)


def random_vmo(frames, seed=1):
    rng = random.Random(seed)
    gsm = [random_gsm_frame(rng) for _ in range(frames)]
    return b"".join(gsm_frame_to_vmo(f) for f in gsm), b"".join(gsm)


class FrameMappingTest(unittest.TestCase):

    def test_known_frame(self):
        vmo = bytes(range(34))
        expected = bytearray([0, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10, 13, 12, 15,
                              14, 17, 16, 19, 18, 21, 20, 23, 22, 25, 24, 27,
                              26, 29, 28, 31, 30, 33, 32])
        expected[0] = 0xD0
        self.assertEqual(vmo2wav.vmo_frame_to_gsm(vmo), expected)

    def test_flag_byte_is_ignored(self):
        vmo = bytearray(range(34))
        a = vmo2wav.vmo_frame_to_gsm(bytes(vmo))
        vmo[1] = 0xFF
        self.assertEqual(vmo2wav.vmo_frame_to_gsm(bytes(vmo)), a)

    def test_round_trip(self):
        vmo, gsm = random_vmo(50)
        out, trailing = vmo2wav.vmo_to_gsm(vmo)
        self.assertEqual(out, gsm)
        self.assertEqual(trailing, 0)

    def test_trailing_bytes(self):
        vmo, gsm = random_vmo(3)
        out, trailing = vmo2wav.vmo_to_gsm(vmo + b"\x00" * 10)
        self.assertEqual(out, gsm)
        self.assertEqual(trailing, 10)

    def test_no_complete_frame(self):
        for data in (b"", b"\x00" * 33):
            with self.assertRaises(ValueError):
                vmo2wav.vmo_to_gsm(data)


class CommandLineTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.vmo, self.gsm = random_vmo(100)
        self.vmo_path = self.path("memo.vmo")
        with open(self.vmo_path, "wb") as f:
            f.write(self.vmo)

    def path(self, name):
        return os.path.join(self.dir, name)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)

    def test_gsm_output(self):
        proc = self.run_cli("--gsm", self.vmo_path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(self.path("memo.gsm"), "rb") as f:
            self.assertEqual(f.read(), self.gsm)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg not installed")
    def test_wav_output(self):
        proc = self.run_cli(self.vmo_path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(2.0 s)", proc.stdout)
        with wave.open(self.path("memo.wav")) as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getframerate(), 8000)
            self.assertEqual(w.getnframes(), 100 * 160)
        self.assertEqual(os.path.getsize(self.path("memo.wav")),
                         44 + 100 * 320)

    def test_existing_output_is_kept(self):
        out = self.path("memo.gsm")
        with open(out, "wb") as f:
            f.write(b"keep")
        proc = self.run_cli("--gsm", self.vmo_path)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("already exists", proc.stderr)
        with open(out, "rb") as f:
            self.assertEqual(f.read(), b"keep")
        proc = self.run_cli("--gsm", "-f", self.vmo_path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, "rb") as f:
            self.assertEqual(f.read(), self.gsm)

    def test_never_overwrites_input(self):
        proc = self.run_cli("--gsm", "-f", "-o", self.vmo_path, self.vmo_path)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("overwrite the input", proc.stderr)
        with open(self.vmo_path, "rb") as f:
            self.assertEqual(f.read(), self.vmo)

    def test_empty_file_fails(self):
        empty = self.path("empty.vmo")
        open(empty, "wb").close()
        proc = self.run_cli("--gsm", empty)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no complete", proc.stderr)
        self.assertFalse(os.path.exists(self.path("empty.gsm")))

    def test_missing_file_does_not_stop_others(self):
        proc = self.run_cli("--gsm", self.path("missing.vmo"), self.vmo_path)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(os.path.exists(self.path("memo.gsm")))

    def test_output_with_multiple_inputs_is_rejected(self):
        proc = self.run_cli("-o", "x.wav", self.vmo_path, self.vmo_path)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
