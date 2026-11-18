# Curated birdsong audio quality

The 2026-11-17 audit checked all 68 original recordings, screened replacement
candidates, and verified the final 68 recordings across the same 19 regions.
The catalog excludes both Sydney Sonus naturalis soundscapes (XC442361 and
XC442377). In total, 15 very quiet files and one unusually loud file were replaced
by 16 geographically documented recordings. Region centers and the one-visit-per-
region rotation are unchanged; the number of available recordings per region can
vary.

The project screening limits are:

- Average signal level of at least −45 dBFS.
- Integrated loudness from −45 through −12 LUFS.
- No continuous stretch of 20 seconds or longer whose one-second RMS windows
  remain below −50 dBFS.
- Successful full-file decoding, a complete download, and unique audio content.

These checks retain ordinary pauses between calls. They screen extreme levels;
the recordings keep their original dynamics and are not volume-normalized.
FFmpeg's `volumedetect`, `astats`, and `ebur128` filters supply the measurements.
The maintenance tool is separate from the app; FFmpeg is not needed for playback.

Three otherwise usable Ogg recordings (XC112714, XC125715, and XC134748) have
Commons-provided MP3 derivatives. Older WebKit on the macOS 12 test host cannot
play Ogg, so setup downloads those MP3s and retains the original source-page
attribution. Existing Ogg files are preserved, while cache metadata switches to
the complete MP3 download. No provider credentials are required.

[The machine-readable audit](birdsong-quality-audit.json) lists every accepted
file's source, duration, levels, quiet fraction, longest quiet stretch, and
SHA-256, plus the excluded entries and replacement IDs. Candidate downloads were
also checked against Wikimedia's published size and SHA-1 when available.
All added recordings have supported reuse licenses and documented coordinates
within 100 km of their existing catalog region.

To repeat the measurements against disposable copies of the media cache:

```sh
python scripts/audit_birdsong_loudness.py \
  --media-dir /tmp/gaiascapes-audit/media/birdsong \
  --ffmpeg /path/to/ffmpeg \
  --output /tmp/gaiascapes-audit/report.json
```

Do not point profiling servers at installed runtime data. The audit command is
read-only with respect to its media input and writes its report separately.

