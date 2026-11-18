---
name: youtube-infographic-maker
description: YouTube Infographic Maker — turns one or more YouTube videos into a detailed, printable infographic (PDF + HTML) with the video's big idea, key takeaways, core lessons, frameworks and a step-by-step action plan. Use this whenever the user sends a YouTube link (youtube.com, youtu.be, shorts, playlists) together with "Create infographic" (any capitalisation, or "crear infografía", "make an infographic", "infographic of this video"), and also when they ask to turn a YouTube video, talk, podcast episode or lecture into a printable summary, cheat sheet, one-pager or visual study guide — even if they don't name the skill.
---

# YouTube Infographic Maker

The user sends YouTube link(s) and says "Create infographic". Your job: study the
**entire** content of every video, pull out what actually matters — the core
teachings, the key takeaways, and (when the content is applicable) concrete
actionable steps — and deliver a polished, printable infographic.

The user wants it **concrete and straight to the point**. It may run to several
pages when the video is dense, but every line must earn its place: no filler,
no generic advice the video didn't give, no repeating the same point in three
sections.

## Workflow

### 1. Collect the links
Pull every YouTube URL from the message (watch, youtu.be, shorts, live, embed,
playlist). Several links → one combined infographic unless the user asks for
separate ones (see "Multiple videos" below).

