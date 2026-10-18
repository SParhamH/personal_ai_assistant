import requests
from langchain_community.tools import (
    WikipediaQueryRun,
    DuckDuckGoSearchRun,
    DuckDuckGoSearchResults,
)
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_core.tools import Tool, tool
from datetime import datetime
from memory_search import search_memory
# save the response


def save_to_txt(data: str, filename: str = "output.txt"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_text = f"--- Output ---\nTimestamp: {timestamp}\n\n{data}\n\n"

    with open(filename, "a", encoding="utf-8") as f:
        f.write(formatted_text)

    return f"Data successfully saved to {filename}"

# Safe fail


def safe(func, name):
    """Wraps a search so a failure becomes a message the agent can read, not a crash."""
    def run(query):
        try:
            return func(query)
        except Exception:
            # Return text instead of raising, so the agent can try another tool
            return f"{name} failed just now. Try a different tool or tell the user."
    return run


# General web search
search = DuckDuckGoSearchRun()
search_tool = Tool(
    name="search",
    func=safe(search.run, "Web search"),
    description="Search the web for current information, prices, local info, or when trusted sources are not enough.",
)

# Wikipedia
api_wrapper = WikipediaAPIWrapper(top_k_results=2, doc_content_chars_max=1000)
wiki_tool = WikipediaQueryRun(api_wrapper=api_wrapper)

# News
news_search = DuckDuckGoSearchResults(backend="news", num_results=5)
news_tool = Tool(
    name="news_search",
    func=safe(news_search.run, "News search"),
    description="Search recent news. Use for current events and breaking news. Results include the source and date.",
)

# Trusted-source search (one search, limited to certain sites)
results_search = DuckDuckGoSearchResults(num_results=5)


def make_site_search(name, description, sites):
    """Builds a search tool that only looks at the given sites."""
    site_filter = " OR ".join(f"site:{s}" for s in sites)

    def run(query):
        try:
            return results_search.run(f"{query} ({site_filter})")
        except Exception as e:
            return f"Search failed: {e}"

    return Tool(name=name, func=run, description=description)


# Acadamic search
academic_tool = make_site_search(
    name="academic_search",
    description="Search academic sources (PubMed, arXiv preprints, Semantic Scholar). Use for research and scientific questions. arXiv papers are not always peer-reviewed.",
    sites=["pubmed.ncbi.nlm.nih.gov", "arxiv.org", "semanticscholar.org"],
)

# Goverment official search
government_tool = make_site_search(
    name="government_search",
    description="Search official US government sites (CDC, FDA, NIST, CISA, FBI, FTC, laws, public health, official guidance).",
    sites=["gov"],
)

# Education search
education_tool = make_site_search(
    name="education_search",
    description="Search university and educational sites. Use for learning material and school-friendly explanations.",
    sites=["edu", "khanacademy.org"],
)

# Collection of the trusted sources
trusted_tool = make_site_search(
    name="trusted_search",
    description="Search a mix of trusted sources (government, universities, WHO, Britannica, AP, Reuters, BBC, The New York Times). Use for general factual questions.",
    sites=["gov", "edu", "who.int", "britannica.com",
           "apnews.com", "reuters.com", "bbc.com", "nytimes.com"],
)

# Code search
code_tool = make_site_search(
    name="code_search",
    description="Search programming documentation and technical sources (Python docs, MDN, Microsoft Learn, SQLite, LangChain docs, PyPI, Real Python, Stack Overflow, GitHub). Use for library, API, error, or version questions. Prefer official docs over Stack Overflow.",
    sites=[
        "docs.python.org", "developer.mozilla.org", "learn.microsoft.com",
        "sqlite.org", "docs.langchain.com", "pypi.org",
        "realpython.com", "stackoverflow.com", "github.com",
    ],
)

# Seach memory
memory_tool = Tool(
    name="search_memory",
    func=search_memory,
    description="Search the user's past chats for a word or phrase. Use when the user asks what they said or discussed before."
)

# The list to pass to create_tool_calling_agent and AgentExecutor
tools = [
    search_tool,
    wiki_tool,
    news_tool,
    academic_tool,
    government_tool,
    education_tool,
    trusted_tool,
    code_tool,
    memory_tool,
]

# Planning to add weather, traffic, location
