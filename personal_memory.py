"""
personal_memory.py - the assistant's personal memory.
Memories are saved in memory/ as JSON files you can open and read.
"""

from pathlib import Path
from datetime import date
import json
import copy
import re


# the AI function from main.py, given through setup()
_ask_llm = None

MEMORY_FOLDER = Path("memory")

# Active memories
MEMORIES_FILE = MEMORY_FOLDER / "memories.json"
MAX_IN_PROMPT = 10

# Inbox suggestions
INBOX_FILE = MEMORY_FOLDER / "inbox.json"
LEARN_EVERY = 6

# How many times an idea must come up before it's shown, after 0, 1, 2... skips
ASK_AT = [1, 3, 8, 16, 32]


# What each file looks like before anything is saved.
# More files (inbox, archive) get added here in later steps.
DEFAULTS = {
    MEMORIES_FILE: {"next_id": 1, "memories": []},
    INBOX_FILE: {"pending_messages": [], "suggestions": []}
}


# Read memory file
def _load(path):
    if not path.exists():
        # A copy, so changing what we return never changes DEFAULTS itself
        return copy.deepcopy(DEFAULTS[path])
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Write memory file
def _save(path, data):
    MEMORY_FOLDER.mkdir(exist_ok=True)

    # Write a temp file first, then swap it in.
    # Write to a temp file first so that if the program crashes while writing, real memories.json stays whole
    temp = path.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    temp.replace(path)


# AI assistant to orginize the memory
def setup(ask_llm):
    """Call once when the assistant starts. ask_llm: prompt text in, reply text out."""
    global _ask_llm
    _ask_llm = ask_llm


def _parse_json_list(reply):
    """AI replies are messy (code fences, extra words), so pull out just the [ ... ] part."""
    start, end = reply.find("["), reply.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        items = json.loads(reply[start:end + 1])
    except json.JSONDecodeError:
        return []
    # Keep only items shaped like {"memory": "...", ...}
    return [i for i in items if isinstance(i, dict) and i.get("memory")]


def _ask_ai(text):
    """Ask the AI to turn the user's words into short, categorized memories."""
    memories = _load(MEMORIES_FILE)["memories"]
    categories = sorted({m.get("category", "other") for m in memories})
    prompt = f"""
You are the long-term memory of a personal AI assistant.
The user asked you to remember something. Turn their message into memories.

Rules:
- One idea per memory. Split "I like simple answers with examples" into "Likes simple answers" and "Likes examples in explanations".
- memory: one short, plain sentence about the user, like "Studies computer science".
- category: reuse an existing category if one fits. Otherwise make a short lowercase one (1 or 2 words, with _ instead of spaces).
- Never save passwords, keys, or ID numbers.

Existing categories: {", ".join(categories) or "none yet"}

Reply with ONLY a JSON list, like:
[{{"memory": "Likes simple answers", "category": "answer_style"}}]

Message: {text}
"""
    return _parse_json_list(_ask_llm(prompt))


# Using AI for suggestion to add to memory
def _find_suggestions(messages):
    """Ask the AI what's worth remembering in the user's recent messages."""
    memories = _load(MEMORIES_FILE)["memories"]
    suggestions = _load(INBOX_FILE)["suggestions"]
    saved = "\n".join(f"- {m['text']}" for m in memories) or "none yet"
    waiting = "\n".join(f"- {s['memory']}" for s in suggestions) or "none"
    # Categories from saved memories AND waiting suggestions, so the AI reuses them
    categories = sorted({m.get("category", "other") for m in memories}
                        | {_clean_category(s.get("category")) for s in suggestions})
    numbered = "\n".join(f"{n}. {m}" for n, m in enumerate(messages, start=1))
    prompt = f"""
You are the long-term memory of a personal AI assistant.
Read the user's recent messages and find things worth remembering about them:
facts (studies, projects, goals, tools), how they like answers written or explained,
how they code, and how they like to communicate.

Rules:
- Only keep things that will still matter next month. Skip one-time requests and plain questions.
- Skip private topics like health, money, or family problems, because the user didn't ask to save those.
- Never save passwords, keys, or ID numbers.
- Don't suggest anything that is already saved (see the list below).
- One idea per memory, as one short sentence about the user.
- category: reuse an existing category if one fits. Otherwise make a short lowercase one, with _ instead of spaces.
- If an idea is the same as one in "Waiting suggestions", copy that wording exactly, so it counts as a repeat.

Already saved:
{saved}

Waiting suggestions:
{waiting}

Existing categories: {", ".join(categories) or "none yet"}

Reply with ONLY a JSON list, or [] if nothing is worth saving. Example:
[{{"memory": "Likes simple answers", "category": "answer_style"}}]

Messages:
{numbered}
"""
    return _parse_json_list(_ask_llm(prompt))


