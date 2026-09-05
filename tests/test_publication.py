import json
from pathlib import Path

import pytest

from video2yt import cleanup, upload_cli
from tests.test_upload_metadata import valid_meta


@pytest.fixture
def publishing(tmp_path, monkeypatch):
    project = tmp_path / 'output' / 'demo'
    project.mkdir(parents=True)
    video = project / 'final.mp4'; video.write_bytes(b'video')
    thumb = project / 'thumbnail.png'; thumb.write_bytes(b'png')
    (project / 'intro_script.txt').write_text('鉤牙破萬', encoding='utf-8')
    meta = valid_meta() | {'video_path': str(video), 'thumbnail_path': str(thumb)}
    manifest = project / 'youtube_metadata.json'
    manifest.write_text(json.dumps(meta))
    args = upload_cli.parse_args(['--metadata', str(manifest)])
    calls = {'video': 0, 'thumbnail': 0, 'playlist': 0}
    monkeypatch.setattr(upload_cli.upload, 'get_credentials', lambda *a: object())
    monkeypatch.setattr(upload_cli, 'build', lambda *a, **k: object())
    monkeypatch.setattr(upload_cli.upload, 'list_channels', lambda *a: [{'id': 'channel'}])
    def insert(*a):
        calls['video'] += 1
        return 'abcdefghijk'
    def thumbnail(*a): calls['thumbnail'] += 1
    def playlist(*a, **k): calls['playlist'] += 1
    monkeypatch.setattr(upload_cli.upload, 'upload_video', insert)
    monkeypatch.setattr(upload_cli.upload, 'upload_thumbnail', thumbnail)
    monkeypatch.setattr(upload_cli.playlists, 'add_video', playlist)
    return project, args, calls


def test_retry_reuses_video_and_keeps_durable_archive(publishing):
    project, args, calls = publishing
    first = upload_cli.run(args)
    second = upload_cli.run(args)
    assert first['video_id'] == second['video_id']
    assert calls == {'video': 1, 'thumbnail': 1, 'playlist': 1}
    receipt = json.loads((project / 'publication.json').read_text())
    assert receipt['status'] == 'complete'
    assert receipt['channel_id'] == 'channel'
    archive = project.parent.parent / 'assets/publications/abcdefghijk'
    assert (archive / 'intro_script.txt').read_text() == '鉤牙破萬'
    assert (archive / 'publication.json').is_file()
    assert not (archive / 'final.mp4').exists()


def test_playlist_failure_is_recoverable_without_reupload(publishing, monkeypatch):
    project, args, calls = publishing
    def fail(*a, **k): raise RuntimeError('playlist unavailable')
    monkeypatch.setattr(upload_cli.playlists, 'add_video', fail)
    result = upload_cli.run(args)
    assert result['complete'] is False
    assert json.loads((project / 'publication.json').read_text())['video_id'] == 'abcdefghijk'
    assert not cleanup.is_shipped_project(project)
    monkeypatch.setattr(upload_cli.playlists, 'add_video', lambda *a, **k: None)
    assert upload_cli.run(args)['complete']
    assert calls['video'] == 1


def test_uncertain_upload_is_not_blindly_repeated(publishing, monkeypatch):
    project, args, calls = publishing
    def interrupted(*a): raise RuntimeError('connection lost')
    monkeypatch.setattr(upload_cli.upload, 'upload_video', interrupted)
    with pytest.raises(RuntimeError): upload_cli.run(args)
    monkeypatch.setattr(upload_cli.upload, 'upload_video', lambda *a: pytest.fail('duplicate upload'))
    with pytest.raises(RuntimeError, match='uncertain'): upload_cli.run(args)


def test_changed_video_is_not_reuploaded(publishing):
    project, args, calls = publishing
    upload_cli.run(args)
    (project / 'final.mp4').write_bytes(b'different video')
    with pytest.raises(ValueError, match='changed'): upload_cli.run(args)
    assert calls['video'] == 1


def test_thumbnail_change_updates_same_video(publishing):
    project, args, calls = publishing
    upload_cli.run(args)
    (project / 'thumbnail.png').write_bytes(b'new thumbnail')
    upload_cli.run(args)
    assert calls == {'video': 1, 'thumbnail': 2, 'playlist': 1}


def test_corrupt_receipt_never_means_new_upload(publishing):
    project, args, calls = publishing
    (project / 'publication.json').write_text('{')
    with pytest.raises(ValueError, match='receipt'): upload_cli.run(args)
    assert calls['video'] == 0


def test_metadata_only_draft_never_qualifies_for_cleanup(tmp_path):
    p = tmp_path / 'draft'; p.mkdir()
    (p / 'youtube_metadata.json').write_text('{}')
    assert not cleanup.is_shipped_project(p)


