#!/usr/bin/env python3
"""Render uig.me/writing: incident reports, investigations and notes, one file per post.

  posts/<id>.md      front matter + Markdown (the normal case)
  posts/<id>.html    front matter + an HTML body, used as it is (reports with hand-made tables and figures)
  media/<id>/        that post's images; link them as media/<id>/name.png

Front matter:
  title:        required
  type:         incident | investigation | note
  date:         YYYY-MM-DD when published; empty = draft, left out of the site
  updated:      YYYY-MM-DD (optional)
  summary:      one line for the lists and link previews
  techniques:   ATT&CK IDs, e.g. [T1110.001, T1105] (optional)
  tool:         splunk | sentinel | wazuh, the SIEM the work was led in (optional)
  incident:     Sentinel incident number (optional)
  playbooks:    ids of uig.me/investigations playbooks used (optional)
  allow:        public IPs or emails this post may show undefanged, e.g. a mail relay in a how-to (optional)
  wrap:         class around an HTML body: report | article (HTML posts only)
  og_image:     link preview image for this post, media/<id>/name.png or .jpg (optional; default og-image.png)

  python tools/build.py [--site _site] [--check]

Plain HTML and CSS, no JavaScript. Every value is escaped, except the post bodies I wrote.
--check fails if the built site shows a public IP, an email address or a GUID that no post allows:
write attacker addresses defanged (198[.]51[.]100[.]7) and use pseudonyms (src-xxxxxxxx) for honeypot sources.
"""

import argparse
import datetime
import html
import json
import re
import shutil
import sys
from pathlib import Path

import markdown
import yaml

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://uig.me/writing"
REPO = "https://github.com/estul-lachin/writing"
OWNER = "Estul Lachin"
TYPES = {  # type: (label, plural label, list path)
    "incident": ("Incident report", "Incident reports", "incident-reports"),
    "investigation": ("Investigation", "Investigations", "investigations"),
    "note": ("Note", "Notes", "notes"),
}
TOOLS = {"splunk": "Splunk", "sentinel": "Microsoft Sentinel", "wazuh": "Wazuh"}
CSP = "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'"
DESCRIPTION = ("Incident reports, investigations and notes by Estul Lachin, SOC analyst: "
               "real attacks on my own servers, written up.")
RESERVED = {t[2] for t in TYPES.values()} | {"media"}

e = html.escape


class SourceError(Exception):
    pass


OG_DEFAULT = "og-image.png"


def og_image_path(v, post_id, where):
    """The og_image value, checked: a PNG or JPEG of this post, under media/<id>/. None when not set."""
    if v in (None, ""):
        return None
    v = str(v).strip()
    if not re.fullmatch(r"media/" + re.escape(post_id) + r"/[A-Za-z0-9_-][A-Za-z0-9._-]*\.(png|jpe?g)", v) or ".." in v:
        raise SourceError(f"{where}: og_image must be media/{post_id}/<name>.png or .jpg, got {v!r}")
    return v


def png_size(path):
    """(width, height) of a PNG file, or None if it is missing or not a PNG."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def as_date(v, where):
    if v in (None, ""):
        return None
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v
    raise SourceError(f"{where}: dates must be YYYY-MM-DD, got {v!r}")


def load_posts():
    out = []
    for p in sorted(ROOT.glob("posts/*")):
        if p.name.startswith("_") or p.suffix not in (".md", ".html"):
            continue
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", p.stem) or p.stem in RESERVED:
            raise SourceError(f"{p.name}: file name must be lowercase-hyphenated and not one of {sorted(RESERVED)}")
        m = re.match(r"---\n(.*?)\n---\n?(.*)", p.read_text(encoding="utf-8"), re.S)
        if not m:
            raise SourceError(f"{p.name}: no front matter (--- ... ---)")
        meta = yaml.safe_load(m.group(1)) or {}
        if meta.get("type") not in TYPES:
            raise SourceError(f"{p.name}: type must be one of {', '.join(TYPES)}")
        if not meta.get("title"):
            raise SourceError(f"{p.name}: title is required")
        if meta.get("tool") and meta["tool"] not in TOOLS:
            raise SourceError(f"{p.name}: tool must be one of {', '.join(TOOLS)}")
        out.append({"id": p.stem, "html": p.suffix == ".html", "title": str(meta["title"]), "type": meta["type"],
                    "date": as_date(meta.get("date"), p.name), "updated": as_date(meta.get("updated"), p.name),
                    "summary": str(meta.get("summary") or ""), "techniques": meta.get("techniques") or [],
                    "tool": meta.get("tool"), "incident": meta.get("incident"),
                    "playbooks": meta.get("playbooks") or [], "allow": [str(a) for a in meta.get("allow") or []],
                    "wrap": meta.get("wrap") or "article", "body": m.group(2),
                    "og_image": og_image_path(meta.get("og_image"), p.stem, p.name)})
    if len({p["id"] for p in out}) != len(out):
        raise SourceError("two posts share an id (one .md and one .html with the same name)")
    return out


def og_tags(og_image, og_alt):
    """og:image tags: the post's own image when it has one, else the site default (1200x630)."""
    if not og_image:
        size, url, alt = (1200, 630), f"{SITE}/{OG_DEFAULT}", f"{OWNER}: writing"
    else:
        size, url, alt = png_size(ROOT / og_image), f"{SITE}/{og_image}", og_alt or f"{OWNER}: writing"
    tags = [f'<meta property="og:image" content="{e(url)}">']
    if size:
        tags += [f'<meta property="og:image:width" content="{size[0]}">',
                 f'<meta property="og:image:height" content="{size[1]}">']
    tags.append(f'<meta property="og:image:alt" content="{e(alt)}">')
    return "\n".join(tags)


