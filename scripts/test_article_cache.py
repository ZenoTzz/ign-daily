from __future__ import annotations

import unittest

from translate_titles_deepseek import extract_article_text, html_to_text


class ArticleCacheExtractionTests(unittest.TestCase):
    def test_article_links_keep_visible_anchor_text(self) -> None:
        html = """
        <article>
          <p data-cy="paragraph">According to a post on
            <a href="https://www.boardchannels.com.cn/thread-132900-1-1.html"
               class="link" data-cy="styled-link">Board Channels</a>, prices may rise.</p>
          <p data-cy="paragraph">A
            <a href="/articles/game-of-thrones-the-mad-king-cast-first-look"
               class="link" data-cy="styled-link">new stage play</a> is also planned.</p>
        </article>
        """
        text = extract_article_text(html, 2000)
        self.assertIn("Board Channels", text)
        self.assertIn("new stage play", text)

    def test_noise_container_is_still_removed(self) -> None:
        html = '<div class="recommended-content">Related story</div><p>Article text</p>'

        self.assertNotIn("Related story", html_to_text(html))


if __name__ == "__main__":
    unittest.main()
