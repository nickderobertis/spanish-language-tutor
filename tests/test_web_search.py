from bs4 import BeautifulSoup

from language_tutor.web_search import extract_page_content, extract_real_url


def test_extract_real_url_from_search_redirect():
    redirect = (
        "https://duckduckgo.com/l/?uddg="
        "https%3A%2F%2Fwww.python.org%2Fabout%2F&rut=tracking"
    )

    assert extract_real_url(redirect) == "https://www.python.org/about/"


def test_extract_real_url_rejects_ad_redirect():
    redirect = (
        "https://duckduckgo.com/l/?uddg="
        "https%3A%2F%2Fduckduckgo.com%2Fy.js%3Fad_domain%3Dexample.com"
    )

    assert extract_real_url(redirect) is None


def test_extract_page_content_prefers_main_content():
    soup = BeautifulSoup(
        """
        <html><body>
          <nav><p>This navigation sentence must not be returned.</p></nav>
          <main>
            <h1>Python programming language overview</h1>
            <p>Python is a programming language designed for readable code.</p>
          </main>
        </body></html>
        """,
        "lxml",
    )

    content = extract_page_content(soup)

    assert "Python is a programming language" in content
    assert "navigation" not in content
