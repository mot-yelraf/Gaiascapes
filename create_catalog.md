# Create a Gaiascapes recording catalog

Act as a wildlife audio curator. Use the internet to find real animal vocalizations for **[animal or species]** for the **[Gaiascapes Sound Sources tile]**. Aim for **[number of recordings, regions, call types, and preferred clip lengths]**. If the user leaves preferences blank, aim for five recordings with contrasting call types and independent takes. Prefer complete sequences of calls over isolated sounds or long stretches of background noise. Ask which animal or tile the user wants if either is ambiguous.

## Find and check recordings

1. Start at original field-recording pages and institutional archives. Wikimedia Commons, Freesound, iNaturalist, Xeno-canto, and research repositories can help. Use an aggregator to discover material, then verify the file on the original source page. Include actual animal sounds such as calls, songs, rumbles, and choruses. Exclude imitations, synthetic audio, and clips dominated by unrelated wildlife, people, or machinery.
2. Verify the **license on each exact audio file**. Prefer public domain, CC0, CC BY, and CC BY-SA. Include CC BY-NC or CC BY-NC-SA if the user allows noncommercial recordings. Preserve the exact license and version. Access for listening, research, or download alone does not establish permission to redistribute. Exclude files whose reuse terms are absent or ambiguous. Keep original credits and record any processing already described by the source.
3. Verify the animal identity and the recording locality. Extract call type, date, behavior, wild or captive context, and scientific name where documented. Use the actual recording site, including a zoo or hydrophone site when appropriate. If the source identifies only a region, use a documented public map point for that region and label the coordinates as approximate. Respect obscured locations. If there is no defensible locality, leave the recording out and list it as a lead in your summary.
4. Fetch the public, unauthenticated **direct HTTPS audio URL** and confirm it returns the expected MP3 or WAV. Use the exact file that URL serves for the byte length and lowercase SHA-256 hash. Measure its duration using an audio tool. Audition the file if you can. If you can only verify the metadata and decode, say so in the summary. Leave files that require a login, expiring download link, archive extraction, or conversion out of this JSON-only catalog. Never substitute a preview URL without checking that the preview contains the intended call and carries reusable terms.
5. Look for a relevant, independently licensed picture for each recording when feasible. Prefer the recorded individual when a suitable picture exists. Otherwise use a correctly identified representative image and label it as such. Verify the original picture page, license and creator. Check the direct HTTPS URL, JPEG/PNG/WebP file type, byte length, and SHA-256. Omit the picture field when no suitable image can be verified. A Wikipedia article title may be supplied for Gaiascapes’ usual image lookup.
6. Deduplicate by original source recording ID and by audio hash. If the Gaiascapes checkout is available, compare against `src/gaiascapes_host/mammal_catalog.json`, `src/gaiascapes_host/commons_birdsong_catalog.json`, and `src/gaiascapes_host/sanctsound_catalog.json` as applicable. Also compare against any existing catalog the user supplies. Include only additions in the output. Avoid several excerpts from one take unless they are clearly distinct and the user asked for them.

## Choose the tile

Use one tile for the entire file. Match the selection to one of these `kind` values.

| Sound Sources tile | `kind` |
| --- | --- |
| Bears | `bear_calls` |
| Birdsong | `birdsong` |
| Canine Calls | `canine_calls` |
| Dolphin Calls | `dolphin_calls` |
| Elephants | `elephant_calls` |
| Feline Calls | `feline_calls` |
| Frog Calls | `frog_calls` |
| Primates | `primate_calls` |
| Whale Song | `whale_song` |

## Write the JSON

Save one UTF-8 JSON file named `gaiascapes-<kind>-catalog.json`. Use `format_version` of `1`, a descriptive `catalog_name`, the UTC date checked as `checked_at` in `YYYY-MM-DD` form, and a `recordings` array. Write valid JSON with no comments, trailing commas, non-finite numbers, or placeholder entries. Use the following recording fields. Their names follow Gaiascapes’ bundled `mammal_catalog.json`. Birdsong and marine provider catalogs have their own on-disk structures, so use this exchange format for them too.

The top-level JSON has this shape. Replace the example name and date and fill the array with verified recordings.

```json
{
  "format_version": 1,
  "catalog_name": "Elephant call sequences",
  "checked_at": "2026-01-01",
  "recordings": []
}
```

| Required recording field | Value |
| --- | --- |
| `id`, `kind`, `provider` | A stable, unique lowercase ID such as `freesound-103117`, the selected tile key, and a short source identifier such as `freesound`. |
| `common_name`, `wikipedia_title`, `title` | The animal name at the level supported by the source, the verified Wikipedia article title or an empty string, and the recording’s descriptive title. |
| `creator`, `license`, `license_url`, `source_url` | The recordist or credited source, the exact file license and its HTTPS terms URL, and the original HTTPS recording page. |
| `place`, `latitude`, `longitude` | The documented locality and numeric decimal degrees. Latitude must be within −90 to 90 and longitude within −180 to 180. |
| `coordinate_basis`, `coordinate_source`, `context` | Explain what the coordinates represent, give the HTTPS evidence URL, and describe the recording circumstances and call type as supported by the source. |
| `download_url`, `file`, `bytes`, `sha256` | The direct HTTPS audio URL, a plain filename such as `<id>.mp3` or `<id>.wav`, a positive integer byte length, and a 64-character lowercase hex SHA-256 digest of that audio. |
| `duration_seconds`, `media_version` | A positive numeric audio duration and a brief description of the source media version and known processing. |

For each optional field, omit it if the underlying fact is unavailable. Use `scientific_name`, `call_type`, `recorded_date` (ISO date), `recorded_time` (local time and time zone if documented), `recording_id` (original provider ID), `recording_medium`, or `review` as applicable. An optional `picture` object has `title`, `creator`, `license`, `license_url`, `source_url`, `download_url`, `file`, `bytes`, `sha256`, `alt`, and `context`. The text in `context` identifies the picture as the recorded individual or a representative image. Use a plain filename with the verified image extension and no path components.

## Deliver the catalog

Parse the JSON once before delivering it. Verify that the IDs and audio hashes are unique, all entries have the same `kind`, required metadata is present, and each linked file has the stated type, size and hash. Give the user the JSON file and a short summary of the number of verified recordings and pictures, call types, duration range, license restrictions and any gaps. If nothing qualifies, return an empty `recordings` array and explain what prevented verification. Never invent a recording, location, license, author, or hash to fill a gap.

To use the file, open **Settings → Sound sources**, select **import catalog** on the matching tile, choose the JSON file, and select **Import recordings**. Gaiascapes checks the selected tile for duplicates and stores the imported media with the installation. An empty result is a research report only and has no recordings to import.
