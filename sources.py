"""
sources.py - builds the sources list from what the search tools really returned.
The AI no longer writes the sources itself, so it can't make up "Read more here."
"""

import re
from urllib.parse import urlparse

# A field ends where the next field starts, or where the result ends
_END = r"(?:, (?:title|link|date|source): |$)"


def _field(name, chunk):
    """Pulls one field, like the title or the link, out of one search result."""
    match = re.search(rf", {name}: (.+?){_END}", chunk, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def sources_from(steps, limit=5):
    """
    steps is raw_response["intermediate_steps"]: a list of (action, tool output).
    Returns up to 'limit' different sources, one line of text each.
    """
    # link -> text line. A dict keeps the order and drop repearts.
    found = {}
    for action, output in steps:
        text = str(output)

        # Wikipedia returns "Page: Title" lines instead of links
        if action.tool == "wikipedia":
            for title in re.findall(r"Page: (.+)$", text, flags=re.MULTILINE):
                title = title.strip()
                link = "https://en.wikipedia.org/wiki/" + \
                    title.replace(" ", "_")
                found.setdefault(link, f"Wikipedia: {title} - {link}")
            continue

        # Search tools return results joined by ", snippet: "
        for chunk in text.split(", snippet: "):
            title, link = _field("title", chunk), _field("link", chunk)
            if not title or not link:
                # an error message or plain text, not a result
                continue
            # Only news results have a source name. Otherwise Use the site name.
            name = _field("source", chunk) or urlparse(
                link).netloc.removeprefix("www.")
            date = _field("date", chunk)[:10]
            when = f", {date}" if date else ""
            found.setdefault(link, f"{name}{when}: {title} - {link}")

    return list(found.values())[:limit]


if __name__ == "__main__":
    from types import SimpleNamespace as Action

    news = ("snippet: Japan is heading to Mars' moons., title: Japan Launches Mars Mission. Here's What Happens Next, "
            "link: https://www.usatoday.com/story/graphics/2026/10/25/japan-mmx-mars-mission-moons/92350684007/, "
            "date: 2026-10-25T21:32:30+00:00, source: USA TODAY, "
            "snippet: Four crew members emerged after 378 days., title: Crew from NASA's simulated Mars mission emerge, "
            "link: https://www.msn.com/en-ie/news/national/crew-emerge/ar-AA2gBphO, "
            "date: 2026-11-02T21:32:30+00:00, source: Irish Examiner on MSN")
    web = ("snippet: Mars is the fourth planet., title: Mars - NASA Science, "
           "link: https://science.nasa.gov/mars/")
    wiki = "Page: Mars\nSummary: Mars is the fourth planet.\n\nPage: Mars mission\nSummary: Missions to Mars."
    failed = "News search failed just now. Try a different tool or tell the user."

    steps = [
        (Action(tool="news_search"), news),
        (Action(tool="government_search"), web),
        (Action(tool="wikipedia"), wiki),
        # same results again, should not repeat
        (Action(tool="news_search"), news),
        (Action(tool="news_search"), failed),  # should add nothing
    ]
    for line in sources_from(steps):
        print(line)
