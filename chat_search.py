from storage import list_sessions, load_json


def search_chat(keyword: str) -> str:
    """Finds past messages that contain all the important words."""
    # Lowercase, split into words
    # Skip tiny words like "of" and "the"
    # If every word was small (like "dog"), keep them all so we still have something to search for.
    all_words = keyword.lower().split()
    words = [w for w in keyword.lower().split() if len(w) > 3] or all_words

    # An empty search
    if not words:
        return "No keyword was given."

    found = []
    # Seach every saved chat, newest first
    for file in list_sessions():
        chat = load_json(file)
        for m in chat["messages"]:
            text = m["content"].lower()
            if all(w in text for w in words):
                # Cut long answers to 300 characters so one big reply doesn't flood the results
                found.append(
                    f"[{m['time']}] {m['role']}: {m['content'][:300]}")

    if not found:
        return f"No past messages mention '{keyword}'."

    # Return at most 10 results
    return "\n".join(found[:10])
