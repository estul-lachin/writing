"""Per-post og_image: front matter, page tags, build check, and the issue bot keeping the file.

    python -m unittest discover -s tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build  # noqa: E402
import issue_to_post  # noqa: E402


def png(width, height):
    """The first 24 bytes of a PNG are enough for png_size."""
    return (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
            + width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")


POST = """---
type: incident
title: 'Test report'
date: '2026-11-14'
summary: One line.
{extra}---
<p>Body <img src="media/test-post/fig.svg" alt="Figure"></p>
"""

ISSUE = """---
slug: test-post
type: incident
summary: One line.
date: 2026-11-14
updated: 2026-11-16
format: html
wrap: report
{extra}---

<p>Body <img src="media/test-post/fig.svg" alt="Figure"></p>
"""


class TempRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "posts").mkdir()
        (self.root / "site").mkdir()
        self.media = self.root / "media" / "test-post"
        self.media.mkdir(parents=True)
        (self.media / "fig.svg").write_text("<svg/>")
        self.saved = build.ROOT, issue_to_post.ROOT
        build.ROOT = issue_to_post.ROOT = self.root

    def tearDown(self):
        build.ROOT, issue_to_post.ROOT = self.saved
        self.tmp.cleanup()

    def write_post(self, extra=""):
        (self.root / "posts" / "test-post.html").write_text(POST.format(extra=extra), encoding="utf-8")


class PageTags(TempRoot):
    def test_default_image_when_not_set(self):
        self.write_post()
        [p] = build.load_posts()
        self.assertIsNone(p["og_image"])
        html = build.post_page(p)
        self.assertIn(f'<meta property="og:image" content="{build.SITE}/og-image.png">', html)
        self.assertIn('<meta property="og:image:width" content="1200">', html)
        self.assertIn('<meta property="og:image:height" content="630">', html)
        self.assertIn('<meta property="og:image:alt" content="Estul Lachin: writing">', html)

    def test_list_pages_keep_default(self):
        html = build.list_page([], None)
        self.assertIn(f'content="{build.SITE}/og-image.png"', html)

    def test_post_image_used_with_its_own_size(self):
        (self.media / "og.png").write_bytes(png(1200, 630))
        self.write_post("og_image: media/test-post/og.png\n")
        [p] = build.load_posts()
        html = build.post_page(p)
        self.assertIn(f'<meta property="og:image" content="{build.SITE}/media/test-post/og.png">', html)
        self.assertNotIn("og-image.png", html)
        self.assertIn('<meta property="og:image:width" content="1200">', html)
        self.assertIn('<meta property="og:image:height" content="630">', html)
        self.assertIn('<meta property="og:image:alt" content="Test report">', html)

    def test_size_read_from_file(self):
        (self.media / "og.png").write_bytes(png(800, 418))
        self.write_post("og_image: media/test-post/og.png\n")
        html = build.post_page(build.load_posts()[0])
        self.assertIn('og:image:width" content="800"', html)
        self.assertIn('og:image:height" content="418"', html)

    def test_jpeg_has_no_size_tags(self):
        (self.media / "og.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        self.write_post("og_image: media/test-post/og.jpg\n")
        html = build.post_page(build.load_posts()[0])
        self.assertIn('content="https://uig.me/writing/media/test-post/og.jpg"', html)
        self.assertNotIn("og:image:width", html)

    def test_rejects_paths_outside_the_post(self):
        for bad in ("media/other-post/og.png", "og-image.png", "media/test-post/../x/og.png",
                    "https://example.com/og.png", "media/test-post/og.svg", "media/test-post/sub/og.png"):
            with self.subTest(bad=bad):
                self.write_post(f"og_image: '{bad}'\n")
                with self.assertRaises(build.SourceError):
                    build.load_posts()


class BuildCheck(TempRoot):
    def test_missing_file_is_a_problem(self):
        self.write_post("og_image: media/test-post/og.png\n")
        _, problems = build.build(self.root / "_site")
        self.assertIn("test-post: missing og_image media/test-post/og.png", problems)

    def test_present_file_is_copied(self):
        (self.media / "og.png").write_bytes(png(1200, 630))
        self.write_post("og_image: media/test-post/og.png\n")
        _, problems = build.build(self.root / "_site")
        self.assertEqual(problems, [])
        self.assertTrue((self.root / "_site" / "media" / "test-post" / "og.png").is_file())


class IssueBot(TempRoot):
    def convert(self, extra=""):
        issue = {"title": "Test report", "body": ISSUE.format(extra=extra)}
        return issue_to_post.convert(issue, "publish", "2026-11-16")

    def front(self):
        text = (self.root / "posts" / "test-post.html").read_text(encoding="utf-8")
        return text.split("---\n")[1]

    def test_og_image_kept_and_written(self):
        (self.media / "og.png").write_bytes(png(1200, 630))
        (self.media / "stale.png").write_bytes(png(1, 1))
        self.convert("og_image: media/test-post/og.png\n")
        self.assertTrue((self.media / "og.png").is_file())
        self.assertFalse((self.media / "stale.png").exists())
        self.assertTrue((self.media / "fig.svg").is_file())
        self.assertIn("og_image: media/test-post/og.png", self.front())
        self.assertIn("updated: '2026-11-16'", self.front())

    def test_removed_from_issue_removes_it(self):
        (self.media / "og.png").write_bytes(png(1200, 630))
        self.convert("og_image: media/test-post/og.png\n")
        self.convert()
        self.assertNotIn("og_image", self.front())
        self.assertFalse((self.media / "og.png").exists())

    def test_bad_path_is_refused(self):
        with self.assertRaises(issue_to_post.IssueError):
            self.convert("og_image: media/other-post/og.png\n")

    def test_missing_file_is_refused(self):
        with self.assertRaises(issue_to_post.IssueError):
            self.convert("og_image: media/test-post/og.png\n")

    def test_drop_unreferenced_keep(self):
        (self.media / "og.png").write_bytes(png(1200, 630))
        issue_to_post.drop_unreferenced("test-post", "no images here", ["media/test-post/og.png"])
        self.assertTrue((self.media / "og.png").is_file())
        self.assertFalse((self.media / "fig.svg").exists())


if __name__ == "__main__":
    unittest.main()
