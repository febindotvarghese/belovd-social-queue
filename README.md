# belovd-social-queue

The public bridge between Belovd's local creative pipeline (which needs a
human to pick the day's graphic) and the cloud-scheduled poster (which
publishes to Instagram/TikTok on a cron and can't see local files).

This repo holds **only** approved, ready-to-publish output — no app source,
no design-system docs, no unpublished drafts. Everything here is about to go
public on social anyway.

## Workflow

1. Run `creative-pipeline` locally, pick the day's variation as usual.
2. Copy the selected files into `approved/<date>/`:
   - `slide-1-affirmation.png`
   - `slide-2-scripture.png`
   - `caption.txt` — the Instagram/TikTok caption text (affirmation line +
     any hashtags), plain text, one post's worth
3. `git add`, `git commit`, `git push`. That push **is** the approval — it's
   the only signal the cloud poster acts on.
4. The `social-poster` skill (run on a cloud schedule) pulls this repo,
   finds the earliest `approved/<date>/` folder not yet in `posted-log.md`,
   publishes it to Instagram and TikTok using the raw GitHub URLs as the
   public image source, then commits a new line to `posted-log.md` and
   pushes — that commit is what prevents double-posting.

## posted-log.md format

One line per successful post:

```
2026-08-12 | slide-1-affirmation.png,slide-2-scripture.png | instagram:ok tiktok:ok
```

If a platform fails, it's recorded as `instagram:fail` and that date is
retried on the next run — only fully-succeeded dates are safe to skip.

## What never goes in this repo

Access tokens, client secrets, or any credential. Those live only as
secrets in the scheduled task's environment, never committed here — this
repo is public.
