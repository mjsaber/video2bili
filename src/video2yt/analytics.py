"""Local, provenance-preserving video measurement and read-only API collection.

API report combinations and Pacific date semantics:
https://developers.google.com/youtube/analytics/channel_reports
https://developers.google.com/youtube/analytics/dimensions#day
https://developers.google.com/youtube/analytics/reference/reports/query

Studio imports use canonical metric names (not arbitrary localized CSV exports).
Percentage fields are in percentage points, durations in seconds, watch time in
minutes. Unknown metrics stay null. Subscribers gained is gross, not net; API
video-filtered subscribers only include subscriptions from the watch page.
"""
from __future__ import annotations

import csv
import json
import math
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WINDOWS = {'24h': 24, '7d': 168, '28d': 672}
SCOPES = ['https://www.googleapis.com/auth/yt-analytics.readonly',
          'https://www.googleapis.com/auth/youtube.readonly']
METRICS = ('views', 'watch_minutes', 'average_view_duration_seconds',
           'retention_30s_pct', 'subscribers_gained', 'impressions',
           'impressions_ctr_pct', 'new_viewers')
API_METRICS = {'views': 'views', 'estimatedMinutesWatched': 'watch_minutes',
               'averageViewDuration': 'average_view_duration_seconds',
               'subscribersGained': 'subscribers_gained'}
PACIFIC = ZoneInfo('America/Los_Angeles')


def utc_time(value: str | datetime) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('timestamp must include timezone')
        return result.astimezone(timezone.utc)
    except (TypeError, AttributeError) as exc:
        raise ValueError('expected ISO timestamp including timezone') from exc


def iso(value: datetime) -> str:
    return utc_time(value).isoformat().replace('+00:00', 'Z')


def validate_receipt(receipt: dict) -> None:
    if not isinstance(receipt, dict):
        raise ValueError('publication receipt must be an object')
    for key in ('video_id', 'channel_id'):
        if not isinstance(receipt.get(key), str) or not re.fullmatch(r'[A-Za-z0-9_-]+', receipt[key]):
            raise ValueError(f'receipt requires a valid {key}')
    if receipt.get('status') not in ('uploaded', 'complete'):
        raise ValueError('receipt status must be uploaded or complete')
    utc_time(receipt.get('uploaded_at'))
    if receipt.get('published_at'):
        utc_time(receipt['published_at'])


def publication_reference(receipt: dict) -> tuple[datetime, str]:
    validate_receipt(receipt)
    key = 'published_at' if receipt.get('published_at') else 'uploaded_at'
    return utc_time(receipt[key]), key


