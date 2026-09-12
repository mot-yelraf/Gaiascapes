# Mammal recording curation — initial source audit

The mammal sources will use only fixed sites where approved recordings exist.
They will not expose a location selector or require all 19 original anchors to
be populated. The 19-site comparison below remains research provenance, not a
requirement to search those sites at playback time.

Checked 2026-09-12. This document retains the initial shortlist. Nine candidates
have since been promoted into a bundled starter catalog; see the
[per-file credits and review limits](../../src/gaiascapes_host/recordings/MAMMAL_CREDITS.md)
and [runtime manifest](../../src/gaiascapes_host/mammal_catalog.json).
Public high-quality MP3 derivatives are used, not login-gated original uploads.
Unused candidates below remain research-only.

User listening feedback on the PoC rejects `freesound-818986` as a suitable
elephant-call example: other wildlife dominates the clip. Its source description
and successful decode were insufficient to establish listening suitability.
Replace it before treating the elephant collection as curated and approved.

Free-license candidates exist in all four requested groups. The strongest match to an existing Gaiascapes region is the bonnet macaque recording near Tambdi Surla in Goa. Most other candidates belong to different locations. No complete 19-location collection has been verified for any of these groups.

## Location basis

This audit uses the 19 terrestrial locations in `src/gaiascapes_host/commons_birdsong_catalog.json`, with its existing 100 km radius. Gaiascapes currently has other, different 19-site catalogs for other sounds; there is not one universal set of 19 recording coordinates. The JSON retains all 19 terrestrial IDs and coordinates unchanged, with empty candidate lists where evidence is missing.

A named recording site, a species range, and a game location are different things. A tiger recorded in Kentucky cannot be presented as an Indian field recording. An elephant recording from Samburu cannot be relabeled Nairobi. Unmatched recordings stay unassigned.

## Candidates

Each linked page supplies the recording description and stated license. Identity and context below are provisional where noted. None has received a listening-quality review. Freesound pages offer previews, but original downloads require login; no account was used or created.

