#!/usr/bin/env python3
"""Fetch metadata + timestamped transcripts for one or more YouTube videos.

Usage:
    python get_transcript.py URL [URL ...] [--out DIR] [--lang en,es]

For every video it writes <DIR>/<video_id>.md containing title, channel,
duration, chapters (when available) and the transcript grouped into ~30 s
paragraphs with [mm:ss] stamps. A summary line per video is printed:

    OK <video_id> <path> (<n> words)
    TRANSCRIPT_UNAVAILABLE <video_id> <reason>

Exit code: 0 if every video succeeded, 2 if any failed (the others are still
written). Methods tried, in order: youtube-transcript-api, then yt-dlp
subtitles. Metadata comes from yt-dlp when it works, otherwise YouTube oEmbed.
Playlist URLs (list=... without v=...) are expanded with yt-dlp.
"""
import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def ensure(pkg, import_name=None):
    try:
        __import__(import_name or pkg)
        return True
    except ImportError:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg],
                           capture_output=True, text=True)
        if r.returncode != 0:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                                "--break-system-packages", pkg],
                               capture_output=True, text=True)
        try:
            __import__(import_name or pkg)
            return True
        except ImportError:
            return False


def video_id(url):
    url = url.strip()
    if ID_RE.match(url):
        return url
    p = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    host = p.netloc.lower()
    if host.endswith("youtu.be"):
        cand = p.path.strip("/").split("/")[0]
        return cand if ID_RE.match(cand) else None
    q = urllib.parse.parse_qs(p.query)
    if "v" in q and ID_RE.match(q["v"][0]):
        return q["v"][0]
    m = re.match(r"^/(shorts|embed|live|v)/([A-Za-z0-9_-]{11})", p.path)
    return m.group(2) if m else None


def playlist_ids(url):
    if not ensure("yt-dlp", "yt_dlp"):
        return []
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "--flat-playlist",
                        "--print", "id", url], capture_output=True, text=True)
    return [l.strip() for l in r.stdout.splitlines() if ID_RE.match(l.strip())]


