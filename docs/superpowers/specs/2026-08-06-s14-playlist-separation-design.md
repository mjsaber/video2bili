# S14 Playlist Separation Design

**Date:** 2026-08-06  
**Status:** Approved in conversation; pending written-spec review  
**Channel:** `UCEgIrCo0pR6DyyrXuSn3wBg`

## Goal

Separate Season 14 Battlegrounds videos from Season 13 on YouTube and make future uploads route to an explicit season playlist instead of a season-agnostic catch-all.

## Confirmed decisions

- Rename the existing public playlist `爐石戰記：英雄戰場 流派教學全集` to `英雄戰場 S13 流派教學`.
- Create a separate public playlist named `英雄戰場 S14 流派教學`.
- Keep topical and streamer playlists, including `郭楓荷 實戰教學`, unchanged.
- Treat these existing uploads as S14:
  - `hZiEib2tzAs` — `「爐石戰記：英雄戰場」第14賽季搶先體驗：宰割亡靈五千攻擊 | 郭楓荷 × Kimmy [彈幕]`
  - `KXlycy1Kb1A` — `「爐石戰記：英雄戰場」新賽季抉擇野豬完整教學 | 郭楓荷 × Kimmy 實戰 [彈幕]`
- Keep `-FK8EETGaDc` (`新賽季B-Box機械`) in S13. It was published before the Season 14 creator early-access window and uses the outgoing Season 13 environment. Blizzard's Season 14 announcement sets creator early access from 2026-07-30 and the live season start at 2026-08-04.

## Why season must be explicit

Title keyword inference is not reliable. Existing Season 13 titles frequently contain `新賽季`, while the current Season 14 upload title does not contain `S14` or `第14賽季`. A title-only predicate would therefore move old videos incorrectly and will fail again when Season 15 starts.

New upload metadata will carry an explicit integer field:

```json
{
  "season": 14
}
```

The upload preflight will validate that `season` is a positive integer. This makes a missing season fail before any video is uploaded, instead of uploading successfully and silently skipping season playlist placement.

## Playlist routing design

Season routing and topical routing will be separate concerns:

1. `season` selects exactly one playlist named `英雄戰場 S{season} 流派教學`.
2. Existing keyword rules independently add matching videos to topical/streamer playlists such as `英雄戰場 異變玩法教學`, `英雄戰場 剋制與轉型教學`, and `郭楓荷 實戰教學`.
3. The season-agnostic catch-all rule is removed so it cannot be recreated after the migration.
4. Playlist additions remain idempotent.

The playlist descriptions will be season-specific:

- S13: `爐石戰記：英雄戰場第 13 賽季流派完整教學與實戰。#英雄戰場教學`
- S14: `爐石戰記：英雄戰場第 14 賽季流派完整教學與實戰，持續更新。#英雄戰場教學`

## Live migration

A dedicated migration command will default to dry-run and require `--yes` for writes. It will:

1. Authenticate and verify the expected channel ID.
2. Resolve the existing playlist by its exact current title.
3. Rename it in place to `英雄戰場 S13 流派教學`, preserving its ID, URL, order, and existing membership.
4. Create or reuse `英雄戰場 S14 流派教學` as a public playlist.
5. Add the two confirmed S14 video IDs to S14 in chronological order when absent.
6. Remove those two IDs from S13 by resolving their `playlistItem` IDs and deleting only those exact membership records.
7. Leave every other playlist membership untouched.
8. Re-read both playlists and fail if postconditions are not satisfied.

The migration must be restart-safe. If it stops partway through, rerunning it produces the same final state without duplicate memberships. It must also handle the already-renamed state and an already-created S14 playlist.

## Backfill behavior

The existing backfill command will no longer route every upload into a catch-all playlist. It will retain topical/streamer keyword backfill only. Historical season membership is owned by the explicit season migration, because old uploads do not all have local metadata containing a reliable season field.

## Error handling and safety

- No YouTube mutation occurs without `--yes`.
- Exact playlist titles and exact video IDs are used; no fuzzy deletion is allowed.
- Removal uses the playlist membership ID returned by YouTube, not a broad video delete operation.
- The script refuses to proceed on the wrong authenticated channel.
- If both the old and renamed S13 playlist titles exist simultaneously, the migration stops for manual inspection rather than guessing which playlist to modify.
- Upload success remains independent from secondary topical playlist failures, but season metadata validation happens before upload.

## Verification

Automated tests will cover:

- season validation, including rejection of missing, boolean, zero, negative, and string values;
- S14 metadata routing to `英雄戰場 S14 流派教學` even when the title only says `新賽季`;
- exactly one season playlist per upload;
- preservation of topical and streamer matches;
- idempotent playlist creation and insertion;
- exact membership removal by playlist-item ID;
- migration dry-run producing no writes;
- migration reruns after partial or complete application;
- the old catch-all title not being recreated by backfill.

After tests pass, live verification will confirm:

- `英雄戰場 S13 流派教學` is public and excludes both S14 IDs;
- `英雄戰場 S14 流派教學` is public and contains exactly the two confirmed S14 IDs in chronological order;
- both S14 videos remain in `郭楓荷 實戰教學`;
- no playlist named `爐石戰記：英雄戰場 流派教學全集` remains.

## Out of scope

- Reorganizing `異變`, `剋制與轉型`, or streamer playlists.
- Retitling or editing the videos themselves.
- Automatically reconstructing season membership for every historical upload before S13.
- Changing playlist ordering beyond the two S14 insertions.
