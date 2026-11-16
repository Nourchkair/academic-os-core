from __future__ import annotations

import io

import pytest

from academia_os.web_search import WebSearchError, parse_results, search


BODY = """
<div class="result">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Frousseau">Rousseau &amp; the social contract</a>
  <a class="result__snippet" href="#">An overview of the <b>general will</b>.</a>
</div>
<div class="result">
  <a rel="nofollow" class="result__a" href="https://plato.stanford.edu/entries/rousseau/">Stanford Encyclopedia: Rousseau</a>
  <a class="result__snippet" href="#">Rousseau's political philosophy.</a>
</div>
"""


def test_parse_results_decodes_redirects_and_strips_tags() -> None:
    results = parse_results(BODY, limit=5)
    assert results[0]["url"] == "https://example.org/rousseau"
    assert results[0]["title"] == "Rousseau & the social contract"
    assert results[0]["snippet"] == "An overview of the general will."
    assert results[1]["url"] == "https://plato.stanford.edu/entries/rousseau/"


def test_search_requires_a_query() -> None:
    with pytest.raises(WebSearchError, match="query"):
        search("   ")


def test_search_uses_the_injected_opener() -> None:
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()
            return False

    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response(BODY.encode("utf-8"))

    results = search("rousseau social contract", 2, opener=opener)
    assert "q=rousseau+social+contract" in captured["url"]
    assert len(results) == 2


def test_search_reports_empty_results() -> None:
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    with pytest.raises(WebSearchError, match="no web results"):
        search("zzz", opener=lambda request, timeout=None: Response(b"<html></html>"))