# Questions like "do you remember...?" are for the AI to answer, not saving requests
QUESTION_START = re.compile(
    r"^\s*(do|did|can|could|would|will|what|when|why|how)\b", re.IGNORECASE)
# Phrases that mean "save this"
REMEMBER = re.compile(
    r"\b(remember|don't forget|do not forget|keep in mind|from now on|for now on|going forward)\b", re.IGNORECASE)


def remember_now(text, force=False):
    """
    Save something right away, because the user asked. Returns what was saved.
    force=True (the /remember command) keeps your own words if the AI finds nothing.
    """
    try:
        items = _ask_ai(text)
    except Exception:
        # No internet, or AI call failed
        items = []
    if not items:
        # From /remember, keep your words. From a normal sentence, save nothing.
        return save_memory(text) if force else None

    lines = []
    for item in items:
        lines.append(save_memory(item["memory"],
                     _clean_category(item.get("category"))))

    return "\n".join(lines)


# Date
def _today():
    # "yyyy-mm-dd": this format also sorts correctly
    return date.today().isoformat()


# Helper to orginize categories
def _clean_category(name):
    """'Answer Style' -> 'answer_style'. Empty -> 'other'."""
    return str(name or "other").lower().strip().replace(" ", "_")


# Helper for inbox/suggestions
def _similarity(a, b):
    """0 to 1: how many words two sentences share. 1 means exactly the same words."""
    words_a = set(re.findall(r"[a-z']+", a.lower()))
    words_b = set(re.findall(r"[a-z']+", b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _threshold(level):
    """How many times an idea must come up before it's shown, after `level` skips."""
    if level < len(ASK_AT):
        return ASK_AT[level]
    # Past the list: keep doubling (64, 128...), so it gets rarer but never "never"
    return ASK_AT[-1] * 2 ** (level - len(ASK_AT) + 1)


# Save memory file
def save_memory(text, category="other"):
    """Save one memory and return a message saying what happened."""
    text = text.strip()
    if not text:
        return "Nothing to save."

    data = _load(MEMORIES_FILE)
    # Don't save the exact same thing twice (ignore upper/lowercase)
    for m in data["memories"]:
        if m["text"].lower() == text.lower():
            return f"Already saved as #{m['id']}."

    memory = {"id": data["next_id"], "text": text,
              "category": category, "added": _today()}
    data["memories"].append(memory)
    data["next_id"] += 1
    _save(MEMORIES_FILE, data)

    return f"Saved #{memory['id']} [{category}] {text}"


# List memory
def list_memories():
    """Everything saved, grouped by category."""
    memories = _load(MEMORIES_FILE)["memories"]
    if not memories:
        return "No memory saved yet."

    # Sort memories into groups
    groups = {}
    for m in memories:
        groups.setdefault(m.get("category", "other"), []).append(m)

    lines = []
    for category in sorted(groups):
        lines.append(category.upper())
        for m in groups[category]:
            lines.append(f"  {m['id']}. {m['text']}")
    return "\n".join(lines)


# Memory prompt for each message
def build_memory_prompt():
    """The memory text added to the AI's system prompt each turn."""
    memories = _load(MEMORIES_FILE)["memories"]
    if not memories:
        return ("Saved memories about the user: none yet.\n"
                "Important: you cannot save anything yourself. If the user tells you how to act in the future (for example 'remember...', 'in the future...', 'always...') and it is NOT in the list above, do not say you will remember it. "
                "Tell them to use /remember to save it.")

    # For now, just the newest ones. A later step picks the ones that fit the question
    newest = memories[-MAX_IN_PROMPT:]
    lines = [f"- ({m.get('category', 'other')}) {m['text']}" for m in newest]
    return ("Saved memories about the user:\n" + "\n".join(lines) +
            "\nUse these quietly when they help the answer. If one conflicts with what the user says now, follow the user. Don't list them unless the user asks.\n"
            "Important: you cannot save anything yourself. If the user tells you how to act in the future (for example 'remember...', 'in the future...', 'always...') and it is NOT in the list above, do not say you will remember it. "
            "Tell them to use /remember to save it.")


# Collecting messages and filling the inbox
def note_message(user_message):
    """Call after each normal message. Every few messages, the AI looks for things to remember."""
    inbox = _load(INBOX_FILE)
    # Saved to the file right away, so closing the chat loses nothing
    inbox["pending_messages"].append(user_message)
    _save(INBOX_FILE, inbox)
    if len(inbox["pending_messages"]) >= LEARN_EVERY:
        _learn()


def _learn():
    """Turn waiting messages into suggestions in the inbox."""
    inbox = _load(INBOX_FILE)
    if not inbox["pending_messages"]:
        return
    try:
        items = _find_suggestions(inbox["pending_messages"])
    except Exception:
        # no internet or the AI failed: keep the messages and try again later
        return

    memories = _load(MEMORIES_FILE)["memories"]
    for item in items:
        text = item["memory"]
        # Already a memory: nothing to suggest
        if any(_similarity(text, m["text"]) >= 0.6 for m in memories):
            continue
        # Already waiting: count the repeat instead of adding it twice
        same = next((s for s in inbox["suggestions"] if _similarity(
            text, s["memory"]) >= 0.6), None)
        if same:
            same["times_seen"] = same.get("times_seen", 1) + 1
        else:
            inbox["suggestions"].append(
                {**item, "times_seen": 1, "level": 0})

    inbox["pending_messages"] = []
    _save(INBOX_FILE, inbox)


# Review - Accept - Skip
def _ask_which(count):
    """Ask which suggestions to keep. Keeps asking until the answer is clear."""
    while True:
        answer = input(
            "Save which? Enter = all, n = none, or numbers like 2,4: ").strip().lower()
        if answer in ("", "all", "y", "yes"):
            return set(range(1, count + 1))
        if answer in ("n", "no", "none"):
            return set()
        numbers = {int(x) for x in re.findall(r"\d+", answer)}
        # Only digits, commas and spaces count, so "skip 2" isn't read as "save 2"
        if numbers and re.fullmatch(r"[\d,\s]+", answer) and all(1 <= x <= count for x in numbers):
            return numbers
        print(
            f"Please press Enter, type n, or type numbers from 1 to {count} (like 2,4).")


def review():
    """Show waiting suggestions as one list and save the ones you pick."""

    # look at the newest messages first, even if there are fewer than 6
    _learn()
    inbox = _load(INBOX_FILE)
    # Only show suggestions that have come up enough times
    due = [s for s in inbox["suggestions"]
           if s.get("times_seen", 1) >= _threshold(s.get("level", 0))]
    if not due:
        return "No new memory suggestions."

    print("\nI noticed some things that may be worth remembering:")
    for n, s in enumerate(due, start=1):
        print(f"  {n}. [{_clean_category(s.get('category'))}] {s['memory']}")

    chosen = _ask_which(len(due))
    lines = []
    for n, s in enumerate(due, start=1):
        if n in chosen:
            lines.append(save_memory(
                s["memory"], _clean_category(s.get("category"))))
            inbox["suggestions"].remove(s)   # saved, so it leaves the inbox
        else:
            # skipped: wait for more repeats
            s["level"] = s.get("level", 0) + 1
    skipped = len(due) - len(chosen)
    if skipped:
        lines.append(
            f"Skipped {skipped}. They'll come back if they keep coming up.")

    _save(INBOX_FILE, inbox)
    return "\n".join(lines)


# Commands
def handle_message(user_message):
    """
    Call before the AI answers. Saves "remember ..." requests right away.
    Returns a notice to print, or None for a normal message.
    """

    text = user_message.strip()
    if text.endswith("?") or QUESTION_START.match(text):
        return None
    if REMEMBER.search(text):
        return remember_now(text)

    return None


def handle_command(text):
    """
    Runs a memory command: /memories, /review, or /remember <text>.
    Returns the text to print, or None if it isn't a memory command.
    """
    if text == "/memories":
        return list_memories()
    if text == "/review":
        return review()
    if text.startswith("/remember "):
        return remember_now(text[len("/remember "):], force=True)
    return None