| Group | Recording / source | Reported site | Stated license | Curation note |
| --- | --- | --- | --- | --- |
| Feline | [Lion — Lion roars 1.wav](https://freesound.org/people/eardeer/sounds/458903/) | Ukutula Game Reserve, South Africa | CC BY 4.0 | Reserve recording; confirm captive/managed status. Not Kruger. |
| Feline | [Lion — Lion roars 2.wav](https://freesound.org/people/eardeer/sounds/458902/) | Ukutula Game Reserve, South Africa | CC BY 4.0 | Alternate clip at same site; confirm captive/managed status. |
| Feline | [Tiger — Tiger Roar](https://freesound.org/people/lauramellis/sounds/263115/) | Louisville Zoo, Kentucky, USA | CC0 | Must be mapped to the zoo, not Asia. Subspecies not verified. |
| Feline | [Lion — Lion raring-sound1TamilNadu178.ogg](https://commons.wikimedia.org/wiki/File:Lion_raring-sound1TamilNadu178.ogg) | Unverified | Public domain | Filename mentions Tamil Nadu, but no verified recording coordinates/site. Do not assign to Goa or Karnataka. |
| Feline | [Mountain lion — Mountain lion growl](https://www.nps.gov/subjects/sound/clips.htm) | Unverified | NPS-authored; file rights verification pending | Download listed on official NPS page. Educational program context alone does not establish the recording location. |
| Canine | [Gray wolf — Wolf howls.ogg](https://commons.wikimedia.org/wiki/File:Wolf_howls.ogg) | Unverified | Public domain (US federal work) | Recording locality and captive/wild context are not specified. |
| Canine | [Dingo — Dingo’s in Yuendumu](https://freesound.org/people/kangaroovindaloo/sounds/517552/) | Yuendumu, Northern Territory, Australia | CC BY 4.0 | Pack near recordist bungalow; no claim of wild status. Not Sydney or Cooya Pooya. |
| Canine | [Fox — vixen calling](https://freesound.org/people/AndrewJonesFoto/sounds/362127/) | The Rower, Kilkenny, Ireland | CC BY 4.0 | Recordist identifies fox, tentatively a vixen; species and caller sex not independently verified. |
| Canine | [Coyote — coyotes howling](https://freesound.org/people/SamsterBirdies/sounds/640060/) | Davenport, Washington, USA | CC0 | Recordist reports post-processing in Audacity. |
| Canine | [Coyote — Coyotes 2.mp3](https://freesound.org/people/robertjd/sounds/69584/) | Banff, Alberta, Canada | CC0 | Howling at a train; assess train contamination before selecting an excerpt. |
| Elephant | [Elephant (African species needs confirmation) — Night in the Serengeti with elephant rumble](https://freesound.org/people/zachrau/sounds/818986/) | Mara, Tanzania / Serengeti | CC0 | Rumble described at about 5 seconds; crickets and birds also present. Not Nairobi/Kilifi. |
| Elephant | [African savanna elephant — Animal-borne acoustic recordings of African elephant vocalizations from Samburu National Reserve, Kenya](https://datadryad.org/dataset/doi:10.5061/dryad.xd2547dz3) | Samburu National Reserve, Kenya | CC0 (Dryad publication terms) | Dataset, not a selected clip. 1,123 extracted WAV clips; select a high-quality example and retain file ID. License policy: https://datadryad.org/terms . No GPS fixes verified; do not invent precise coordinates. |
| Elephant | [Elephant (Asian category; identity needs confirmation) — Elephant voice - trumpeting.ogg](https://commons.wikimedia.org/wiki/File:Elephant_voice_-_trumpeting.ogg) | Unverified | CC0 | Page categorized Elephas maximus, but no verified locality or Indian subspecies. Hold for identity/location verification. |
| Primate | [Bonnet macaque — Bonnet Macaque Alarm Call @ GoaMarch 9 2013](https://freesound.org/people/Calcuttan/sounds/187587/) | Forest near Tambdi Surla, Bhagwan Mahavir Wildlife Sanctuary, Goa, India | CC BY 4.0 | Single-sound map center 15.3886461578622, 74.17522430419922; approximately 1.2 km from existing Molem anchor. Map center precision is not GPS accuracy. Needs audio review and original acquisition. |
| Primate | [Howler monkey (species unresolved) — Howler monkey howling in the evening jungle](https://freesound.org/people/zachrau/sounds/812933/) | Near Monteverde, Costa Rica | CC0 | Not the existing Rancho Naturalista region; retain actual site. |
| Primate | [Howler monkey (species unresolved) — Howler monkey and other monkey or bird.wav](https://freesound.org/people/sethlind/sounds/332718/) | Osa Peninsula, Costa Rica | CC0 | Secondary caller unresolved. Not Rancho Naturalista. |
| Primate | [Howler monkey (species unresolved) — howler_monkey_jungle_4.wav](https://freesound.org/people/itsmrjack/sounds/123044/) | Palenque, Chiapas, Mexico (source spells Polenque) | CC0 | Needs audio review, exact site metadata, and species confirmation. |
| Primate | [Howler monkey (species unresolved) — Howler Monkeys](https://freesound.org/people/Lenguaverde/sounds/490315/) | San José, Petén, Guatemala | CC0 | Needs audio review, exact site metadata, and species confirmation. |
| Primate | [Howler monkey (species unresolved) — Howler Monkeys](https://freesound.org/people/FlyingMarmot/sounds/414248/) | Lamanai ruins, Belize | CC0 | Needs audio review, exact site metadata, and species confirmation. |
| Primate | [Gibbon (species unresolved) — Gibbon Monkey.mp3](https://freesound.org/people/Bidone/sounds/67355/) | Unverified | CC0 | Gibbons are apes. Site and species require confirmation; do not infer a recording location from species range. |
| Primate | [Primate (identity unresolved) — Affen schreit.mp3](https://freesound.org/people/Bidone/sounds/67361/) | Leipzig Zoo, Germany | CC0 | Tags suggest chimpanzee, but description only identifies monkey; hold species label pending verification. |
| Primate | [Monkey (species unresolved) — monkeys-1.wav](https://freesound.org/people/xserra/sounds/93993/) | Galta hill, Jaipur, Rajasthan, India | CC BY 4.0 | Not either existing India region. |
| Primate | [Monkey (species unresolved) — kerala-4.wav](https://freesound.org/people/xserra/sounds/320507/) | Thekkady, Kerala, India | CC BY 4.0 | Mixed monkeys and birds; identify a suitable segment. Not either existing India region. |

## Existing-region result

| Existing region | Initial result |
| --- | --- |
| Churchill, Manitoba, Canada | No verified recording match in this search |
| Goulds, Newfoundland, Canada | No verified recording match in this search |
| Rancho Naturalista, Costa Rica | No verified recording match in this search |
| Tapichalaca Reserve, Ecuador | No verified recording match in this search |
| Napo Galeras, Ecuador | No verified recording match in this search |
| Atlantic Forest, São Paulo, Brazil | No verified recording match in this search |
| Almeirim, Pará, Brazil | No verified recording match in this search |
| Finca El Candado, Salta, Argentina | No verified recording match in this search |
| Wrocław, Poland | No verified recording match in this search |
| Ballochbuie, Scotland | No verified recording match in this search |
| Oujda, Morocco | No verified recording match in this search |
| Nairobi, Kenya | No verified recording match in this search |
| Kilifi, Kenya | No verified recording match in this search |
| Chikballapur, Karnataka, India | No verified recording match in this search |
| Molem National Park, Goa, India | Bonnet macaque metadata candidate; audio review pending |
| Kruger National Park, South Africa | No verified recording match in this search |
| Sydney, New South Wales, Australia | No verified recording match in this search |
| Cooya Pooya, Pilbara, Australia | No verified recording match in this search |
| Ocean Beach, Stewart Island, New Zealand | No verified recording match in this search |

The Goa recording is described by the recordist as a forest alarm call near Tambdi Surla. Its [single-recording map](https://freesound.org/people/Calcuttan/sounds/187587/geotag/?ajax=1) is centered at approximately 15.38865, 74.17522, about 1.2 km from the existing Molem anchor. Treat this as published map evidence, not an accuracy claim for a GPS fix.

## Unresolved and excluded sources

- **Indian elephants:** no India-specific, species-verified, freely reusable recording with suitable locality evidence was established in this pass. The [LDC Asian Elephant Vocalizations collection](https://catalog.ldc.upenn.edu/LDC2010S05) contains real Sri Lankan recordings, but is distributed under an LDC agreement, not a verified open-content license. It is not included as a freely redistributable source.
- **African elephant dataset:** the [Samburu Dryad dataset](https://datadryad.org/dataset/doi:10.5061/dryad.xd2547dz3) offers extracted WAV clips. Dryad’s [publication terms](https://datadryad.org/terms) provide for CC0 release. Select individual calls and retain their annotation/file identifiers; the whole dataset is not one game sound.
- **Tiger identification:** [Tiger Mad.ogg](https://commons.wikimedia.org/wiki/File:Tiger_Mad.ogg) describes an uncertain tiger-like sound. Excluded from species-approved candidates.
- **Human/prop imitations:** exclude [Man howls like wolf](https://commons.wikimedia.org/wiki/File:Man_howls_like_wolf.ogg), [Monkey Imitation 2](https://freesound.org/people/AntumDeluge/sounds/417816/), and [ElephantTrumpetCall](https://freesound.org/people/AdrianaSpalinky/sounds/52249/). Their descriptions explicitly identify imitation or prop-made sound.
- **Heavily altered/restricted audio:** [Large Wolf Howl](https://freesound.org/people/adrilahan/sounds/172652/) is pitch-shifted and CC BY-NC, so is excluded from the open reusable field collection.
- **Captive animals:** retain clearly marked zoo candidates as a separate review pool. Whether to include them in the final collection has not been decided. Ukutula’s managed/captive context also needs confirmation.

## Promotion into the runtime catalog

1. Confirm species, actual site, captive/wild context, and license from original provenance. A generic elephant or monkey label does not justify a species/subspecies announcement.
2. Obtain the original licensed recording; retain creator, source page, license URL, file ID, and checksum.
3. Listen and inspect the file for a clear animal call, clipping, excessive speech/music, and misleading processing. Preserve an original and document any trim, gain adjustment, or conversion.
4. Match only documented recording sites to the existing regions. Keep gaps empty and skip unavailable groups rather than substituting sounds from elsewhere.
5. Add approved recordings to the existing image, announcement, Sequential/Random, Reveal/Hide, and Next flows only after metadata and audio review are complete.

No runtime source tile, playback behavior, installed setting, or curated audio catalog was changed by this research.
