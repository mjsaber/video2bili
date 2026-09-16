"""Search-keyword rules for upload title/tags (see assets/analytics/2026-09-13_*)."""

from video2yt.packaging import search_keyword_issues


def compliant_meta() -> dict:
    return {
        "title": "倒轉怎麼轉型？羅傑斯留還是賣｜爐石戰記 英雄戰場 海盜",
        "tags": ["爐石戰記", "英雄戰場", "英雄戰場教學", "Hearthstone Battlegrounds", "海盜"],
    }


def test_compliant_meta_has_no_issues():
    assert search_keyword_issues(compliant_meta()) == ([], [])


def test_title_without_game_name_is_an_error():
    meta = compliant_meta() | {"title": "倒轉怎麼轉型？｜英雄戰場 海盜"}
    errors, _ = search_keyword_issues(meta)
    assert any("爐石戰記" in e for e in errors)


def test_missing_required_tag_is_an_error():
    meta = compliant_meta() | {"tags": ["爐石戰記", "英雄戰場", "海盜"]}
    errors, _ = search_keyword_issues(meta)
    assert any("英雄戰場教學" in e and "Hearthstone Battlegrounds" in e for e in errors)


def test_required_tag_match_is_case_insensitive():
    meta = compliant_meta() | {"tags": ["爐石戰記", "英雄戰場", "英雄戰場教學", "hearthstone battlegrounds", "海盜"]}
    assert search_keyword_issues(meta)[0] == []


def test_simplified_tag_is_an_error():
    meta = compliant_meta()
    meta["tags"] = meta["tags"] + ["酒馆战棋"]
    errors, _ = search_keyword_issues(meta)
    assert any("酒馆战棋" in e for e in errors)


def test_title_without_tribe_word_is_a_warning_not_error():
    meta = compliant_meta() | {"title": "翻盤思路：白板局也能贏｜爐石戰記 英雄戰場"}
    errors, warnings = search_keyword_issues(meta)
    assert errors == []
    assert any("tribe" in w for w in warnings)


def test_official_tribe_name_without_colloquial_tag_is_a_warning():
    meta = compliant_meta() | {"title": "匕首亡靈怎麼餵屠殺｜爐石戰記 英雄戰場"}
    _, warnings = search_keyword_issues(meta)
    assert any("不死族" in w for w in warnings)
    meta["tags"] = meta["tags"] + ["不死族"]
    assert not any("不死族" in w for w in search_keyword_issues(meta)[1])
