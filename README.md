# belovd-social-queue

The public bridge between Belovd's local creative pipeline (which needs a
human to pick each post's graphic) and the cloud-scheduled poster (which
publishes to Instagram/TikTok on a cron and can't see local files).

This repo holds **only** approved, ready-to-publish output — no app source,
no design-system docs, no unpublished drafts. Everything here is about to go
public on social anyway.

## Cadence

**2 posts/day**, to start. Each post gets its own `approved/<post-id>/`
folder, where `post-id` is `<date>-<n>` (e.g. `2026-08-12-1`,
`2026-08-12-2`) — a date alone is not a unique folder name once there's more
than one post per day.

## Workflow

1. Run `creative-pipeline` locally — it picks 2 identity-facet angles for
   the day, then audits designs for each independently.
2. For each approved post, it copies the selected files into
   `approved/<post-id>/`:
   - `slide-1-affirmation.png`
   - `slide-2-scripture.png`
   - `caption.txt` — the Instagram/TikTok caption text (affirmation line,
     verse + reference, optional one-line invitation, then hashtags — see
     `distribution/social/voice.md` §Caption in the main repo), plain text,
     one post's worth
3. `git add`, `git commit` (one commit can cover both of a day's posts),
   `git push`. That push **is** the approval — it's the only signal the
   cloud poster acts on.
4. `scripts/post.py` (run on a GitHub Actions schedule) pulls this repo and
   advances **Instagram and TikTok independently** — each platform posts
   its own earliest `approved/<post-id>/` not yet marked `ok` for that
   platform in `posted-log.md` (plain lexicographic sort on the id —
   `2026-08-12-1` < `2026-08-12-2` < `2026-08-13-1`). This means one
   platform can be live before the other is configured — e.g. Instagram
   posts daily from day one while TikTok isn't set up yet — without either
   blocking on the other. Once TikTok joins later, it works through its own
   backlog at its own pace, one post-id per run, until it catches up to
   Instagram's cursor.

## posted-log.md format

Append-only; one line per platform attempted per run, keyed by post-id:

```
2026-08-12-1 | slide-1-affirmation.png,slide-2-scripture.png | instagram:ok
2026-08-12-2 | slide-1-affirmation.png,slide-2-scripture.png | instagram:ok
2026-08-12-1 | slide-1-affirmation.png,slide-2-scripture.png | tiktok:ok
```

A post-id can legitimately appear on more than one line if its platforms
completed on different days (e.g. TikTok catching up weeks after
Instagram). The reader merges lines for the same post-id, so a later line
only fills in the platform key it mentions — it never erases a platform an
earlier line already marked `ok`. A `fail` is retried on the next run for
that platform only.

## Automation

`scripts/post.py`, run by `.github/workflows/post.yml` on a daily
GitHub Actions schedule, is what actually does steps 4 above. It needs six
repo secrets set (Settings → Secrets and variables → Actions) —
`META_ACCESS_TOKEN`, `META_IG_USER_ID`, `TIKTOK_CLIENT_KEY`,
`TIKTOK_CLIENT_SECRET`, `TIKTOK_ACCESS_TOKEN`, `TIKTOK_REFRESH_TOKEN`, and
`GH_SECRETS_TOKEN` — see the main project's `SETUP-social-posting.md` for
where each one comes from. You can also trigger a run manually from the
Actions tab (`workflow_dispatch`) instead of waiting for the schedule.

## What never goes in this repo

Access tokens, client secrets, or any credential — as plaintext in a
committed file, that is. They live only as encrypted GitHub Actions repo
secrets, injected as env vars at run time. This repo is public, so nothing
sensitive ever gets committed here.
