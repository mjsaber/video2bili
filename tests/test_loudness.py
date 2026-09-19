"""loudness.py: R128 measurement parse + voice-relative bed gain."""
from pathlib import Path
from unittest.mock import MagicMock

from video2yt import loudness


def test_measure_lufs_parses_integrated_value(monkeypatch, tmp_path):
    seen = []
    def _run(cmd, **kw):
        seen.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="  Integrated loudness:\n    I:         -17.7 LUFS\n    Threshold: -28.0 LUFS\n")
    monkeypatch.setattr("video2yt.loudness.subprocess.run", _run)
    assert loudness.measure_lufs(tmp_path / "a.wav") == -17.7
    assert "-vn" in seen[0] and "ebur128" in seen[0]


def test_measure_lufs_none_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("video2yt.loudness.subprocess.run",
                        lambda cmd, **kw: MagicMock(returncode=0, stdout="", stderr="no summary here"))
    assert loudness.measure_lufs(tmp_path / "a.wav") is None


def test_bed_gain_db_targets_below_voice_and_clamps():
    assert loudness.bed_gain_db(-19.0, -23.0) == -26.0
    assert loudness.bed_gain_db(-19.0, -23.0, below_db=25.0) == -21.0
    assert loudness.bed_gain_db(None, -23.0) == loudness.LEGACY_BED_GAIN_DB
    assert loudness.bed_gain_db(-19.0, None) == loudness.LEGACY_BED_GAIN_DB
    assert loudness.bed_gain_db(-5.0, -60.0) == loudness._MAX_GAIN_DB
    assert loudness.bed_gain_db(-70.0, -5.0) == loudness._MIN_GAIN_DB


def _ebur_lines(values):
    return "".join(f"[Parsed_ebur128_0] t: {i/10:.1f} TARGET:-23 LUFS M: {v:.1f} S: {v:.1f} I: -20.0 LUFS LRA: 5.0 LU\n"
                   for i, v in enumerate(values))


def test_voice_reference_is_85th_percentile_of_short_term_ignoring_silence(monkeypatch, tmp_path):
    values = [-70.0, -55.0] + list(range(-40, -9))   # silence + a −40…−10 ramp (31 windows)
    monkeypatch.setattr("video2yt.loudness.subprocess.run",
                        lambda cmd, **kw: MagicMock(returncode=0, stdout="", stderr=_ebur_lines(values)))
    ref = loudness.voice_reference_lufs(tmp_path / "speech.wav")
    assert ref == -14.0            # round(0.85 * 30) = 26th of −40…−10 → −14; −70/−55 dropped as silence
    assert loudness.voice_reference_lufs(tmp_path / "speech.wav", percentile=50) == -25.0


def test_voice_reference_drops_windows_far_below_the_loudest(monkeypatch, tmp_path):
    values = [-45.0] * 40 + [-15.0, -14.0, -13.0, -12.0]   # bed-only windows dominate, 4 speech windows
    monkeypatch.setattr("video2yt.loudness.subprocess.run",
                        lambda cmd, **kw: MagicMock(returncode=0, stdout="", stderr=_ebur_lines(values)))
    assert loudness.voice_reference_lufs(tmp_path / "seg.mp4") == -12.0   # P85 of the 4 speech windows only (round(0.85·3)=3)


def test_voice_reference_none_when_only_silence(monkeypatch, tmp_path):
    monkeypatch.setattr("video2yt.loudness.subprocess.run",
                        lambda cmd, **kw: MagicMock(returncode=0, stdout="", stderr=_ebur_lines([-70.0, -60.0])))
    assert loudness.voice_reference_lufs(tmp_path / "speech.wav") is None
    monkeypatch.setattr("video2yt.loudness.subprocess.run", lambda cmd, **kw: None)
    assert loudness.voice_reference_lufs(tmp_path / "speech.wav") is None


def test_align_gain_db_puts_p85_on_target_and_clamps():
    assert loudness.align_gain_db(-17.0) == loudness.TARGET_P85_LUFS + 17.0
    assert loudness.align_gain_db(-13.0) == 0.0
    assert loudness.align_gain_db(None) is None
    assert loudness.align_gain_db(-90.0) == loudness._MAX_GAIN_DB
