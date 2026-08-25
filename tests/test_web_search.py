"""Web-search tests.

The search and fetch paths run against a real HTTP server bound to loopback, so
they exercise the actual aiohttp/httpx/BeautifulSoup code without depending on
DuckDuckGo being reachable. Summarisation runs the real langchain-classic
map/reduce chain against a stub chat model, so no paid model call is made.
"""

from collections.abc import AsyncIterator
from typing import override
from urllib.parse import quote

import pytest
from aiohttp import web
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from language_tutor import web_search
from language_tutor.web_search import (
    documents_from_search_results,
    duckduckgo_search,
    extract_page_content,
    extract_real_url,
    summarize_documents,
    web_search_to_summary,
)

ARTICLE_HTML = """
<html><body>
  <nav><p>Navigation chrome that must never reach the summary.</p></nav>
  <main>
    <h1>El clima en la Ciudad de Mexico</h1>
    <p>La Ciudad de Mexico tiene un clima templado durante todo el ano.</p>
  </main>
</body></html>
"""

SECOND_ARTICLE_HTML = """
<html><body>
  <main>
    <p>La temporada de lluvias va de mayo a octubre en el valle de Mexico.</p>
  </main>
</body></html>
"""


def redirect_link(target: str) -> str:
    return f"/l/?uddg={quote(target, safe='')}&rut=tracking"


def results_page(base_url: str) -> str:
    """A DuckDuckGo-shaped result page: two organic hits, one ad, one malformed."""
    return f"""
    <html><body>
      <div class="web-result">
        <a class="result__a" href="{redirect_link(f"{base_url}/page/1")}">Clima CDMX</a>
        <div class="result__snippet">Clima templado todo el ano.</div>
      </div>
      <div class="web-result">
        <a class="result__a"
           href="{redirect_link("https://duckduckgo.com/y.js?ad_domain=anuncio.example")}">
          Anuncio patrocinado
        </a>
        <div class="result__snippet">Publicidad.</div>
      </div>
      <div class="web-result">
        <a class="result__a">Enlace sin href</a>
        <div class="result__snippet">Malformado.</div>
      </div>
      <div class="web-result">
        <a class="result__a" href="{redirect_link(f"{base_url}/page/2")}">Lluvias CDMX</a>
        <div class="result__snippet">Temporada de lluvias.</div>
      </div>
    </body></html>
    """


EMPTY_RESULTS_PAGE = """
<html><body><div class="no-results">No results found for that query.</div></body></html>
"""


class StubChatModel(FakeListChatModel):
    """A real chat model implementation that never leaves the process."""

    @override
    def get_num_tokens(self, text: str) -> int:
        return len(text.split())


@pytest.fixture
async def search_site(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """Serve DuckDuckGo-shaped search results and article pages over loopback."""
    base_url = ""

    async def handle_search(request: web.Request) -> web.Response:
        query = request.query.get("q", "")
        body = (
            EMPTY_RESULTS_PAGE if query == "sin resultados" else results_page(base_url)
        )
        return web.Response(text=body, content_type="text/html")

    async def handle_page(request: web.Request) -> web.Response:
        page = request.match_info["page"]
        body = ARTICLE_HTML if page == "1" else SECOND_ARTICLE_HTML
        return web.Response(text=body, content_type="text/html")

    async def handle_broken(_: web.Request) -> web.Response:
        raise web.HTTPInternalServerError()

    app = web.Application()
    app.router.add_get("/html/", handle_search)
    app.router.add_get("/page/{page}", handle_page)
    app.router.add_get("/broken", handle_broken)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    base_url = f"http://127.0.0.1:{port}"

    monkeypatch.setattr(web_search, "DUCKDUCKGO_HTML_URL", f"{base_url}/html/")
    try:
        yield base_url
    finally:
        await runner.cleanup()


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


@pytest.mark.anyio
async def test_search_returns_organic_results_and_drops_ads_and_malformed_links(
    search_site: str,
):
    hits = await duckduckgo_search("clima cdmx", max_results=5)

    assert [hit.url for hit in hits] == [
        f"{search_site}/page/1",
        f"{search_site}/page/2",
    ]
    assert hits[0].title == "Clima CDMX"
    assert hits[0].snippet == "Clima templado todo el ano."


@pytest.mark.anyio
async def test_search_honours_the_result_limit(search_site: str):
    hits = await duckduckgo_search("clima cdmx", max_results=1)

    assert [hit.url for hit in hits] == [f"{search_site}/page/1"]


@pytest.mark.anyio
async def test_search_returns_nothing_when_the_page_has_no_organic_results(
    search_site: str,
):
    assert await duckduckgo_search("sin resultados", max_results=5) == []


@pytest.mark.anyio
async def test_documents_extract_the_readable_page_content(search_site: str):
    hits = await duckduckgo_search("clima cdmx", max_results=5)

    docs = await documents_from_search_results(hits)

    assert [doc.metadata["source"] for doc in docs] == [
        f"{search_site}/page/1",
        f"{search_site}/page/2",
    ]
    assert "clima templado" in docs[0].page_content
    assert "Navigation chrome" not in docs[0].page_content
    assert "temporada de lluvias" in docs[1].page_content.lower()


@pytest.mark.anyio
async def test_documents_record_fetch_failures_instead_of_raising(search_site: str):
    hits = [
        web_search.WebSearchResult(
            url=f"{search_site}/broken", title="Roto", snippet=""
        )
    ]

    docs = await documents_from_search_results(hits)

    assert len(docs) == 1
    assert docs[0].page_content.startswith(f"[Error loading {search_site}/broken:")


@pytest.mark.anyio
async def test_documents_from_no_hits_is_empty():
    assert await documents_from_search_results([]) == []


@pytest.mark.anyio
async def test_summarize_documents_maps_each_page_then_reduces():
    llm = StubChatModel(responses=["resumen uno", "resumen dos", "resumen combinado"])
    docs = [
        Document(page_content="pagina uno", metadata={"source": "uno"}),
        Document(page_content="pagina dos", metadata={"source": "dos"}),
    ]

    summary = await summarize_documents(docs, llm)

    assert summary == "resumen combinado"


@pytest.mark.anyio
async def test_web_search_to_summary_searches_fetches_and_summarises(search_site: str):
    llm = StubChatModel(responses=["resumen uno", "resumen dos", "resumen combinado"])

    summary = await web_search_to_summary("clima cdmx", max_results=5, llm=llm)

    assert summary == "resumen combinado"


@pytest.mark.anyio
async def test_web_search_to_summary_reports_when_nothing_was_found(search_site: str):
    llm = StubChatModel(responses=["nunca usado"])

    summary = await web_search_to_summary("sin resultados", max_results=5, llm=llm)

    assert summary == "No results found."
