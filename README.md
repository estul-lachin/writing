# writing

Source of **https://uig.me/writing**: my incident reports, investigations and notes. One file per post.

## Write a post

1. Copy `posts/_template.md` to `posts/<id>.md` (lowercase, hyphens). The id is the address: `uig.me/writing/<id>/`.
2. Fill the front matter: `type` (`incident`, `investigation` or `note`), `title`, `summary`.
3. Write in Markdown. Put images in `media/<id>/` and link them as `media/<id>/name.png`.
4. Set `date` when it is finished. Without a date the post is a draft and is not published.
5. `python tools/build.py --check`, look at it locally, commit and push. GitHub Pages deploys it.

```
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/python tools/build.py --check
mkdir -p /tmp/w && rm -rf /tmp/w/writing && cp -r _site /tmp/w/writing && python3 -m http.server -d /tmp/w 8000
# open http://127.0.0.1:8000/writing/
```

A post can also be `posts/<id>.html`: the same front matter, then an HTML body that is used as it is, inside
`<div class="report">` or `<div class="article">` (`wrap:` in the front matter). The older reports with hand-made
tables and figures are kept that way.

## Privacy check

Everything here is public. `--check` fails the build when a page shows a public IP address, an email address or a
GUID:

- attacker addresses and URLs are written defanged: `198[.]51[.]100[.]7`, `hxxp[:]//`;
- honeypot sources in query results and screenshots are pseudonyms (`src-xxxxxxxx`), from the pseudonymized copy
  of the logs, never from the raw index;
- nothing from an employer or a client, ever;
- a value that really must appear (a mail relay in a how-to) is listed under `allow:` in that post's front matter.

The check reads text, not pictures: look at every screenshot before committing it.

## Layout

- `posts/` the posts; files starting with `_` are ignored
- `media/<id>/` a post's images
- `site/` static files copied as they are (`style.css`, `favicon.svg`, `og-image.png`)
- `tools/build.py` the generator; writes `_site/` (not committed)
- `assets/og-image.html` source of the link preview image
