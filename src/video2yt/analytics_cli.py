"""Import, collect, and report video measurements without altering published videos."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.errors import HttpError

from video2yt import analytics


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='video2yt-analytics', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('import', 'collect', 'report'):
        sub = commands.add_parser(name)
        sub.add_argument('--receipt', type=Path, required=True, help='publication.json from upload or assets/publications')
        sub.add_argument('--analytics-dir', type=Path, default=Path('assets/analytics'))
        if name == 'report':
            sub.add_argument('--json', action='store_true', help='Machine-readable report including all snapshots')
        else:
            sub.add_argument('--window', choices=analytics.WINDOWS, required=True, help='Checkpoint since publication; API uses approximate calendar dates')
        if name == 'import':
            sub.add_argument('--input', type=Path, required=True, help='Canonical JSON or CSV; metric units in analytics module docstring')
            sub.add_argument('--start', required=True, help='Inclusive Pacific YYYY-MM-DD, or exact ISO timestamp')
            sub.add_argument('--end', required=True, help='Inclusive Pacific YYYY-MM-DD, or exclusive exact ISO timestamp')
            sub.add_argument('--window-kind', choices=('date_buckets', 'exact'), default='date_buckets')
            sub.add_argument('--collected-at', help='Original collection ISO timestamp with timezone (defaults to now)')
        if name == 'collect':
            sub.add_argument('--client-secret', type=Path, default=Path('client_secret.json'))
            sub.add_argument('--token', type=Path, default=Path('youtube_analytics_token.json'),
                             help='Dedicated cache basename must be youtube_analytics_token.json')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = json.loads(args.receipt.read_text(encoding='utf-8'))
        analytics.validate_receipt(receipt)
        if args.command == 'report':
            report = analytics.build_report(receipt, args.analytics_dir)
            print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else analytics.render_report(report))
            return 0
        if args.command == 'import':
            result = analytics.make_snapshot(receipt, analytics.read_import(args.input), window=args.window,
                start=args.start, end=args.end, kind=args.window_kind, collected_at=args.collected_at)
            result['imported_at'] = analytics.iso(datetime.now(timezone.utc))
            result['import_file'] = str(args.input.resolve())
        else:
            from googleapiclient.discovery import build
            credentials = analytics.get_credentials(args.client_secret, args.token)
            youtube = build('youtube', 'v3', credentials=credentials, cache_discovery=False)
            client = build('youtubeAnalytics', 'v2', credentials=credentials, cache_discovery=False)
            result = analytics.collect_snapshot(receipt, client, youtube, window=args.window)
        path = analytics.save_snapshot(result, args.analytics_dir)
        print(f'Measurement saved: {path}')
        return 0
    except (OSError, ValueError, RuntimeError, HttpError) as exc:
        print(f'[video2yt-analytics] {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
