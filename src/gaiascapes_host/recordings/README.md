# Xiamen dolphin whistle samples

These four files contain Indo-Pacific humpback dolphin whistles from:

Weijie Fu, Xuming Peng, Fuxing Wu, Fei Zhang, Chuang Zhang, Wenjie Xiang,
Zhongchang Song, and Yu Zhang (2025). *Acoustic recordings of underwater
vocalizations of Indo-Pacific humpback dolphins in Xiamen Bay, China*.
Dataset: https://doi.org/10.6084/m9.figshare.29143727
Paper: https://doi.org/10.1038/s41597-025-06253-5

License: Creative Commons Attribution 4.0 International (CC BY 4.0):
https://creativecommons.org/licenses/by/4.0/

The sources are `Whistles/Whistle_006.wav`, `Whistles/Whistle_070.wav`,
`Whistles/Whistle_090.wav`, and `Whistles/Whistle_096.wav` in the dataset's
`Whistles.zip`. All four have quality grade 3 in `WhistleParameters.csv`.
The source recording numbers are respectively 6, 11, 13, and 14. Coordinates
and recording dates come from the corresponding rows in `Results.csv`.

Gaiascapes resampled the files to 48 kHz, 16-bit PCM for browser compatibility,
without changing playback speed. No synthesis, looping, or pitch shift was
applied. The source and derived checksums are retained in
`sanctsound_catalog.json`. These small samples are bundled to avoid downloading
the 129 MB source archive during playback.

The conversion was performed with macOS `afconvert`:

```sh
afconvert -f WAVE -d LEI16@48000 source.wav destination.wav
```
