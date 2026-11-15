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

## Write from the browser (no Mac needed)

1. github.com/estul-lachin/writing > Issues > New issue > **one of the three forms** (incident report, investigation, note). The issue title is the post title; fill the
   short name, type and summary; write the post in Markdown and paste screenshots straight into the box.
2. Save the issue, then add the label **check**. A bot builds the post and runs the privacy check, and comments
   with the result. Nothing is published.
3. Fix the issue text if it complained, then add the label **publish**. The bot commits `posts/<id>.md` and the
   images, deploys, comments with the link and closes the issue.
4. To change a published post, edit its issue (reopen it if needed) and add **publish** again: the date stays,
   `updated` is set to today.

If the forms do not open, a plain issue works too: start the text with a `---` block (`slug`, `type`, `summary`,
optional `techniques` and `tool`), then the post. The bot's error message shows the block.

The labels are removed again when the run ends, so adding one again always starts a new run. Only issues opened
by the repository owner, with the label added by the owner, are ever processed.

**An issue is public the moment it is saved, and so are the pictures pasted into it.** Defang addresses while
writing, use only pseudonymized screenshots, and look at every picture before you paste it. If something slips
in, delete the picture from the issue and the issue itself; the check does not read pictures.

Branch protection note: if you turn on "require a pull request" for `main`, allow `github-actions` to bypass it,
or the publish bot cannot push.

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
- `tools/issue_to_post.py` turns a post-form issue into a post; `.github/workflows/publish.yml` runs it
- `site/` static files copied as they are (`style.css`, `favicon.svg`, `og-image.png`)
- `tools/build.py` the generator; writes `_site/` (not committed)
- `assets/og-image.html` source of the link preview image
