#!/usr/bin/env python3
"""Publish the next approved Belovd post to Instagram + TikTok.

Instagram and TikTok advance through approved/ independently — each
platform posts whatever its own earliest not-yet-"ok" post is. This lets
one platform go live before the other is configured, without either
blocking on the other once both are running.

Run by .github/workflows/post.yml on a schedule. Never invoked for content
creation or approval — see ../.claude/skills/social-poster/SKILL.md in the
main project repo for the human-in-the-loop steps that come before this.
"""
import base64
import os
import sys
import time
from pathlib import Path

import requests
from nacl import encoding, public

REPO_ROOT = Path(__file__).resolve().parent.parent
APPROVED_DIR = REPO_ROOT / "approved"
LOG_PATH = REPO_ROOT / "posted-log.md"
GRAPH_VERSION = "v21.0"

META_KEYS = ["META_ACCESS_TOKEN", "META_IG_USER_ID"]
TIKTOK_KEYS = [
    "TIKTOK_CLIENT_KEY",
    "TIKTOK_CLIENT_SECRET",
    "TIKTOK_ACCESS_TOKEN",
    "TIKTOK_REFRESH_TOKEN",
    "GH_SECRETS_TOKEN",
]


def require(keys):
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        print(f"::error::Missing required secret(s): {', '.join(missing)}")
        sys.exit(1)


def tiktok_configured():
    present = [k for k in TIKTOK_KEYS if os.environ.get(k)]
    if not present:
        return False
    if len(present) < len(TIKTOK_KEYS):
        missing = [k for k in TIKTOK_KEYS if k not in present]
        print(f"::error::TikTok partially configured — missing {', '.join(missing)}")
        sys.exit(1)
    return True


def parse_log():
    """Return {post_id: {"instagram": "ok"/"fail", "tiktok": "ok"/"fail"}}.

    The log is append-only and a post_id may appear on several lines (e.g.
    Instagram succeeds today, TikTok catches up to that same post_id
    weeks later) — later lines only overwrite the platform keys they
    mention, never blank out a platform an earlier line already recorded.
    """
    result = {}
    if not LOG_PATH.exists():
        return result
    for line in LOG_PATH.read_text().splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        post_id, statuses = parts[0], parts[2]
        entry = result.setdefault(post_id, {})
        for tok in statuses.split():
            if ":" in tok:
                platform, status = tok.split(":", 1)
                entry[platform] = status
    return result


def find_next_pending(log, platform):
    if not APPROVED_DIR.exists():
        return None
    for post_id in sorted(p.name for p in APPROVED_DIR.iterdir() if p.is_dir()):
        if log.get(post_id, {}).get(platform) == "ok":
            continue
        return post_id
    return None


def raw_url(post_id, filename):
    repo = os.environ["GITHUB_REPOSITORY"]
    return f"https://raw.githubusercontent.com/{repo}/main/approved/{post_id}/{filename}"


def read_caption(post_id):
    return (APPROVED_DIR / post_id / "caption.txt").read_text().strip()


def _checked(r):
    """Like r.raise_for_status(), but keeps Meta's actual error body."""
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.request.method} {r.request.url} -> {r.text}")
    return r


def _wait_until_finished(base, container_id, token):
    for _ in range(20):
        r = _checked(
            requests.get(
                f"{base}/{container_id}",
                params={"fields": "status_code,status", "access_token": token},
                timeout=30,
            )
        )
        body = r.json()
        status = body.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"container {container_id} errored: {body}")
        time.sleep(3)
    raise RuntimeError(f"container {container_id} never finished processing")


def publish_instagram(post_id):
    caption = read_caption(post_id)
    token = os.environ["META_ACCESS_TOKEN"]
    ig_id = os.environ["META_IG_USER_ID"]
    base = f"https://graph.instagram.com/{GRAPH_VERSION}"
    try:
        child_ids = []
        for fname in ("slide-1-affirmation.png", "slide-2-scripture.png"):
            r = _checked(
                requests.post(
                    f"{base}/{ig_id}/media",
                    data={
                        "image_url": raw_url(post_id, fname),
                        "is_carousel_item": "true",
                        "access_token": token,
                    },
                    timeout=30,
                )
            )
            child_ids.append(r.json()["id"])

        for cid in child_ids:
            _wait_until_finished(base, cid, token)

        r = _checked(
            requests.post(
                f"{base}/{ig_id}/media",
                data={
                    "media_type": "CAROUSEL",
                    "children": ",".join(child_ids),
                    "caption": caption,
                    "access_token": token,
                },
                timeout=30,
            )
        )
        carousel_id = r.json()["id"]

        # The carousel container itself also needs to reach FINISHED before
        # media_publish will accept it — polling only the child items isn't
        # enough.
        _wait_until_finished(base, carousel_id, token)

        _checked(
            requests.post(
                f"{base}/{ig_id}/media_publish",
                data={"creation_id": carousel_id, "access_token": token},
                timeout=30,
            )
        )
        return "ok"
    except Exception as exc:
        print(f"::error::Instagram publish failed for {post_id}: {exc}")
        return "fail"