def page(title, body, depth, description=DESCRIPTION, path="", og_image=None, og_alt=None):
    rel = "/writing/" if depth is None else "../" * depth
    home = rel or "./"
    full = f"Writing · {OWNER}" if not title else f"{title} · {OWNER}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>{e(full)}</title>
<meta name="description" content="{e(description)}">
<meta property="og:title" content="{e(full)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="{"article" if depth == 1 and path else "website"}">
<meta property="og:url" content="{SITE}/{path}">
<link rel="canonical" href="{SITE}/{path}">
{og_tags(og_image, og_alt)}
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{rel}favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{rel}style.css">
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <div class="crumb"><a class="brand" href="https://uig.me/">{OWNER}</a><a class="section" href="{home}">Writing</a></div>
    <nav>
      <a href="https://uig.me/#work">Work</a>
      <a href="{home}" aria-current="page">Writing</a>
      <a href="https://uig.me/about/">About</a>
      <a href="https://uig.me/Estul-Lachin-Resume.pdf">Résumé</a>
    </nav>
  </div>
</header>
<main class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <a href="https://www.linkedin.com/in/estul-lachin">LinkedIn</a> ·
    <a href="https://github.com/estul-lachin">GitHub</a> ·
    <a href="{REPO}">Source</a>
    <p class="credit">Attacker addresses are defanged; honeypot sources in query results are pseudonyms (src-xxxxxxxx).</p>
  </div>
</footer>
</body>
</html>
"""


def long_date(d):
    return datetime.date.fromisoformat(d).strftime("%-d %B %Y")


def chips(techniques):
    return " ".join(f'<a class="chip" href="https://attack.mitre.org/techniques/{e(str(t).replace(".", "/"))}/" '
                    f'rel="noopener">{e(str(t))}</a>' for t in techniques)


def media_paths(text):
    """media/<id>/x.png in a post points at the site's /media/, one level up from the post's page."""
    return re.sub(r'(src|href|srcset)="media/', r'\1="../media/', text)


def post_list(posts, rel):
    if not posts:
        return '<p class="muted">Nothing here yet.</p>'
    rows = "".join(
        f'<a href="{rel}{p["id"]}/"><time datetime="{p["date"]}">{p["date"]}</time>'
        f'<span class="what"><b>{e(p["title"])}</b>{"<span>" + e(p["summary"]) + "</span>" if p["summary"] else ""}</span>'
        f'<span class="kind">{e(TYPES[p["type"]][0])}</span></a>' for p in posts)
    return f'<div class="list">{rows}</div>'


def list_page(posts, current):
    """current: None for every post, or a type."""
    rel = "" if current is None else "../"
    tabs = [("All", rel or "./", None)] + [(t[1], f"{rel}{t[2]}/", k) for k, t in TYPES.items()
                                            if any(p["type"] == k for p in posts)]
    filt = " · ".join(f'<a href="{h}"{" aria-current=\"page\"" if k == current else ""}>{e(n)}</a>'
                      for n, h, k in tabs)
    shown = [p for p in posts if current in (None, p["type"])]
    title = "" if current is None else TYPES[current][1]
    body = f"""<h1>{e(title or "Writing")}</h1>
