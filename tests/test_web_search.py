import pytest
from language_tutor.web_search import (
    web_search_to_summary,
    documents_from_search_results,
    duckduckgo_search,
)


@pytest.mark.anyio
async def test_web_search_to_summary():
    summary = await web_search_to_summary("Python programming language", max_results=3)
    assert "Python" in summary


@pytest.mark.anyio
async def test_web_search_documents():
    hits = await duckduckgo_search("Python programming language", max_results=5)
    print(f"Hits:\n{hits}\n\n")
    assert len(hits) == 5
    docs = await documents_from_search_results(hits)
    print(f"Docs:\n{docs}\n\n")
    assert len(docs) == 5