def refresh_tiktok_token():
    r = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": os.environ["TIKTOK_CLIENT_KEY"],
            "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
            "grant_type": "refresh_token",
            "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"],
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data["access_token"], data["refresh_token"]


def update_repo_secret(name, value):
    """Encrypt+push a new value for a GitHub Actions repo secret."""
    repo = os.environ["GITHUB_REPOSITORY"]
    gh_token = os.environ["GH_SECRETS_TOKEN"]
    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
    }
    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    key_info = r.json()
    public_key = public.PublicKey(key_info["key"], encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(value.encode("utf-8"))
    encrypted_value = base64.b64encode(encrypted).decode("utf-8")

    r = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
        headers=headers,
        json={"encrypted_value": encrypted_value, "key_id": key_info["key_id"]},
        timeout=30,
    )
    r.raise_for_status()


def publish_tiktok(post_id):
    caption = read_caption(post_id)
    try:
        access_token, new_refresh_token = refresh_tiktok_token()
        # Persist the rotated refresh token immediately — if anything below
        # fails, the next run must still be able to refresh.
        update_repo_secret("TIKTOK_REFRESH_TOKEN", new_refresh_token)

        photo_urls = [
            raw_url(post_id, "slide-1-affirmation.png"),
            raw_url(post_id, "slide-2-scripture.png"),
        ]
        r = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/content/init/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={
                "post_info": {
                    "title": caption[:150],
                    "description": caption,
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_cover_index": 0,
                    "photo_images": photo_urls,
                },
                "post_mode": "DIRECT_POST",
                "media_type": "PHOTO",
            },
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("error", {}).get("code") not in (None, "ok"):
            raise RuntimeError(body["error"])
        publish_id = body["data"]["publish_id"]

        for _ in range(20):
            r = requests.post(
                "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"publish_id": publish_id},
                timeout=30,
            )
            r.raise_for_status()
            status = r.json()["data"]["status"]
            if status == "PUBLISH_COMPLETE":
                return "ok"
            if status == "FAILED":
                raise RuntimeError(r.json()["data"])
            time.sleep(5)
        raise RuntimeError(f"publish_id {publish_id} did not complete in time")
    except Exception as exc:
        print(f"::error::TikTok publish failed for {post_id}: {exc}")
        return "fail"


def log_result(post_id, statuses):
    """statuses: dict of only the platform(s) actually attempted this run."""
    parts = " ".join(f"{platform}:{status}" for platform, status in statuses.items())
    with LOG_PATH.open("a") as f:
        f.write(
            f"{post_id} | slide-1-affirmation.png,slide-2-scripture.png | {parts}\n"
        )


def main():
    require(META_KEYS + ["GITHUB_REPOSITORY"])
    log = parse_log()
    any_failure = False

    ig_post_id = find_next_pending(log, "instagram")
    if ig_post_id:
        status = publish_instagram(ig_post_id)
        log_result(ig_post_id, {"instagram": status})
        print(f"instagram: {ig_post_id} -> {status}")
        any_failure = any_failure or status != "ok"
    else:
        print("instagram: nothing pending")

    if tiktok_configured():
        tt_post_id = find_next_pending(log, "tiktok")
        if tt_post_id:
            status = publish_tiktok(tt_post_id)
            log_result(tt_post_id, {"tiktok": status})
            print(f"tiktok: {tt_post_id} -> {status}")
            any_failure = any_failure or status != "ok"
        else:
            print("tiktok: nothing pending")
    else:
        print("tiktok: not configured yet, skipping")

    if any_failure:
        sys.exit(1)


if __name__ == "__main__":
    main()