<p class="lead">Incident reports, investigations and notes. The reports are real attacks on my own servers:
what happened, how I know, and what I changed afterwards.</p>
<p class="subnav">{filt}</p>
{post_list(shown, rel)}"""
    return page(title, body, 0 if current is None else 1, path="" if current is None else f"{TYPES[current][2]}/")


def post_page(p):
    label, _, path = TYPES[p["type"]]
    crumb = f'<p class="kicker"><a href="../">Writing</a> / <a href="../{path}/">{e(label.lower())}</a></p>'
    if p["html"]:
        body = f'{crumb}\n<div class="{e(p["wrap"])}">\n{media_paths(p["body"])}\n</div>'
    else:
        text = markdown.Markdown(extensions=["extra", "sane_lists"], output_format="html").convert(p["body"])
        bits = [f'<time datetime="{p["date"]}">{long_date(p["date"])}</time>']
        if p["updated"]:
            bits.append(f"updated {long_date(p['updated'])}")
        if p["tool"]:
            bits.append(f'led in <span class="tool">{e(TOOLS[p["tool"]])}</span>')
        if p["incident"]:
            bits.append(f"Sentinel incident #{e(str(p['incident']))}")
        extra = ""
        if p["playbooks"]:
            extra = "<h2>Queries used</h2><ul>" + "".join(
                f'<li><a href="https://uig.me/investigations/playbooks/{e(str(b))}/">{e(str(b))}</a></li>'
                for b in p["playbooks"]) + "</ul>"
        body = f"""{crumb}
<h1>{e(p["title"])}</h1>
<p class="meta">{" · ".join(bits)} {chips(p["techniques"])}</p>
<div class="prose">{media_paths(text)}{extra}</div>"""
    return page(p["title"], body, 1, p["summary"] or DESCRIPTION, f"{p['id']}/",
                og_image=p.get("og_image"), og_alt=p["title"])


ALLOWED_NETS = (r"^(10|127)\.", r"^192\.168\.", r"^172\.(1[6-9]|2\d|3[01])\.", r"^192\.0\.2\.", r"^198\.51\.100\.",
                r"^203\.0\.113\.", r"^0\.0\.0\.0$", r"^255\.")
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z.]{2,}")
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
OWN_EMAILS = {"hello@uig.me"}


def leak_scan(site, allow):
    """allow: {page path under the site: values that post's front matter allows}."""
    problems = []
    for f in sorted(site.rglob("*")):
        if f.suffix not in (".html", ".json", ".xml", ".txt"):
            continue
        name = str(f.relative_to(site))
        ok = allow.get(name, set()) | OWN_EMAILS
        text = f.read_text(encoding="utf-8", errors="replace")
        for ip in set(IPV4.findall(text)):
            if (all(int(o) <= 255 for o in ip.split(".")) and not any(re.match(n, ip) for n in ALLOWED_NETS)
                    and ip not in ok):
                problems.append(f"{name}: public IP {ip}")
        problems += [f"{name}: email {m}" for m in set(EMAIL.findall(text)) if m not in ok]
        problems += [f"{name}: GUID {m}" for m in set(GUID.findall(text))]
    return problems


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(out):
    posts = [p for p in load_posts() if p["date"]]
    posts.sort(key=lambda p: (p["date"], p["id"]), reverse=True)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    problems = []
    for p in posts:
        src = ROOT / "media" / p["id"]
        if src.is_dir():
            shutil.copytree(src, out / "media" / p["id"])
        if p.get("og_image") and not (ROOT / p["og_image"]).is_file():
            problems.append(f"{p['id']}: missing og_image {p['og_image']}")
        html_text = post_page(p)
        for ref in re.findall(r'(?:src|href)="\.\./media/([^"]+)"', html_text):
            if not (ROOT / "media" / ref).is_file():
                problems.append(f"{p['id']}: missing image media/{ref}")
        write(out / p["id"] / "index.html", html_text)
    write(out / "index.html", list_page(posts, None))
    urls = [f"{SITE}/"]
    for k, t in TYPES.items():
        if any(p["type"] == k for p in posts):
            write(out / t[2] / "index.html", list_page(posts, k))
            urls.append(f"{SITE}/{t[2]}/")
    urls += [f"{SITE}/{p['id']}/" for p in posts]
    write(out / "404.html", page("Not found", '<h1>Not found</h1>\n<p>That page does not exist. '
                                 '<a href="/writing/">All writing</a>.</p>', None))
    summary = {"posts": len(posts), **{t[2].replace("-", "_"): sum(p["type"] == k for p in posts)
                                        for k, t in TYPES.items()},
               "latest": posts[0]["date"] if posts else None}
    write(out / "summary.json", json.dumps(summary, indent=1) + "\n")
    write(out / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    problems += leak_scan(out, {f"{p['id']}/index.html": set(p["allow"]) for p in posts})
    return summary, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", default="_site", help="output directory (default _site)")
    ap.add_argument("--check", action="store_true", help="fail on leaks or missing images")
    a = ap.parse_args(argv)
    try:
        summary, problems = build(ROOT / a.site)
    except (SourceError, yaml.YAMLError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    for p in problems:
        print(("error: " if a.check else "warning: ") + p, file=sys.stderr)
    print(f"built {a.site}/: {summary['posts']} posts ({summary['incident_reports']} incident reports, "
          f"{summary['investigations']} investigations, {summary['notes']} notes)")
    return 1 if (a.check and problems) else 0


if __name__ == "__main__":
    sys.exit(main())
