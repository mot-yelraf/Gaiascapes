"""Measure curated birdsong loudness and quiet stretches without changing audio.

FFmpeg is a maintenance tool only, not an application dependency. Point this
command at disposable copies of recordings; it performs no network requests,
playback, normalization, or writes to the installed media directory.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess


FILTER = ('aresample=48000,asetnsamples=n=48000:p=0,'
          'astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level,'
          'ebur128=framelog=verbose:peak=sample,volumedetect')


def quality_issues(analysis):
    """Flag extreme levels or long near-silent stretches for curated playback."""
    issues = []
    if analysis['mean_dbfs'] < -45:
        issues.append('average_below_minus45_dbfs')
    if analysis['integrated_lufs'] < -45:
        issues.append('loudness_below_minus45_lufs')
    if analysis['integrated_lufs'] > -12:
        issues.append('loudness_above_minus12_lufs')
    if analysis['longest_quiet_seconds'] >= 20:
        issues.append('quiet_stretch_at_least20_seconds')
    return issues


def parse_analysis(log):
    """Extract full-file levels and time-weighted one-second quiet measurements."""
    def last(pattern):
        values = re.findall(pattern, log)
        if not values:
            raise ValueError('FFmpeg did not produce complete loudness measurements')
        return float(values[-1])

    times = re.findall(r'\btime=(\d+):(\d+):(\d+(?:\.\d+)?)', log)
    if not times:
        raise ValueError('FFmpeg did not report decoded duration')
    h, m, s = map(float, times[-1])
    duration = h * 3600 + m * 60 + s
    levels = [max(-120., float(value)) for value in re.findall(
        r'lavfi\.astats\.Overall\.RMS_level=(-inf|[-\d.]+)', log)]
    if duration <= 0 or not levels:
        raise ValueError('No decoded audio samples')
    quiet = longest = run = 0.
    for index, level in enumerate(levels):
        seconds = max(0., min(1., duration - index))
        if level < -50:
            quiet += seconds
            run += seconds
            longest = max(longest, run)
        else:
            run = 0.
    return {'duration_seconds': round(duration, 2),
            'mean_dbfs': last(r'mean_volume:\s*([-\d.]+) dB'),
            'peak_dbfs': last(r'max_volume:\s*([-\d.]+) dB'),
            'integrated_lufs': last(r'\bI:\s*([-\d.]+) LUFS'),
            'quiet_fraction_below_minus50_dbfs': round(quiet / duration, 4),
            'longest_quiet_seconds': round(longest, 2),
            'loudest_second_dbfs': round(max(levels), 2),
            'one_second_rms_dbfs': [round(value, 2) for value in levels]}


def analyze_audio(path, ffmpeg):
    """Decode a full file and retain measurements and its exact source hash."""
    result = subprocess.run([str(ffmpeg), '-hide_banner', '-nostdin', '-nostats', '-xerror',
        '-i', str(path), '-map', '0:a:0', '-vn', '-af', FILTER, '-f', 'null', '-'],
        capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Audio decode failed: ' + result.stderr[-1500:])
    report = parse_analysis(result.stderr)
    report['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    report['bytes'] = path.stat().st_size
    return report


def main():
    """Audit every catalog entry against private media copies and write JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=Path(__file__).resolve().parents[1] /
                        'src/gaiascapes_host/commons_birdsong_catalog.json')
    parser.add_argument('--media-dir', type=Path, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.media_dir.resolve()):
        parser.error('Write reports outside the media directory')
    rows = []
    for location in json.loads(args.catalog.read_text())['locations']:
        for recording in location['recordings']:
            rows.append({'region_id': location['id'], **recording})

    def measure(row):
        slug = row['region_id'] + '-XC' + row['recording_id']
        metadata_path = args.media_dir / (slug + '.json')
        try:
            metadata = json.loads(metadata_path.read_text())
            path = args.media_dir / metadata['file']
            if not path.is_file():
                raise FileNotFoundError(str(path))
            if metadata.get('size') and path.stat().st_size != metadata['size']:
                raise ValueError('File size differs from source metadata')
            analysis = analyze_audio(path, args.ffmpeg)
            return {**row, 'analysis': analysis, 'quality_issues': quality_issues(analysis)}
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return {**row, 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(measure, rows))
    report = {'recording_count': len(results), 'quiet_window_threshold_dbfs': -50,
              'measurements': results}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f"Analyzed {len(results)} entries; {sum('error' in row for row in results)} errors; {args.output}")
    return 1 if any('error' in row for row in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
