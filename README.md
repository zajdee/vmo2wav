# vmo2wav

Convert Siemens `.vmo` voice memos to WAV.

Siemens phones from around 2001 (the SL45, SL45i, ME45 and other phones of the
x45 generation) store dictaphone recordings as `.vmo` files. FFmpeg, SoX and
ordinary audio players can't read them. `vmo2wav.py` is a single Python
script with no dependencies beyond FFmpeg, and it can.

## Requirements

- Python 3.6 or newer (tested with 3.9 to 3.14)
- [FFmpeg](https://ffmpeg.org/) for WAV output. It is not needed with `--gsm`.

## Usage

```sh
./vmo2wav.py memo.vmo              # writes memo.wav
./vmo2wav.py *.vmo                 # converts every .vmo file in the directory
./vmo2wav.py -o out.wav memo.vmo   # sets the output file name
./vmo2wav.py --gsm memo.vmo        # writes raw GSM (memo.gsm) instead of WAV
```

The output is an 8 kHz, 16-bit, mono PCM WAV file, which is the native quality
of the recording.

- Existing output files are never overwritten unless you pass `-f`.
- The input file is never overwritten, even with `-f`.
- If one file fails, the others are still converted, and the script exits
  with status 1.

Run `./vmo2wav.py --help` for all options.

## File format

A `.vmo` file has no header. It is a sequence of 34-byte frames, and each frame
holds 20 ms of GSM 06.10 Full Rate speech (the original 13 kbit/s GSM codec).
The frame stores the 33 bytes of a standard libgsm frame in a shuffled order.
Byte 1 of each frame is not part of the GSM data. It is usually `0x20` and
sometimes `0x00`, possibly a voice activity flag.

This is how one VMO frame `p` becomes one libgsm frame `s`:

```
s[2k]   = p[2k]          for k = 0..15
s[2k+1] = p[2k+3]        for k = 0..15
s[32]   = p[32]
s[0]    = (s[0] & 0x0F) | 0xD0    # restore the 0xD magic nibble of libgsm
```

The result is a standard raw `.gsm` stream. To decode it with FFmpeg:
`ffmpeg -f gsm -ar 8000 -i memo.gsm memo.wav`.

## Tests

```sh
python3 -m unittest discover tests
```

The tests use synthetic frames, so they need no sample recordings. The WAV
test is skipped if FFmpeg is not installed.

## Credits

The frame mapping comes from the `vmo2wav` converter in
[SieFS](https://github.com/tapwag/siefs/tree/master/converter), a filesystem
tool for Siemens phones. That converter decodes the frames with a bundled copy
of libgsm. This project reimplements the mapping in Python and uses FFmpeg's
GSM decoder. On real recordings its output matches the SieFS converter to
within one step of GSM's 13-bit sample resolution (a ±8 difference in 16-bit
samples), which is a rounding difference between the two GSM decoders.

## License

GPL-2.0-or-later, the same license as SieFS. See [LICENSE](LICENSE).
