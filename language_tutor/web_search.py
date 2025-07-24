import aiohttp
from bs4 import BeautifulSoup, Tag
import httpx
from pydantic import BaseModel
from langchain.chains.summarize import load_summarize_chain
from langchain_openai import OpenAI
from langchain.schema import Document
from urllib.parse import urlparse, parse_qs, unquote
import asyncio

_url = "https://html.duckduckgo.com/html/"
_headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

_llm = OpenAI(temperature=0)
_summary_chain = load_summarize_chain(llm=_llm, chain_type="map_reduce")


def extract_real_url(duckduckgo_url: str) -> str | None:
    """
    Extract the real URL from DuckDuckGo's redirect URL.

    For DuckDuckGo URLs like:
    https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F&rut=...

    This extracts the URL from the 'uddg' parameter and URL-decodes it.
    For ad URLs, it returns None to skip them.
    """
    try:
        # Parse the URL
        parsed = urlparse(duckduckgo_url)

        # Get the query parameters
        query_params = parse_qs(parsed.query)

        # Extract the 'uddg' parameter which contains the real URL
        if "uddg" in query_params:
            real_url = unquote(query_params["uddg"][0])

            # Skip ad URLs that go through DuckDuckGo's ad system
            if "duckduckgo.com/y.js" in real_url or "ad_domain=" in real_url:
                return None

            # For regular (non-ad) URLs, ensure proper protocol
            if real_url.startswith("//"):
                real_url = "https:" + real_url
            elif not real_url.startswith(("http://", "https://")):
                real_url = "https://" + real_url

            return real_url
    except Exception:
        pass

    # If extraction fails, ensure the original URL at least has https if it's not an ad
    if "duckduckgo.com/y.js" in duckduckgo_url or "ad_domain=" in duckduckgo_url:
        return None

    if duckduckgo_url.startswith("//"):
        return "https:" + duckduckgo_url
    elif not duckduckgo_url.startswith(("http://", "https://")):
        return "https://" + duckduckgo_url

    return duckduckgo_url


class WebSearchResult(BaseModel):
    url: str
    title: str
    snippet: str


async def duckduckgo_search(query: str, max_results: int = 5) -> list[WebSearchResult]:
    params = {"q": query, "kl": "us-en"}

    async with aiohttp.ClientSession() as session:
        async with session.get(_url, params=params, headers=_headers) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")
    results = []

    # Try different selectors that DuckDuckGo might use, prioritizing organic results
    # First try to get organic results, then fall back to all results
    result_containers = []

    # Try web-result first (seems to exclude ads)
    web_results = soup.find_all("div", class_="web-result")
    if web_results:
        result_containers.extend(web_results)

    # If we don't have enough, add more from other selectors
    if (
        len(result_containers) < max_results * 2
    ):  # Get extra since some will be filtered
        other_results = (
            soup.find_all("div", class_="result__body")
            or soup.find_all("div", class_="result")
            or soup.find_all("article")
        )

        # Add results we don't already have
        for result in other_results:
            if result not in result_containers:
                result_containers.append(result)
                if (
                    len(result_containers) >= max_results * 3
                ):  # Get plenty of candidates
                    break

    for result in result_containers:
        # Try different link selectors
        title_tag = (
            result.find("a", class_="result__a")
            or result.find("a", class_="result__url")
            or (result.find("h2") and result.find("h2").find("a"))
            or result.find("a")
        )

        # Try different snippet selectors
        snippet_tag = (
            result.find(class_="result__snippet")
            or result.find(class_="snippet")
            or result.find(class_="description")
            or result.find("p")
        )

        # Ensure we have a valid tag with href attribute
        if not title_tag or not hasattr(title_tag, "get") or not title_tag.get("href"):
            continue

        raw_link = str(title_tag.get("href", ""))
        # Extract the real URL from DuckDuckGo's redirect
        link = extract_real_url(raw_link)

        # Skip ad URLs or URLs we couldn't extract
        if not link:
            continue

        # Get text content safely
        title = title_tag.get_text().strip() if hasattr(title_tag, "get_text") else ""
        snippet = (
            snippet_tag.get_text().strip()
            if snippet_tag and hasattr(snippet_tag, "get_text")
            else ""
        )

        # Skip empty results
        if not link or not title:
            continue

        results.append(WebSearchResult(url=link, title=title, snippet=snippet))

        if len(results) >= max_results:
            break
    return results


async def documents_from_search_results(hits: list[WebSearchResult]) -> list[Document]:
    if not hits:
        return []

    async def fetch_single_document(
        client: httpx.AsyncClient, result: WebSearchResult
    ) -> Document:
        """Fetch and extract content from a single URL."""
        try:
            resp = await client.get(result.url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Extract meaningful content from the page
            text = extract_page_content(soup)

        except Exception as e:
            text = f"[Error loading {result.url}: {e}]"

        return Document(page_content=text, metadata={"source": result.url})

    # Fetch all documents in parallel
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [fetch_single_document(client, hit) for hit in hits]
        docs = await asyncio.gather(*tasks)

    return docs


def extract_page_content(soup: BeautifulSoup) -> str:
    """
    Extract meaningful content from a web page, prioritizing main content areas.
    """
    # Remove script and style elements
    for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
        script.decompose()

    # Try to find main content areas first
    content_selectors = [
        "main",
        "article",
        ".content",
        ".main-content",
        "#content",
        "#main",
        ".post-content",
        ".entry-content",
        ".article-body",
        ".page-content",
    ]

    for selector in content_selectors:
        content_area = soup.select_one(selector)
        if content_area:
            # Get all paragraphs and headings from the content area
            text_elements = content_area.find_all(
                ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"]
            )
            if text_elements:
                texts = []
                for elem in text_elements[:25]:  # Limit to first 25 elements
                    text = elem.get_text().strip()
                    if len(text) > 20:  # Only include substantial text
                        texts.append(text)
                if texts:
                    content = " ".join(texts)
                    # Limit total length
                    if len(content) > 5000:
                        content = content[:5000] + "..."
                    return content

    # Fallback: get all paragraphs from the entire page
    paragraphs = soup.find_all("p")
    if paragraphs:
        texts = []
        for p in paragraphs[:20]:  # Limit to first 20 paragraphs
            text = p.get_text().strip()
            if len(text) > 20:  # Only include substantial text
                texts.append(text)
        if texts:
            content = " ".join(texts)
            # Limit total length
            if len(content) > 5000:
                content = content[:5000] + "..."
            return content

    # Last resort: get the page title and meta description
    title = soup.find("title")
    title_text = title.get_text().strip() if title else ""

    meta_desc = soup.find("meta", attrs={"name": "description"})
    desc_text = ""
    if meta_desc and isinstance(meta_desc, Tag):
        desc_text = meta_desc.get("content", "") or ""

    if title_text or desc_text:
        return f"{title_text}. {desc_text}".strip()

    return "[No meaningful content found]"


async def web_search_to_summary(query: str, max_results: int = 5) -> str:
    """
    Perform a web search and return the summary of the results.
    """
    hits = await duckduckgo_search(query, max_results=max_results)
    docs = await documents_from_search_results(hits)
    return await _summary_chain.arun(docs) if docs else "No results found."