def test_cleanup_archives_before_delete_and_protects_draft(publishing):
    from video2yt import publication
    project, args, calls = publishing
    upload_cli.run(args)
    root = project.parent.parent
    draft = project.parent / 'draft'; draft.mkdir()
    (draft / 'youtube_metadata.json').write_text('{}')
    current = project.parent / 'current'; current.mkdir()
    (current / 'youtube_metadata.json').write_bytes((project / 'youtube_metadata.json').read_bytes())
    receipt = json.loads((project / 'publication.json').read_text())
    receipt.update(video_id='zyxwvutsrqp', uploaded_at='2099-01-01T00:00:00+00:00')
    publication.save(current, receipt)
    (project / 'content_understanding.md').write_text('decision evidence')
    plan = cleanup.build_plan(project.parent, root / 'temp', project='current')
    assert [t.path for t in plan.prev_targets] == [project]
    cleanup.execute(plan, project.parent, root / 'temp')
    assert not project.exists()
    assert draft.exists()
    assert (root / 'assets/publications/abcdefghijk/content_understanding.md').read_text() == 'decision evidence'


def test_cleanup_revalidates_receipts_at_execution(publishing):
    project, args, _ = publishing
    upload_cli.run(args)
    plan = cleanup.build_plan(project.parent, project.parent.parent / 'temp', project='demo')
    (project / 'publication.json').unlink()
    with pytest.raises(ValueError): cleanup.execute(plan, project.parent, project.parent.parent / 'temp')


def test_cleanup_refuses_active_publication_operation(publishing):
    from video2yt import publication
    project, args, _ = publishing
    upload_cli.run(args)
    plan = cleanup.build_plan(project.parent, project.parent.parent / 'temp', project='demo')
    with publication.locked(project):
        with pytest.raises(RuntimeError, match='already running'):
            cleanup.execute(plan, project.parent, project.parent.parent / 'temp')


def test_failed_thumbnail_preserves_uploaded_asset(publishing, monkeypatch):
    project, args, _ = publishing
    upload_cli.run(args)
    archive = project.parent.parent / 'assets/publications/abcdefghijk'
    assert (archive / 'uploaded_thumbnail.png').read_bytes() == b'png'
    (project / 'thumbnail.png').write_bytes(b'unpublished')
    def fail(*a): raise RuntimeError('failed')
    monkeypatch.setattr(upload_cli.upload, 'upload_thumbnail', fail)
    upload_cli.run(args)
    assert (archive / 'uploaded_thumbnail.png').read_bytes() == b'png'


def test_adoption_uses_verified_remote_timestamp(publishing, monkeypatch):
    project, args, calls = publishing
    class Remote:
        def videos(self): return self
        def list(self, **kw): return self
        def execute(self):
            return {'items': [{'snippet': {'channelId': 'channel', 'title': 'title',
                'publishedAt': '2025-01-01T00:00:00Z'}, 'status': {'privacyStatus': 'public'}}]}
    monkeypatch.setattr(upload_cli, 'build', lambda *a, **k: Remote())
    args.adopt_video_id = 'abcdefghijk'
    upload_cli.run(args)
    receipt = json.loads((project / 'publication.json').read_text())
    assert receipt['uploaded_at'] == '2025-01-01T00:00:00Z'
    assert calls['video'] == 0


def test_cleanup_never_deletes_ancestor_of_current(publishing):
    from video2yt import publication
    project, args, _ = publishing
    upload_cli.run(args)
    nested = project / 'nested'; nested.mkdir()
    receipt = publication.load(project)
    receipt.update(video_id='zyxwvutsrqp', uploaded_at='2099-01-01T00:00:00Z')
    publication.save(nested, receipt)
    plan = cleanup.Plan(nested, [], [cleanup.Target(project, 'output', 1)])
    with pytest.raises(ValueError):
        cleanup.execute(plan, project.parent, project.parent.parent / 'temp')
    assert nested.exists()


def test_cleanup_rejects_nested_project_argument(publishing):
    from video2yt import publication
    project, args, _ = publishing
    upload_cli.run(args)
    nested = project / 'nested'; nested.mkdir()
    publication.save(nested, publication.load(project))
    with pytest.raises(ValueError): cleanup.resolve_current(project.parent, nested)


def test_external_thumbnail_archived_with_custom_manifest_name(publishing):
    project, args, _ = publishing
    manifest = json.loads(args.metadata.read_text())
    external = project.parent.parent / 'temp' / 'source' / 'cover.png'
    external.parent.mkdir(parents=True)
    external.write_bytes(b'external uploaded cover')
    manifest['thumbnail_path'] = str(external)
    args.metadata = project / 'custom.json'
    args.metadata.write_text(json.dumps(manifest))
    (project / 'youtube_metadata.json').unlink()
    upload_cli.run(args)
    archive = project.parent.parent / 'assets/publications/abcdefghijk'
    assert (archive / 'uploaded_thumbnail.png').read_bytes() == b'external uploaded cover'
    assert json.loads((archive / 'uploaded_metadata.json').read_text()) == manifest