### 2. Get the full transcript
Run the bundled script (from this skill's directory):

```bash
python scripts/get_transcript.py "<url1>" "<url2>" --out <workdir>/transcripts --lang en,es
```

It writes one `<video_id>.md` per video (title, channel, duration, chapters,
description, and the transcript in ~30 s paragraphs with `[mm:ss]` stamps) and
prints `OK ...` or `TRANSCRIPT_UNAVAILABLE ...` per video. Put `--lang` first in
the language the video is likely in.

If a video comes back `TRANSCRIPT_UNAVAILABLE` (YouTube blocks most cloud /
server IPs, so this is common outside the user's own computer), work down this
list and stop at the first that gives you the real spoken content:

1. **A browser tool, if one is connected** (Claude in Chrome `mcp__claude-in-chrome__*`,
   the built-in browser `mcp__Claude_Browser__*`, or the remote-devices variants).
   Read that browser's skill first, then open the video, expand the description
   ("...more"), click **Show transcript**, and read the transcript panel text
   (scroll it to the end). The user's own browser is not IP-blocked.
2. **An official transcript elsewhere**: TED talks (ted.com/talks/.../transcript),
   podcasts that publish transcripts or detailed show notes, the creator's blog
   post of the same talk. Use web search/fetch. Note in the source footer that a
   secondary transcript was used.
3. **Ask the user** to paste it: "On the video page click *...more* under the
   title → *Show transcript* → select all the text and paste it here." Keep it
   to one short message and say exactly which video(s) are missing.

Do not build the infographic from the title, description, comments or your
general knowledge of the speaker. A summary of what you *assume* the video says
looks authoritative on paper and would mislead the user — the whole point is
that it reflects *this* video. The description and chapters are useful for
structure once you have the transcript.

### 3. Study the whole thing
Read the **complete** transcript, start to finish, before writing anything. For
long videos (> ~15k words) read it in sequential chunks and keep running notes
(idea, supporting example, timestamp) so nothing from the second half gets
dropped — the end of a video often holds the synthesis or the action steps.

Then read `references/content-guide.md` and follow it to extract and distil the
content. It defines what counts as a takeaway vs. a lesson vs. an action step,
how to write each one, and how to decide length.

### 4. Plan the layout
Choose components from `assets/template.html` based on what the video actually
contains — not every component belongs in every infographic:

| Always | When the video has it |
|---|---|
| Hero (lesson-style title, channel, duration) | By the Numbers — real stats stated in the video |
| The Big Idea (one sentence) | Framework / process flow — a named method, sequence, model |
| Key Takeaways (4–8 cards) | Do vs. Avoid / Myth vs. Truth — explicit contrasts or mistakes |
| Core Lessons | Quotes (max 2–3) — only genuinely memorable lines |
| Action Plan (if applicable — see guide) | Key Terms — jargon the reader needs |
| 60-Second Recap | Common Mistakes / warnings |
| Source footer | |

Pick an accent colour that fits the topic (set `--accent`, `--accent-2`,
`--accent-soft` in `:root`):
business/productivity `#1f4fd1 / #f59e0b / #eaf0ff` · health/fitness
`#0f8a5f / #f97316 / #e6f6ef` · money/investing `#0b6e4f / #d4a017 / #e8f5ee` ·
psychology/mindset `#6d28d9 / #f59e0b / #f1ebff` · tech/AI `#0f172a / #06b6d4 / #e6f7fb` ·
creativity/marketing `#db2777 / #7c3aed / #fdeaf3` · learning/education
`#c2410c / #0ea5e9 / #fff1e8`.

### 5. Build the HTML
Copy `assets/template.html` to `<workdir>/<slug>-infographic.html`, keep the
whole `<style>` block, and replace the body with the filled-in components.
Delete every `{{placeholder}}` and every component you aren't using — leftover
placeholders or empty sections look broken in print. Escape `&`, `<`, `>` in
text. Put timestamps (`▶ 12:34`) on takeaway cards and quotes so the user can
jump back to the source. Use `<div class="page-break"></div>` only if a major
section would otherwise start at the very bottom of a page.

Write it in the language of the user's message unless they ask otherwise
(translate quotes and keep the original in the `.by` line if the video is in
another language).

### 6. Render and check
```bash
python scripts/render_pdf.py <workdir>/<slug>-infographic.html --preview <workdir>/preview.png
```
Add `--a4` if the user is outside North America or asks for A4. The script
prints the page count. Look at the preview image (and the PDF if you can) and
fix: overflowing or orphaned cards, a lonely heading at the bottom of a page,
a last page with only two lines on it (tighten copy to pull it back), text too
small to read, leftover placeholders. Re-render after fixes. Cheap ways to
reclaim space before cutting content: switch 6 short takeaway cards from `g2`
to `g3`, merge two thin sections, shorten `.how` lines.

If the renderer fails, deliver the HTML anyway — it prints cleanly from any
browser (Print → Save as PDF, with "Background graphics" on) — and tell the
user that.

### 7. Deliver
Save the final PDF and HTML where the user can open them (the outputs folder or
the working directory) and send them with the file-sharing tool if one exists
(`present_files`, `SendUserFile`). In chat, keep it short:
- the Big Idea in one sentence,
- page count and what's inside (e.g. "6 takeaways, 3-step framework, 9-item action plan"),
- any caveat (auto-generated captions, secondary transcript, a video that couldn't be read).

Don't paste the infographic's content into the chat — it's in the file.

## Multiple videos
- **Same topic / same series** → one synthesised infographic organised by
  *theme*, not by video. Tag each takeaway with its source (`V1`, `V2` in the
  `.ts` line), merge points that repeat across videos, and call out where the
  videos disagree. The hero kicker becomes "3-Video Infographic".
- **Unrelated topics** → one PDF with a section set per video (hero-style
  header per video, page break between them) and a short combined recap only
  if there's a real thread linking them.
- **Playlist links** are expanded by the script. If it's more than ~8 videos,
  tell the user how many there are and confirm before processing them all.

## Files in this skill
- `scripts/get_transcript.py` — metadata + timestamped transcripts (youtube-transcript-api → yt-dlp fallback).
- `scripts/render_pdf.py` — HTML → PDF (Chromium via Playwright for Node or Python → WeasyPrint) with page numbers and PNG preview; uses `scripts/render_pdf.js` for the Node path.
- `assets/template.html` — the print stylesheet and every component, documented inline.
- `references/content-guide.md` — how to extract, distil and write the content. Read it at step 3.