def ts(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def group(snippets, window=30):
    """snippets: list of (start_seconds, text) -> list of '[mm:ss] para'."""
    out, cur, start = [], [], None
    for st, txt in snippets:
        txt = re.sub(r"\s+", " ", html.unescape(txt)).strip()
        if not txt:
            continue
        if start is None:
            start = st
        cur.append(txt)
        if st - start >= window:
            out.append(f"[{ts(start)}] " + " ".join(cur))
            cur, start = [], None
    if cur:
        out.append(f"[{ts(start or 0)}] " + " ".join(cur))
    return out


def via_transcript_api(vid, langs):
    if not ensure("youtube-transcript-api", "youtube_transcript_api"):
        raise RuntimeError("youtube-transcript-api not installable")
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    tl = api.list(vid)
    tr = None
    for finder in (tl.find_manually_created_transcript, tl.find_generated_transcript):
        try:
            tr = finder(langs)
            break
        except Exception:
            pass
    if tr is None:  # any language at all
        tr = next(iter(tl))
    data = tr.fetch()
    snips = [(s.start, s.text) for s in data.snippets]
    return snips, f"{tr.language} ({'auto' if tr.is_generated else 'manual'})"


def parse_vtt(path):
    snips, last = [], ""
    with open(path, encoding="utf-8", errors="ignore") as f:
        blocks = f.read().split("\n\n")
    for b in blocks:
        m = re.search(r"(\d+):(\d\d):(\d\d)\.\d+\s+-->", b)
        if not m:
            continue
        st = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        lines = [re.sub(r"<[^>]+>", "", l) for l in b.splitlines()[1:] if "-->" not in l]
        for l in lines:
            l = l.strip()
            if l and l != last:  # auto-subs repeat rolling lines
                snips.append((st, l))
                last = l
    return snips


def via_ytdlp(vid, langs, meta_only=False):
    if not ensure("yt-dlp", "yt_dlp"):
        raise RuntimeError("yt-dlp not installable")
    url = f"https://www.youtube.com/watch?v={vid}"
    with tempfile.TemporaryDirectory() as d:
        sub_langs = ",".join(f"{l}.*" for l in langs) + ",-live_chat"
        cmd = [sys.executable, "-m", "yt_dlp", "--skip-download", "--write-info-json",
               "-o", os.path.join(d, "%(id)s.%(ext)s"), url]
        if not meta_only:
            cmd[4:4] = ["--write-subs", "--write-auto-subs", "--sub-langs", sub_langs,
                        "--sub-format", "vtt"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        info = {}
        jf = glob.glob(os.path.join(d, "*.info.json"))
        if jf:
            with open(jf[0], encoding="utf-8") as f:
                info = json.load(f)
        if meta_only:
            return None, None, info
        vtts = sorted(glob.glob(os.path.join(d, "*.vtt")),
                      key=lambda p: (".orig" in p, len(p)))
        if not vtts:
            err = (r.stderr.strip().splitlines() or ["no subtitles"])[-1]
            raise RuntimeError(err)
        return parse_vtt(vtts[0]), os.path.basename(vtts[0]).split(".")[-2], info


def oembed(vid):
    try:
        u = ("https://www.youtube.com/oembed?format=json&url="
             + urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}"))
        with urllib.request.urlopen(u, timeout=20) as r:
            return json.load(r)
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--out", default="yt_transcripts")
    ap.add_argument("--lang", default="en,es",
                    help="preferred transcript languages, comma separated")
    a = ap.parse_args()
    langs = [l.strip() for l in a.lang.split(",") if l.strip()]
    os.makedirs(a.out, exist_ok=True)

    ids, failed = [], False
    for u in a.urls:
        v = video_id(u)
        if v:
            ids.append(v)
        elif "list=" in u:
            got = playlist_ids(u)
            print(f"PLAYLIST {u} -> {len(got)} videos")
            ids.extend(got)
        else:
            print(f"TRANSCRIPT_UNAVAILABLE {u} not a recognisable YouTube URL")
            failed = True
    ids = list(dict.fromkeys(ids))

    for vid in ids:
        errors, snips, lang, info = [], None, None, {}
        try:
            snips, lang = via_transcript_api(vid, langs)
        except Exception as e:
            errors.append(f"transcript-api: {type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}")
        try:
            if snips:
                _, _, info = via_ytdlp(vid, langs, meta_only=True)
            else:
                snips, lang, info = via_ytdlp(vid, langs)
        except Exception as e:
            errors.append(f"yt-dlp: {str(e)[:200]}")

        oe = oembed(vid)
        title = info.get("title") or oe.get("title") or vid
        channel = info.get("channel") or info.get("uploader") or oe.get("author_name") or "?"
        dur = info.get("duration")
        lines = [f"# {title}", "",
                 f"- URL: https://www.youtube.com/watch?v={vid}",
                 f"- Channel: {channel}"]
        if dur:
            lines.append(f"- Duration: {ts(dur)}")
        if info.get("upload_date"):
            d = info["upload_date"]
            lines.append(f"- Published: {d[:4]}-{d[4:6]}-{d[6:]}")
        if lang:
            lines.append(f"- Transcript language: {lang}")
        if info.get("chapters"):
            lines += ["", "## Chapters"] + [f"- [{ts(c['start_time'])}] {c['title']}"
                                             for c in info["chapters"]]
        if info.get("description"):
            lines += ["", "## Description", info["description"][:3000]]

        path = os.path.join(a.out, f"{vid}.md")
        if snips:
            paras = group(snips)
            words = sum(len(p.split()) for p in paras)
            lines += ["", "## Transcript", ""] + paras
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print(f"OK {vid} {path} ({words} words) — {title}")
        else:
            failed = True
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n\n## Transcript\n\n(unavailable)\n")
            blocked = any(k in " ".join(errors) for k in
                          ("IpBlocked", "RequestBlocked", "not a bot", "429", "Sign in"))
            reason = "BLOCKED_BY_YOUTUBE (cloud/server IP)" if blocked else "; ".join(errors)
            print(f"TRANSCRIPT_UNAVAILABLE {vid} {reason} — title: {title}; metadata saved to {path}")
    sys.exit(2 if failed else 0)


if __name__ == "__main__":
    main()