def normalize_metrics(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError('metrics must be an object')
    extra = set(data) - set(METRICS)
    if extra:
        raise ValueError(f'unknown metric names: {sorted(extra)}')
    result = {}
    for key in METRICS:
        raw = data.get(key)
        if raw is None or raw == '':
            result[key] = None
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{key} must be a nonnegative finite number or null') from exc
        if isinstance(raw, bool) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{key} must be a nonnegative finite number or null')
        # Retention can exceed 100% when viewers replay a segment.
        if key == 'impressions_ctr_pct' and value > 100:
            raise ValueError('impressions_ctr_pct must be between 0 and 100')
        if key in ('views', 'subscribers_gained', 'impressions', 'new_viewers') and not value.is_integer():
            raise ValueError(f'{key} must be an integer count')
        result[key] = int(value) if value.is_integer() else value
    views, subscribers = result['views'], result['subscribers_gained']
    result['subscribers_per_1000_views'] = subscribers / views * 1000 if views and subscribers is not None else None
    return result


def read_import(path: Path) -> dict:
    if path.suffix.lower() == '.json':
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('import JSON must be an object with metrics and optional traffic_sources')
        return data
    if path.suffix.lower() != '.csv':
        raise ValueError('input must be .json or .csv')
    result = {'metrics': {}, 'traffic_sources': {}}
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or 'traffic_source' not in reader.fieldnames:
            raise ValueError('CSV requires traffic_source column; use total for overall metrics')
        seen = set()
        for row in reader:
            if None in row:
                raise ValueError('CSV row has more values than header columns')
            source = row.pop('traffic_source', '').strip()
            if not source or source in seen:
                raise ValueError(f'blank or duplicate traffic_source: {source}')
            seen.add(source)
            if source == 'total':
                result['metrics'] = row
            else:
                result['traffic_sources'][source] = row
    return result


def make_snapshot(receipt: dict, data: dict, *, window: str, start: str, end: str,
                  kind: str = 'date_buckets', collected_at: str | datetime | None = None,
                  source: str = 'studio_import') -> dict:
    reference, basis = publication_reference(receipt)
    if window not in WINDOWS:
        raise ValueError(f'window must be one of {list(WINDOWS)}')
    if not isinstance(data, dict) or set(data) - {'metrics', 'traffic_sources'}:
        raise ValueError('import contains only metrics and optional traffic_sources objects')
    collected = utc_time(collected_at) if collected_at else datetime.now(timezone.utc)
    target = reference + timedelta(hours=WINDOWS[window])
    if collected < reference:
        raise ValueError('collection precedes publication/upload')
    if kind == 'exact':
        if basis != 'published_at':
            raise ValueError('exact windows require confirmed published_at in the receipt')
        if utc_time(start) != reference or utc_time(end) != target:
            raise ValueError('exact interval must start at publication and end at the requested checkpoint')
        if utc_time(end) > collected:
            raise ValueError('measurement interval ends after collection')
        interval = {'kind': kind, 'start': iso(utc_time(start)), 'end': iso(utc_time(end)), 'timezone': 'UTC'}
    elif kind == 'date_buckets':
        begin, finish = date.fromisoformat(start), date.fromisoformat(end)
        if finish < begin:
            raise ValueError('end date precedes start date')
        if finish > collected.astimezone(PACIFIC).date():
            raise ValueError('measurement interval ends after collection')
        aligned = begin == reference.astimezone(PACIFIC).date() and finish == target.astimezone(PACIFIC).date()
        interval = {'kind': kind, 'start': start, 'end': end, 'timezone': 'America/Los_Angeles',
                    'checkpoint_coverage': 'checkpoint_dates_only' if aligned else 'partial_or_different_dates'}
    else:
        raise ValueError('window kind must be exact or date_buckets')
    traffic = data.get('traffic_sources', {})
    if not isinstance(traffic, dict):
        raise ValueError('traffic_sources must map source names to metric objects')
    metrics = normalize_metrics(data.get('metrics', {}))
    traffic_metrics = {name: normalize_metrics(values) for name, values in traffic.items()}
    measured = any(values[key] is not None
                   for values in [metrics, *traffic_metrics.values()] for key in METRICS)
    return {'schema_version': 1, 'video_id': receipt['video_id'], 'channel_id': receipt['channel_id'],
            'reference_at': iso(reference), 'reference_basis': basis,
            'window': window, 'checkpoint_at': iso(target), 'collected_at': iso(collected),
            'checkpoint_satisfied': kind == 'exact' and measured,
            'publication_age_hours_at_collection': (collected - reference).total_seconds() / 3600,
            'source': source, 'interval': interval,
            'metrics': metrics, 'traffic_sources': traffic_metrics}


def save_snapshot(snapshot: dict, root: Path = Path('assets/analytics')) -> Path:
    video_id = snapshot.get('video_id', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', video_id):
        raise ValueError('invalid video_id')
    folder = root / video_id
    folder.mkdir(parents=True, exist_ok=True)
    stamp = utc_time(snapshot['collected_at']).strftime('%Y%m%dT%H%M%S%fZ')
    path = folder / f'{stamp}-{snapshot["window"]}-{uuid.uuid4().hex[:8]}.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(snapshot, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    return path


def build_report(receipt: dict, root: Path = Path('assets/analytics'), *, now: datetime | None = None) -> dict:
    reference, basis = publication_reference(receipt)
    current = utc_time(now) if now else datetime.now(timezone.utc)
    snapshots = []
    for path in sorted((root / receipt['video_id']).glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('channel_id') != receipt['channel_id'] or data.get('video_id') != receipt['video_id']:
            raise ValueError(f'snapshot identity does not match receipt: {path}')
        snapshots.append(data)
    if basis == 'uploaded_at':
        confirmed = [s for s in snapshots if s.get('reference_basis') == 'published_at'
                     and s.get('publication_time_source') == 'youtube_public_video_snippet']
        if confirmed:
            latest = max(confirmed, key=lambda s: s['collected_at'])
            reference, basis = utc_time(latest['reference_at']), 'published_at'
    checkpoints = {}
    for window, hours in WINDOWS.items():
        relevant = [s for s in snapshots if s['window'] == window and s['reference_at'] == iso(reference)]
        exact = [s for s in relevant if s['interval']['kind'] == 'exact' and s.get('checkpoint_satisfied')]
        due = reference + timedelta(hours=hours)
        checkpoints[window] = {'at': iso(due), 'status': 'recorded' if exact else 'due' if current >= due else 'upcoming',
                               'exact_snapshots': len(exact),
                               'date_bucket_snapshots': sum(s['interval']['kind'] == 'date_buckets' for s in relevant)}
    return {'video_id': receipt['video_id'], 'channel_id': receipt['channel_id'],
            'reference_at': iso(reference), 'reference_basis': basis, 'generated_at': iso(current),
            'checkpoints': checkpoints, 'snapshots': snapshots}


def render_report(report: dict) -> str:
    lines = [f'Video: {report["video_id"]} | Channel: {report["channel_id"]}',
             f'Reference: {report["reference_at"]} ({report["reference_basis"]})']
    if report['reference_basis'] == 'uploaded_at':
        lines.append('Publication time is unconfirmed; ages and checkpoints use upload time as a proxy.')
    lines.append('Checkpoints:')
    for key, checkpoint in report['checkpoints'].items():
        lines.append(f'  {key}: {checkpoint["status"]} at {checkpoint["at"]}; '
                     f'{checkpoint["exact_snapshots"]} exact, {checkpoint["date_bucket_snapshots"]} date-bucket snapshots')
    for snapshot in report['snapshots']:
        interval = snapshot['interval']
        label = 'date buckets (not exact since-publication windows)' if interval['kind'] == 'date_buckets' else 'exact since publication'
        lines.extend(['', f'{snapshot["window"]} checkpoint | {snapshot["source"]} | collected {snapshot["collected_at"]}',
                      f'  Age at collection: {snapshot["publication_age_hours_at_collection"]:g} hours',
                      f'  {label}: {interval["start"]} through {interval["end"]} ({interval["timezone"]})'])
        if interval.get('checkpoint_coverage') == 'partial_or_different_dates':
            lines.append('  Coverage is partial or differs from the requested checkpoint dates.')
        if 'last_returned_day' in interval:
            lines.append(f'  Requested end: {interval["requested_end"]}; last returned day: {interval["last_returned_day"] or "unknown"}')
        for source, metrics in [('total', snapshot['metrics']), *snapshot['traffic_sources'].items()]:
            values = ', '.join(f'{key}={value if value is not None else "unknown"}' for key, value in metrics.items())
            lines.append(f'  {source}: {values}')
        for note in snapshot.get('notes', []):
            lines.append(f'  Note: {note}')
    if not report['snapshots']:
        lines.append('No measurement snapshots yet.')
    lines.append('Missing metrics are unknown. Subscribers/1000 views uses gross subscribers gained; API video attribution is watch-page only.')
    return '\n'.join(lines)


def _rows(response: dict) -> list[dict]:
    names = [column['name'] for column in response.get('columnHeaders', [])]
    return [dict(zip(names, row)) for row in response.get('rows', [])]


def _api_values(row: dict) -> dict:
    return {local: row.get(api) for api, local in API_METRICS.items()}


def collect_snapshot(receipt: dict, analytics, youtube, *, window: str,
                     now: datetime | None = None) -> dict:
    """Query totals and traffic separately; store returned dates, never exact hours."""
    reference, _ = publication_reference(receipt)
    if window not in WINDOWS:
        raise ValueError('invalid checkpoint window')
    current = utc_time(now) if now else datetime.now(timezone.utc)
    channels = youtube.channels().list(part='id', mine=True).execute().get('items', [])
    if receipt['channel_id'] not in {row['id'] for row in channels}:
        raise ValueError('authenticated channel does not match publication receipt')
    videos = youtube.videos().list(part='snippet,status', id=receipt['video_id']).execute().get('items', [])
    if len(videos) != 1 or videos[0]['snippet']['channelId'] != receipt['channel_id']:
        raise ValueError('video channel does not match publication receipt')
    receipt = dict(receipt)
    publication_time_source = None
    video = videos[0]
    if video.get('status', {}).get('privacyStatus') == 'public' and video['snippet'].get('publishedAt'):
        receipt['published_at'] = video['snippet']['publishedAt']
        reference, _ = publication_reference(receipt)
        publication_time_source = 'youtube_public_video_snippet'
    start = reference.astimezone(PACIFIC).date()
    end = min((reference + timedelta(hours=WINDOWS[window])).astimezone(PACIFIC).date(),
              current.astimezone(PACIFIC).date() - timedelta(days=1))
    if end < start:
        raise ValueError('no completed Pacific date buckets available yet')
    query = {'ids': f'channel=={receipt["channel_id"]}', 'filters': f'video=={receipt["video_id"]}',
             'startDate': start.isoformat(), 'endDate': end.isoformat()}
    metrics = ','.join(API_METRICS)
    daily_response = analytics.reports().query(**query, dimensions='day', metrics=metrics, sort='day').execute()
    daily = _rows(daily_response)
    last_day = max((row['day'] for row in daily), default=None)
    data = {'metrics': {}, 'traffic_sources': {}}
    raw = {'daily': daily_response}
    if last_day:
        query['endDate'] = last_day
        raw['totals'] = analytics.reports().query(**query, metrics=metrics).execute()
        totals = _rows(raw['totals'])
        if totals:
            data['metrics'] = _api_values(totals[0])
        # The video traffic-source report supports views and watch minutes,
        # but neither subscribersGained nor averageViewDuration.
        raw['traffic_sources'] = analytics.reports().query(**query, dimensions='insightTrafficSourceType',
            metrics='views,estimatedMinutesWatched').execute()
        data['traffic_sources'] = {row['insightTrafficSourceType']: _api_values(row)
                                  for row in _rows(raw['traffic_sources'])}
    result = make_snapshot(receipt, data, window=window, start=start.isoformat(),
        end=last_day or end.isoformat(), collected_at=current, source='youtube_analytics_api')
    result['interval'].update(requested_end=end.isoformat(), last_returned_day=last_day,
                              returned_days=[row['day'] for row in daily])
    if publication_time_source:
        result['publication_time_source'] = publication_time_source
    if not last_day:
        result['interval']['checkpoint_coverage'] = 'unknown'
    result['raw_reports'] = raw
    result['notes'] = ['Pacific daily buckets may include time beyond the checkpoint and exclude delayed data. '
                       'Returned days are observed coverage, not proof of complete reporting.',
                       'Impressions, impressions CTR, new viewers, and exact 30-second retention require a Studio import. '
                       'Retention curve samples are not interpolated into an exact 30-second measurement.']
    return result


def get_credentials(secret_path: Path, token_path: Path = Path('youtube_analytics_token.json')):
    """Use a dedicated read-only credential cache, never the uploader's token."""
    if token_path.name != 'youtube_analytics_token.json' or token_path.is_symlink():
        raise ValueError('analytics requires a separate youtube_analytics_token.json file')
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path))
        if set(credentials.scopes or []) != set(SCOPES):
            raise ValueError('analytics cache must contain only the two read-only scopes; use a separate cache directory')
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            credentials = None
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
        credentials = flow.run_local_server(port=0, prompt='consent')
    granted = getattr(credentials, 'granted_scopes', None)
    if set(granted if granted is not None else credentials.scopes or []) != set(SCOPES):
        raise ValueError('OAuth did not grant exactly the requested read-only scopes')
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding='utf-8')
    token_path.chmod(0o600)
    return credentials
