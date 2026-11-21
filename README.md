# vmo2wav

Convert Siemens `.vmo` voice memos to WAV.

Siemens phones from around 2001 (SL45, SL45i, ME45, S45 and others of the x45
generation) store dictaphone recordings as `.vmo` files. FFmpeg, SoX and
ordinary audio players can't read them. This is a small, dependency-free
Python script that can.

## Usage

Requirements: Python 3.6+ and [FFmpeg](https://ffmpeg.org/) (FFmpeg is not
needed with `--gsm`).

```sh
./vmo2wav.py memo.vmo              # writes memo.wav
./vmo2wav.py *.vmo                 # converts all files in the directory
./vmo2wav.py -o out.wav memo.vmo   # chooses the output name
./vmo2wav.py --gsm memo.vmo        # writes raw GSM (memo.gsm) instead
```

Existing output files are skipped unless you pass `-f`. Run
`./vmo2wav.py -h` to see all options.

The output is 8 kHz, 16-bit mono PCM, which is the native quality of the
recording.

## The format

A `.vmo` file has no header. It is a plain sequence of 34-byte frames, and
each frame holds 20 ms of GSM 06.10 Full Rate speech (the original 13 kbit/s
GSM codec). The 33 bytes of a standard libgsm frame are stored in a shuffled
order. Byte 1 of each frame is not part of the GSM data; it is typically
`0x20` and sometimes `0x00`, probably a voice activity flag.

To convert one VMO frame `p` to a libgsm frame `s`:

```
s[2k]   = p[2k]          for k = 0..15
s[2k+1] = p[2k+3]        for k = 0..15
s[32]   = p[32]
s[0]    = (s[0] & 0x0F) | 0xD0    # restore the libgsm 0xD magic nibble
```

The resulting stream is a standard raw `.gsm` file. FFmpeg decodes it with
`ffmpeg -f gsm -ar 8000 -i memo.gsm memo.wav`.

## Credits

The frame mapping comes from the `vmo2wav` converter in
[SieFS](https://github.com/tapwag/siefs/tree/master/converter), a Siemens
phone filesystem tool, which decodes the frames with a bundled copy of libgsm.
This repository reimplements that mapping in Python and uses FFmpeg's GSM
decoder.

## License

GPL-2.0-or-later, the same terms as SieFS. See [LICENSE](LICENSE).
