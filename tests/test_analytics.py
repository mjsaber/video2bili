"""Offline tests for measurement provenance, intervals, and read-only queries."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def test_analytics_module_exists():
    assert importlib.util.find_spec('video2yt.analytics') is not None


def analytics():
    from video2yt import analytics
    return analytics


@pytest.fixture
def receipt():
    return {'video_id': 'abcdefghijk', 'channel_id': 'UCchannel',
            'uploaded_at': '2026-08-01T12:00:00Z',
            'published_at': '2026-08-01T12:00:00Z', 'status': 'complete'}


def snapshot(receipt, **kwargs):
    return analytics().make_snapshot(receipt, {'metrics': {'views': 1000, 'subscribers_gained': 3}},
        window='24h', start='2026-08-01', end='2026-08-02',
        collected_at='2026-08-04T12:00:00Z', **kwargs)


def test_missing_metrics_remain_null_and_ratio_is_derived(receipt):
    result = snapshot(receipt)
    assert result['metrics']['subscribers_per_1000_views'] == 3
    assert result['metrics']['watch_minutes'] is None
    assert result['metrics']['retention_30s_pct'] is None
    assert result['interval']['kind'] == 'date_buckets'
    assert result['interval']['timezone'] == 'America/Los_Angeles'
    assert result['publication_age_hours_at_collection'] == 72


@pytest.mark.parametrize('views', [0, None])
def test_ratio_unknown_for_zero_or_missing_denominator(receipt, views):
    result = analytics().make_snapshot(receipt, {'metrics': {'views': views, 'subscribers_gained': 3}},
        window='24h', start='2026-08-01', end='2026-08-02', collected_at='2026-08-04T12:00:00Z')
    assert result['metrics']['subscribers_per_1000_views'] is None


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, 'abc'])
def test_invalid_metrics_rejected(receipt, value):
    with pytest.raises(ValueError, match='views'):
        analytics().make_snapshot(receipt, {'metrics': {'views': value}}, window='24h',
            start='2026-08-01', end='2026-08-02', collected_at='2026-08-04T12:00:00Z')


def test_exact_interval_requires_correct_publication_bounds(receipt):
    result = analytics().make_snapshot(receipt, {}, window='24h',
        start='2026-08-01T12:00:00Z', end='2026-08-02T12:00:00Z',
        kind='exact', collected_at='2026-08-04T12:00:00Z')
    assert result['interval']['kind'] == 'exact'
    with pytest.raises(ValueError, match='publication'):
        analytics().make_snapshot(receipt, {}, window='24h', kind='exact',
            start='2026-08-01T00:00:00Z', end='2026-08-02T00:00:00Z')
    receipt.pop('published_at')
    with pytest.raises(ValueError, match='published_at'):
        analytics().make_snapshot(receipt, {}, window='24h', kind='exact',
            start='2026-08-01T12:00:00Z', end='2026-08-02T12:00:00Z')


def test_json_csv_import_and_duplicate_source_rejection(tmp_path):
    source = tmp_path / 'studio.csv'
    source.write_text('traffic_source,views,watch_minutes,impressions_ctr_pct\ntotal,1000,200,5.2\nBROWSE,200,,\n')
    data = analytics().read_import(source)
    assert data['metrics']['impressions_ctr_pct'] == '5.2'
    assert data['traffic_sources']['BROWSE']['watch_minutes'] == ''
    source.write_text('traffic_source,views\ntotal,1\ntotal,2\n')
    with pytest.raises(ValueError, match='duplicate'):
        analytics().read_import(source)
    source = tmp_path / 'studio.json'
    source.write_text(json.dumps({'metrics': {'views': 100}}))
    assert analytics().read_import(source)['metrics']['views'] == 100


def test_archive_preserves_snapshots_and_report_due_checkpoints(receipt, tmp_path):
    first = analytics().save_snapshot(snapshot(receipt), tmp_path)
    second = analytics().save_snapshot(snapshot(receipt), tmp_path)
    assert first != second
    assert first.parent.name == receipt['video_id']
    report = analytics().build_report(receipt, tmp_path,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc))
    assert len(report['snapshots']) == 2
    assert report['checkpoints']['7d']['status'] == 'due'
    assert report['checkpoints']['28d']['status'] == 'upcoming'
    assert report['checkpoints']['24h']['status'] == 'due'
    assert report['checkpoints']['24h']['date_bucket_snapshots'] == 2
    text = analytics().render_report(report)
    assert 'not exact' in text
    assert 'unknown' in text
    assert '2026-08-01' in text


def test_reject_path_traversal_and_invalid_receipts(receipt):
    receipt['video_id'] = '../evil'
    with pytest.raises(ValueError, match='video_id'):
        snapshot(receipt)


class Request:
    def __init__(self, response):
        self.response = response
    def execute(self):
        return self.response


class FakeYoutube:
    def __init__(self, channel='UCchannel', video_channel='UCchannel'):
        self.channel = channel
        self.video_channel = video_channel
    def channels(self):
        return self
    def videos(self):
        return self
    def list(self, **kwargs):
        if kwargs.get('mine'):
            return Request({'items': [{'id': self.channel}]})
        return Request({'items': [{'id': 'abcdefghijk', 'snippet': {'channelId': self.video_channel}}]})


class FakeAnalytics:
    def __init__(self, empty=False):
        self.calls = []
        self.empty = empty
    def reports(self):
        return self
    def query(self, **kwargs):
        self.calls.append(kwargs)
        dims = kwargs.get('dimensions', '')
        metrics = kwargs['metrics'].split(',')
        values = dict(views=100, estimatedMinutesWatched=20, averageViewDuration=12, subscribersGained=2)
        if dims == 'day':
            rows = [['2026-08-01'] + [values[m] for m in metrics]]
        elif dims == 'insightTrafficSourceType':
            rows = [['YT_SEARCH'] + [values[m] for m in metrics]]
        else:
            rows = [[values[m] for m in metrics]]
        names = ([dims] if dims else []) + metrics
        return Request({'columnHeaders': [{'name': n} for n in names], 'rows': [] if self.empty else rows})


def test_live_collect_valid_queries_record_delay_and_null_studio_metrics(receipt):
    client = FakeAnalytics()
    result = analytics().collect_snapshot(receipt, client, FakeYoutube(), window='24h',
        now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc))
    assert result['metrics']['views'] == 100
    assert result['metrics']['impressions_ctr_pct'] is None
    assert result['traffic_sources']['YT_SEARCH']['views'] == 100
    assert result['interval']['last_returned_day'] == '2026-08-01'
    assert result['interval']['requested_end'] == '2026-08-02'
    assert result['interval']['kind'] == 'date_buckets'
    assert all(c['filters'] == 'video==abcdefghijk' for c in client.calls)
    traffic = next(c for c in client.calls if c.get('dimensions') == 'insightTrafficSourceType')
    assert 'subscribersGained' not in traffic['metrics']
    assert traffic['endDate'] == '2026-08-01'


def test_live_missing_rows_never_become_zero(receipt):
    result = analytics().collect_snapshot(receipt, FakeAnalytics(empty=True), FakeYoutube(), window='24h',
        now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc))
    assert result['metrics']['views'] is None
    assert result['interval']['last_returned_day'] is None


@pytest.mark.parametrize('youtube', [FakeYoutube(channel='other'), FakeYoutube(video_channel='other')])
def test_channel_mismatch_blocks_analytics_queries(receipt, youtube):
    client = FakeAnalytics()
    with pytest.raises(ValueError, match='channel'):
        analytics().collect_snapshot(receipt, client, youtube, window='24h')
    assert not client.calls


def test_cli_import_report_remains_offline(receipt, tmp_path, capsys):
    from video2yt.analytics_cli import main
    path = tmp_path / 'publication.json'
    path.write_text(json.dumps(receipt))
    data = tmp_path / 'data.json'
    data.write_text('{"metrics": {"views": 10}}')
    root = tmp_path / 'analytics'
    assert main(['import', '--receipt', str(path), '--input', str(data), '--analytics-dir', str(root),
        '--window', '24h', '--start', '2026-08-01', '--end', '2026-08-02']) == 0
    assert main(['report', '--receipt', str(path), '--analytics-dir', str(root), '--json']) == 0
    assert 'views' in capsys.readouterr().out


def test_oauth_rejects_upload_token_before_reading(tmp_path):
    path = tmp_path / 'youtube_token.json'
    path.write_text('upload token sentinel')
    with pytest.raises(ValueError, match='separate'):
        analytics().get_credentials(tmp_path / 'secret.json', path)
    assert path.read_text() == 'upload token sentinel'


def test_traffic_query_only_requests_documented_video_metrics(receipt):
    client = FakeAnalytics()
    result = analytics().collect_snapshot(receipt, client, FakeYoutube(), window='24h',
        now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc))
    traffic = next(c for c in client.calls if c.get('dimensions') == 'insightTrafficSourceType')
    assert set(traffic['metrics'].split(',')) <= {'views', 'engagedViews', 'estimatedMinutesWatched'}
    assert result['traffic_sources']['YT_SEARCH']['average_view_duration_seconds'] is None


def test_import_records_original_collection_and_import_timestamps(receipt, tmp_path):
    from video2yt.analytics_cli import main
    receipt_path = tmp_path / 'publication.json'
    receipt_path.write_text(json.dumps(receipt))
    source = tmp_path / 'data.json'
    source.write_text('{"metrics": {"views": 100, "retention_30s_pct": 62.5}}')
    main(['import', '--receipt', str(receipt_path), '--input', str(source), '--analytics-dir', str(tmp_path / 'data'),
          '--window', '24h', '--start', '2026-08-01', '--end', '2026-08-02',
          '--collected-at', '2026-08-04T12:00:00Z'])
    stored = json.loads(next((tmp_path / 'data' / receipt['video_id']).glob('*.json')).read_text())
    assert stored['collected_at'] == '2026-08-04T12:00:00Z'
    assert stored['imported_at'] != stored['collected_at']
    assert stored['import_file'] == str(source.resolve())


def test_malformed_csv_row_is_rejected(tmp_path):
    path = tmp_path / 'bad.csv'
    path.write_text('traffic_source,views\ntotal,5,unlabeled\n')
    with pytest.raises(ValueError, match='CSV'):
        analytics().read_import(path)


def test_partial_date_import_never_completes_later_checkpoint(receipt, tmp_path):
    result = analytics().make_snapshot(receipt, {'metrics': {'views': 10}}, window='28d',
        start='2026-08-01', end='2026-08-01', collected_at='2026-09-01T12:00:00Z')
    analytics().save_snapshot(result, tmp_path)
    report = analytics().build_report(receipt, tmp_path, now=datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert report['checkpoints']['28d']['status'] == 'due'
    assert result['interval']['checkpoint_coverage'] == 'partial_or_different_dates'
    assert result['checkpoint_satisfied'] is False


class PublicYoutube(FakeYoutube):
    def list(self, **kwargs):
        response = super().list(**kwargs)
        if not kwargs.get('mine'):
            response.response['items'][0]['snippet']['publishedAt'] = '2026-08-01T18:00:00Z'
            response.response['items'][0]['status'] = {'privacyStatus': 'public'}
        return response


def test_live_publication_time_enriches_snapshot_without_mutating_receipt(receipt, tmp_path):
    receipt.pop('published_at')
    result = analytics().collect_snapshot(receipt, FakeAnalytics(), PublicYoutube(), window='24h',
        now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc))
    assert result['reference_basis'] == 'published_at'
    assert result['reference_at'] == '2026-08-01T18:00:00Z'
    assert result['publication_age_hours_at_collection'] == 66
    assert 'published_at' not in receipt
    analytics().save_snapshot(result, tmp_path)
    report = analytics().build_report(receipt, tmp_path)
    assert report['reference_basis'] == 'published_at'
    assert report['checkpoints']['24h']['at'] == '2026-08-02T18:00:00Z'


def test_live_private_publication_time_stays_upload_proxy(receipt):
    class PrivateYoutube(PublicYoutube):
        def list(self, **kwargs):
            response = super().list(**kwargs)
            if not kwargs.get('mine'):
                response.response['items'][0]['status']['privacyStatus'] = 'private'
            return response
    receipt.pop('published_at')
    result = analytics().collect_snapshot(receipt, FakeAnalytics(), PrivateYoutube(), window='24h',
        now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc))
    assert result['reference_basis'] == 'uploaded_at'


def test_cli_collect_http_error_is_reported_without_traceback(receipt, tmp_path, monkeypatch, capsys):
    from video2yt.analytics_cli import main
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    path = tmp_path / 'publication.json'
    path.write_text(json.dumps(receipt))
    monkeypatch.setattr(analytics(), 'get_credentials', lambda *args: object())
    def fail(*args, **kwargs):
        raise HttpError(Response({'status': '403'}), b'{"error":{"message":"disabled API"}}')
    monkeypatch.setattr('googleapiclient.discovery.build', fail)
    assert main(['collect', '--receipt', str(path), '--window', '24h']) == 1
    assert 'disabled API' in capsys.readouterr().err


def test_existing_read_only_token_is_used_without_oauth(tmp_path, monkeypatch):
    from google_auth_oauthlib.flow import InstalledAppFlow
    path = tmp_path / 'youtube_analytics_token.json'
    path.write_text(json.dumps({'token': 'test-only', 'refresh_token': 'test-only', 'client_id': 'test-only',
        'client_secret': 'test-only', 'scopes': analytics().SCOPES, 'expiry': '2099-01-01T00:00:00Z'}))
    def forbidden(*args, **kwargs):
        pytest.fail('valid read-only cache must not initiate OAuth')
    monkeypatch.setattr(InstalledAppFlow, 'from_client_secrets_file', forbidden)
    credentials = analytics().get_credentials(tmp_path / 'unused.json', path)
    assert set(credentials.scopes) == set(analytics().SCOPES)
    assert path.stat().st_mode & 0o777 == 0o600


def test_broad_scope_cache_is_rejected_without_modification(tmp_path):
    path = tmp_path / 'youtube_analytics_token.json'
    raw = json.dumps({'token': 'test-only', 'refresh_token': 'test-only', 'client_id': 'test-only',
        'client_secret': 'test-only', 'scopes': analytics().SCOPES + ['https://www.googleapis.com/auth/youtube.upload'],
        'expiry': '2099-01-01T00:00:00Z'})
    path.write_text(raw)
    with pytest.raises(ValueError, match='read-only scopes'):
        analytics().get_credentials(tmp_path / 'unused.json', path)
    assert path.read_text() == raw


def test_oauth_rejects_additional_granted_write_scope(tmp_path, monkeypatch):
    from google_auth_oauthlib.flow import InstalledAppFlow
    class Credentials:
        valid = True
        scopes = analytics().SCOPES
        granted_scopes = analytics().SCOPES + ['https://www.googleapis.com/auth/youtube.upload']
        def to_json(self):
            return '{}'
    class Flow:
        def run_local_server(self, **kwargs):
            return Credentials()
    def create(secret, scopes):
        assert scopes == analytics().SCOPES
        return Flow()
    monkeypatch.setattr(InstalledAppFlow, 'from_client_secrets_file', create)
    with pytest.raises(ValueError, match='read-only scopes'):
        analytics().get_credentials(tmp_path / 'unused.json', tmp_path / 'youtube_analytics_token.json')
    assert not (tmp_path / 'youtube_analytics_token.json').exists()


@pytest.mark.parametrize('data, expected', [
    ({}, False),
    ({'metrics': {'views': None}, 'traffic_sources': {'BROWSE': {'views': None}}}, False),
    ({'metrics': {'views': 0}}, True),
    ({'traffic_sources': {'BROWSE': {'views': 0}}}, True),
])
def test_exact_checkpoint_requires_a_measured_metric(receipt, tmp_path, data, expected):
    result = analytics().make_snapshot(receipt, data, window='24h', kind='exact',
        start='2026-08-01T12:00:00Z', end='2026-08-02T12:00:00Z',
        collected_at='2026-08-04T12:00:00Z')
    assert result['checkpoint_satisfied'] is expected
    analytics().save_snapshot(result, tmp_path)
    report = analytics().build_report(receipt, tmp_path,
        now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc))
    assert report['checkpoints']['24h']['status'] == ('recorded' if expected else 'due')
    assert report['checkpoints']['24h']['exact_snapshots'] == int(expected)