References: [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html),
[Commons audio derivatives API](https://www.mediawiki.org/wiki/Extension:TimedMediaHandler/API).

## Excluded recordings

| XC | Recording | Mean dBFS | LUFS | Reason |
|---|---|---:|---:|---|
| 564600 | [Sterna paradisaea - Arctic Tern XC564600](https://commons.wikimedia.org/wiki/File:Sterna_paradisaea_-_Arctic_Tern_XC564600.mp3) | -17.5 | -8.9 | Very loud |
| 611988 | [Myadestes melanops - Black-faced Solitaire XC611988](https://commons.wikimedia.org/wiki/File:Myadestes_melanops_-_Black-faced_Solitaire_XC611988.mp3) | -52.4 | -46.3 | Very quiet |
| 433671 | [Turdus albicollis - White-necked Thrush XC433671](https://commons.wikimedia.org/wiki/File:Turdus_albicollis_-_White-necked_Thrush_XC433671.mp3) | -32.4 | -46.6 | Very quiet |
| 433995 | [Myiothlypis rivularis - Riverbank Warbler XC433995](https://commons.wikimedia.org/wiki/File:Myiothlypis_rivularis_-_Riverbank_Warbler_XC433995.mp3) | -48.8 | -47.6 | Very quiet |
| 468594 | [Turdus torquatus - Ring Ouzel XC468594](https://commons.wikimedia.org/wiki/File:Turdus_torquatus_-_Ring_Ouzel_XC468594.mp3) | -45.1 | -38.9 | Very quiet |
| 364472 | [Passer rufocinctus - Kenya Sparrow XC364472](https://commons.wikimedia.org/wiki/File:Passer_rufocinctus_-_Kenya_Sparrow_XC364472.mp3) | -49.1 | -49.6 | Very quiet |
| 364474 | [Lybius leucocephalus - White-headed Barbet XC364474](https://commons.wikimedia.org/wiki/File:Lybius_leucocephalus_-_White-headed_Barbet_XC364474.mp3) | -52.7 | -50.8 | Very quiet |
| 364568 | [Ploceus xanthops - Holub's Golden Weaver XC364568](https://commons.wikimedia.org/wiki/File:Ploceus_xanthops_-_Holub%27s_Golden_Weaver_XC364568.mp3) | -51.1 | -51.2 | Very quiet |
| 336949 | [Iduna rama - Sykes's Warbler XC336949](https://commons.wikimedia.org/wiki/File:Iduna_rama_-_Sykes%27s_Warbler_XC336949.mp3) | -48.7 | -45.5 | Very quiet |
| 336956 | [Alauda gulgula - Oriental Skylark XC336956](https://commons.wikimedia.org/wiki/File:Alauda_gulgula_-_Oriental_Skylark_XC336956.mp3) | -49.8 | -46.5 | Very quiet |
| 336958 | [Galerida deva - Sykes's Lark XC336958](https://commons.wikimedia.org/wiki/File:Galerida_deva_-_Sykes%27s_Lark_XC336958.mp3) | -57.0 | -55.1 | Very quiet |
| 336960 | [Taccocua leschenaultii - Sirkeer Malkoha XC336960](https://commons.wikimedia.org/wiki/File:Taccocua_leschenaultii_-_Sirkeer_Malkoha_XC336960.mp3) | -58.3 | -55.3 | Very quiet |
| 444233 | [Cercotrichas leucophrys - White-browed Scrub Robin XC444233](https://commons.wikimedia.org/wiki/File:Cercotrichas_leucophrys_-_White-browed_Scrub_Robin_XC444233.mp3) | -45.1 | -40.0 | Very quiet |
| 442361 | [Sonus naturalis - Soundscape XC442361](https://commons.wikimedia.org/wiki/File:Sonus_naturalis_-_Soundscape_XC442361.mp3) | -64.0 | -51.4 | Very quiet |
| 442377 | [Sonus naturalis - Soundscape XC442377](https://commons.wikimedia.org/wiki/File:Sonus_naturalis_-_Soundscape_XC442377.mp3) | -45.8 | -40.1 | Very quiet |
| 496422 | [Ptilotula keartlandi - Grey-headed Honeyeater XC496422](https://commons.wikimedia.org/wiki/File:Ptilotula_keartlandi_-_Grey-headed_Honeyeater_XC496422.mp3) | -46.4 | -44.0 | Very quiet |

## Added recordings

| XC | Recording | Region | Mean dBFS | LUFS |
|---|---|---|---:|---:|
| 433997 | [Crypturellus tataupa - Tataupa Tinamou XC433997](https://commons.wikimedia.org/wiki/File:Crypturellus_tataupa_-_Tataupa_Tinamou_XC433997.mp3) | brazil-atlantic-forest | -41.7 | -41.1 |
| 437665 | [Hylophilus poicilotis - Rufous-crowned Greenlet XC437665](https://commons.wikimedia.org/wiki/File:Hylophilus_poicilotis_-_Rufous-crowned_Greenlet_XC437665.mp3) | brazil-atlantic-forest | -35.9 | -36.2 |
| 112727 | [Nothoprocta pentlandii - Andean Tinamou XC112727](https://commons.wikimedia.org/wiki/File:Nothoprocta_pentlandii_-_Andean_Tinamou_XC112727.mp3) | argentina-finca-el-candado | -32.5 | -27.1 |
| 468919 | [Phylloscopus trochilus - Willow Warbler XC468919](https://commons.wikimedia.org/wiki/File:Phylloscopus_trochilus_-_Willow_Warbler_XC468919.mp3) | scotland-ballochbuie | -23.1 | -12.8 |
| 372271 | [Bycanistes brevis - Silvery-cheeked Hornbill XC372271](https://commons.wikimedia.org/wiki/File:Bycanistes_brevis_-_Silvery-cheeked_Hornbill_XC372271.mp3) | kenya-nairobi | -30.0 | -26.8 |
| 366678 | [Onychognathus morio - Red-winged Starling XC366678](https://commons.wikimedia.org/wiki/File:Onychognathus_morio_-_Red-winged_Starling_XC366678.mp3) | kenya-nairobi | -37.9 | -38.2 |
| 370903 | [Cossypha semirufa - Rüppell's Robin-Chat XC370903](https://commons.wikimedia.org/wiki/File:Cossypha_semirufa_-_R%C3%BCppell%27s_Robin-Chat_XC370903.mp3) | kenya-nairobi | -41.9 | -37.9 |
| 376080 | [Uraeginthus bengalus - Red-cheeked Cordon-bleu XC376080](https://commons.wikimedia.org/wiki/File:Uraeginthus_bengalus_-_Red-cheeked_Cordon-bleu_XC376080.mp3) | kenya-nairobi | -40.1 | -39.0 |
| 538779 | [Pycnonotus jocosus - Red-whiskered Bulbul XC538779](https://commons.wikimedia.org/wiki/File:Pycnonotus_jocosus_-_Red-whiskered_Bulbul_XC538779.mp3) | india-chikballapur | -34.1 | -26.7 |
| 356035 | [Galloperdix spadicea - Red Spurfowl XC356035](https://commons.wikimedia.org/wiki/File:Galloperdix_spadicea_-_Red_Spurfowl_XC356035.mp3) | india-chikballapur | -28.0 | -24.7 |
| 456500 | [Mirafra passerina - Monotonous Lark XC456500](https://commons.wikimedia.org/wiki/File:Mirafra_passerina_-_Monotonous_Lark_XC456500.mp3) | south-africa-kruger-national-park | -37.7 | -30.2 |
| 463923 | [Cisticola chiniana - Rattling Cisticola XC463923](https://commons.wikimedia.org/wiki/File:Cisticola_chiniana_-_Rattling_Cisticola_XC463923.mp3) | south-africa-kruger-national-park | -21.0 | -16.1 |
| 463924 | [Emberiza tahapisi - Cinnamon-breasted Bunting XC463924](https://commons.wikimedia.org/wiki/File:Emberiza_tahapisi_-_Cinnamon-breasted_Bunting_XC463924.mp3) | south-africa-kruger-national-park | -35.4 | -34.4 |
| 442964 | [Menura novaehollandiae - Superb Lyrebird XC442964](https://commons.wikimedia.org/wiki/File:Menura_novaehollandiae_-_Superb_Lyrebird_XC442964.mp3) | australia-sydney | -31.5 | -31.2 |
| 446209 | [Pardalotus punctatus - Spotted Pardalote XC446209](https://commons.wikimedia.org/wiki/File:Pardalotus_punctatus_-_Spotted_Pardalote_XC446209.mp3) | australia-sydney | -32.4 | -32.5 |
| 492324 | [Ptilotula penicillata - White-plumed Honeyeater XC492324](https://commons.wikimedia.org/wiki/File:Ptilotula_penicillata_-_White-plumed_Honeyeater_XC492324.mp3) | australia-cooya-pooya | -37.2 | -32.7 |
