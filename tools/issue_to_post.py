"""Turn a post-form issue into posts/<id>.md and media/<id>/*.

    python tools/issue_to_post.py issue.json [--mode publish|check]

issue.json is `gh issue view N --json title,body`. Images pasted into the issue are downloaded
into media/<id>/ and the links are rewritten. Writes comment.md (what to tell the issue) and, when
running in GitHub Actions, ok / slug / title to $GITHUB_OUTPUT. Always exits 0 on bad input: the
problem goes into the comment.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

ROOT = build.ROOT
LABELS = ["Short name", "Type", "One-line summary", "ATT&CK techniques (optional)", "Main tool (optional)",
          "Post (Markdown)"]
MAX_IMAGE = 5 * 1024 * 1024
MAGIC = [(b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif")]
ATTACHMENT_HOSTS = {"user-images.githubusercontent.com", "private-user-images.githubusercontent.com"}


class IssueError(Exception):
    pass


PLAIN_HELP = """To publish from a plain issue, start the text with these lines (the issue title is the post title):

```
---
slug: my-post-name
type: note
summary: One sentence for the list and link previews.
techniques: T1110.001, T1105
tool: splunk
---
```

then write the post under them. `type` is incident, investigation or note; `techniques` and `tool` are optional.
The forms at """ + build.REPO + """/issues/new?template=note.yml (or investigation.yml, incident.yml) fill this in for you."""


def parse_plain(body):
    """A plain issue: a '---' block of slug/type/summary/techniques/tool, then the post."""
    m = re.match(r"\s*---[ \t]*\n(.*?)\n---[ \t]*\n?(.*)", body, re.S)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        raise IssueError("the --- block at the top is not valid YAML (key: value lines).\n\n" + PLAIN_HELP)
    if not isinstance(meta, dict):
        raise IssueError("the --- block at the top must be key: value lines.\n\n" + PLAIN_HELP)
    tech = meta.get("techniques") or ""
    if isinstance(tech, list):
        tech = ", ".join(str(t) for t in tech)
    return {"Short name": str(meta.get("slug") or "").strip(), "Type": str(meta.get("type") or "").strip(),
            "One-line summary": str(meta.get("summary") or "").strip(),
            "ATT&CK techniques (optional)": str(tech).strip(),
            "Main tool (optional)": str(meta.get("tool") or "").strip(), "Post (Markdown)": m.group(2).strip()}


def parse_form(body):
    """The issue form renders as '### Label' + blank line + value. The last field takes everything
    after its heading, so '### ' headings inside the post are safe. A plain issue with a --- block works too."""
    if not re.search(r"^### Short name[ \t]*$", body, re.M):
        plain = parse_plain(body)
        if plain is None:
            raise IssueError("this issue has no form fields and no --- block, so the bot cannot read it.\n\n" + PLAIN_HELP)
        return plain
    pos, vals = 0, {}
    for label in LABELS:
        m = re.compile(r"^### " + re.escape(label) + r"[ \t]*\n", re.M).search(body, pos)
        if not m:
            raise IssueError(f"the form field “{label}” is missing from the issue.\n\n" + PLAIN_HELP)
        vals[label] = (m.start(), m.end())
        pos = m.end()
    out = {}
    for i, label in enumerate(LABELS):
        end = vals[LABELS[i + 1]][0] if i + 1 < len(LABELS) else len(body)
        v = body[vals[label][1]:end].strip()
        out[label] = "" if v == "_No response_" else v
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "writing-publisher"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_IMAGE + 1)
    return data


def allowed_image_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https":
        return False
    return (u.netloc == "github.com" and u.path.startswith("/user-attachments/assets/")) or u.netloc in ATTACHMENT_HOSTS


def image_ext(data):
    for magic, ext in MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def file_slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or "screenshot"


def pull_images(slug, text, get=fetch):
    """Download every pasted image into media/<slug>/ and point the text at it."""
    img_dir = ROOT / "media" / slug
    if img_dir.exists():
        shutil.rmtree(img_dir)

    def html_img(m):
        tag = m.group(0)
        src = re.search(r'src="([^"]+)"', tag)
        alt = re.search(r'alt="([^"]*)"', tag)
        return f"![{alt.group(1) if alt else ''}]({src.group(1)})" if src else tag

    text = re.sub(r"<img\b[^>]*>", html_img, text)
    count = 0

    def one(m):
        nonlocal count
        alt, url = m.group(1).strip(), m.group(2)
        if url.startswith("media/"):
            return m.group(0)
        if not url.startswith("https://"):
            raise IssueError(f"image link {url!r} is not a pasted image. Paste the picture into the box instead.")
        if not allowed_image_url(url):
            raise IssueError(f"image from {urllib.parse.urlparse(url).netloc} is not allowed: the site only serves its "
                             "own images. Paste the picture into the box instead.")
        count += 1
        data = get(url)
        if len(data) > MAX_IMAGE:
            raise IssueError(f"image {count} is larger than {MAX_IMAGE // 1024 // 1024} MB. Shrink it and paste it again.")
        ext = image_ext(data)
        if not ext:
            raise IssueError(f"image {count} is not a PNG, JPEG, GIF or WebP file.")
        if alt.lower() in ("", "image", "screenshot"):
            alt = f"Screenshot {count}"
        name = f"{count:02d}-{file_slug(alt)}.{ext}"
        img_dir.mkdir(parents=True, exist_ok=True)
        (img_dir / name).write_bytes(data)
        return f"![{alt}](media/{slug}/{name})"

    return re.sub(r'!\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)', one, text), count


def convert(issue, mode, today, get=fetch):
    f = parse_form(issue["body"] or "")
    slug = f["Short name"]
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug) or slug in build.RESERVED:
        raise IssueError(f"short name “{slug}” must be lowercase letters, digits and hyphens, and not one of "
                         f"{sorted(build.RESERVED)}.")
    if (ROOT / "posts" / f"{slug}.html").exists():
        raise IssueError(f"posts/{slug}.html is a hand-made HTML post; edit that file directly.")
    typ = f["Type"]
    if typ not in build.TYPES:
        raise IssueError(f"type must be one of {', '.join(build.TYPES)}.")
    title = (issue["title"] or "").strip()
    if not title or title == "Post title":
        raise IssueError("the issue title is the post title. Change it from “Post title”.")
    if not f["One-line summary"]:
        raise IssueError("the one-line summary is empty.")
    techniques = [t.upper() for t in re.split(r"[,\s]+", f["ATT&CK techniques (optional)"]) if t]
    bad = [t for t in techniques if not re.fullmatch(r"T\d{4}(\.\d{3})?", t)]
    if bad:
        raise IssueError(f"not ATT&CK technique IDs: {', '.join(bad)} (write them like T1110.001).")
    tool = f["Main tool (optional)"]
    tool = None if tool.lower() in ("", "none", "_no response_") else tool
    if not f["Post (Markdown)"]:
        raise IssueError("the post text is empty.")

    path = ROOT / "posts" / f"{slug}.md"
    meta = {}
    if path.exists():
        m = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
        meta = (yaml.safe_load(m.group(1)) or {}) if m else {}
    updating = bool(meta.get("date"))
    meta.update({"type": typ, "title": title, "summary": f["One-line summary"]})
    meta["techniques"] = techniques
    if tool:
        meta["tool"] = tool
    else:
        meta.pop("tool", None)
    if updating:
        meta["updated"] = today
    else:
        meta["date"] = today
    order = ["type", "title", "date", "updated", "summary", "techniques", "tool"]
    meta = {k: meta[k] for k in order if k in meta} | {k: v for k, v in meta.items() if k not in order}

    post = re.sub(r"<!--.*?-->", "", f["Post (Markdown)"], flags=re.S).strip()
    if not post or all(l.startswith("#") or not l.strip() for l in post.split("\n")):
        raise IssueError("the post has no text yet: only headings, or nothing, is left once the hints are removed.")
    text, n_images = pull_images(slug, post, get)
    front = yaml.safe_dump({k: (str(v) if k in ("date", "updated") else v) for k, v in meta.items()},
                           sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000)
    path.write_text(f"---\n{front}---\n\n{text.strip()}\n", encoding="utf-8")
    return {"slug": slug, "title": title, "images": n_images, "updating": updating}


def unpublish(issue):
    """Turn the post named in the issue back into a draft: the date goes, the file and images stay."""
    f = parse_form(issue["body"] or "")
    slug = f["Short name"]
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug) or slug in build.RESERVED:
        raise IssueError(f"short name “{slug}” is not valid.")
    path = ROOT / "posts" / f"{slug}.md"
    if not path.exists():
        raise IssueError(f"there is no posts/{slug}.md. Posts made as HTML files can only be changed in the repository.")
    m = re.match(r"---\n(.*?)\n---\n(.*)", path.read_text(encoding="utf-8"), re.S)
    if not m:
        raise IssueError(f"posts/{slug}.md has no front matter.")
    meta = yaml.safe_load(m.group(1)) or {}
    if not meta.get("date"):
        raise IssueError(f"{slug} is already a draft, nothing to unpublish.")
    meta.pop("date", None)
    meta.pop("updated", None)
    front = yaml.safe_dump({k: (str(v) if k == "updated" else v) for k, v in meta.items()}, sort_keys=False,
                           allow_unicode=True, default_flow_style=None, width=1000)
    path.write_text(f"---\n{front}date:\n---\n{m.group(2)}", encoding="utf-8")
    return {"slug": slug, "title": str(meta.get("title") or slug), "images": 0, "updating": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("issue")
    ap.add_argument("--mode", default="publish", choices=["publish", "check", "unpublish"])
    a = ap.parse_args()
    issue = json.loads(Path(a.issue).read_text(encoding="utf-8"))
    today = datetime.datetime.now(ZoneInfo("America/Edmonton")).date().isoformat()
    out = {"ok": "false", "slug": "", "title": ""}
    try:
        r = unpublish(issue) if a.mode == "unpublish" else convert(issue, a.mode, today)
        out.update(ok="true", slug=r["slug"], title=r["title"])
        print(f"{a.mode} {r['slug']}: {r['images']} image(s), {'update' if r['updating'] else 'new post'}")
    except (IssueError, OSError, ValueError) as ex:
        Path("comment.md").write_text(f"Not published. Problem: {ex}\n\nFix the issue and add the label again.\n",
                                      encoding="utf-8")
        print(f"error: {ex}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            for k, v in out.items():
                fh.write(f"{k}={v}\n")


if __name__ == "__main__":
    main()
