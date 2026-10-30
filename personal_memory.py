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


# The memories sent with the last answer (For /why)
_last_used = []

MEMORY_FOLDER = Path("memory")

# Active memories
MEMORIES_FILE = MEMORY_FOLDER / "memories.json"
MAX_IN_PROMPT = 10

# Inbox suggestions
INBOX_FILE = MEMORY_FOLDER / "inbox.json"
LEARN_EVERY = 6

# Archive memories
ARCHIVE_FILE = MEMORY_FOLDER / "archive.json"
UNUSED_DAYS = 90
SUGGESTION_DAYS = 30

# Pin (memories the AI marks as permanent get pinned automatically)
AUTO_PIN = True

# Undo changes
UNDO_FILE = MEMORY_FOLDER / "undo.json"
UNDO_LIMIT = 20

# Most "every answer" memory
MAX_ALWAYS = 5

# How many times an idea must come up before it's shown, after 0, 1, 2... skips
ASK_AT = [1, 3, 8, 16, 32]


NO_SAVING_RULE = ("Important: you cannot save anything yourself. If the user tells you how to act "
                  "in the future (for example 'remember...', 'in the future...', 'always...') and "
                  "it is NOT in the saved memories, do not say you will remember it. "
                  "Tell them to use /remember to save it.")


# What each file looks like before anything is saved.
# More files (inbox, archive) get added here in later steps.
DEFAULTS = {
    MEMORIES_FILE: {"next_id": 1, "active_days": 0, "last_active": "", "memories": []},
    INBOX_FILE: {"pending_messages": [], "suggestions": []},
    ARCHIVE_FILE: {"memories": []},
    UNDO_FILE: {"changes": []}
}

# The files /undo puts back, by name
UNDO_FILES = {"memories": MEMORIES_FILE,
              "inbox": INBOX_FILE, "archive": ARCHIVE_FILE}


# Read memory file
def _load(path):
    if not path.exists():
        # A copy, so changing what we return never changes DEFAULTS itself
        return copy.deepcopy(DEFAULTS[path])
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Snapshot memories and archive before changes
def _snapshot(description):
    """Save a copy of all files before a change, so /undo can put them back."""
    history = _load(UNDO_FILE)
    files = {name: _load(path) for name, path in UNDO_FILES.items()}
    history["changes"].append({"description": description, "files": files})

    # Keep only the newest changes
    history["changes"] = history["changes"][-UNDO_LIMIT:]
    _save(UNDO_FILE, history)


# Write memory file
def _save(path, data):
    MEMORY_FOLDER.mkdir(exist_ok=True)

    # Write a temp file first, then swap it in.
    # Write to a temp file first so that if the program crashes while writing, real memories.json stays whole
    temp = path.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    temp.replace(path)


# Clean up archive list
def _clean_up():
    """Archive memories unused for a long time, and drop old suggestions. Returns notices."""
    data, archive, inbox = _load(MEMORIES_FILE), _load(
        ARCHIVE_FILE), _load(INBOX_FILE)
    day = data.get("active_days", 0)
    notices = []

    # Loop over a copy (list(...)), because we remove items from the real list
    for m in list(data["memories"]):
        # setdefault gives them today as a fresh start, saved once, so they age normally after.
        m.setdefault("last_used", day)

        if m.get("expires") and m["expires"] < _today():
            reason = f"its date {m['expires']} passed"

        elif not m.get("pinned") and day - m["last_used"] >= UNUSED_DAYS:
            reason = f"not used in {UNUSED_DAYS} active days"

        # still active, nothing to do
        else:
            continue

        data["memories"].remove(m)
        archive["memories"].append(
            {**m, "archived": _today(), "reason": reason})
        notices.append(f"Moved to archive: {m['text']} ({reason}). "
                       f"/restore {m['id']} brings it back.")

    # Same fresh start for old suggestions, then drop ones that never came up again
    for s in inbox["suggestions"]:
        s.setdefault("last_seen_day", day)
    inbox["suggestions"] = [s for s in inbox["suggestions"]
                            if day - s["last_seen_day"] < SUGGESTION_DAYS]

    if notices:
        _snapshot("the automatic clean_up")
    _save(MEMORIES_FILE, data)
    _save(ARCHIVE_FILE, archive)
    _save(INBOX_FILE, inbox)
    return "\n".join(notices)


def list_archive():
    """Everything in the archive, with when and why it was archived."""
    memories = _load(ARCHIVE_FILE)["memories"]
    if not memories:
        return "The archive is empty"

    lines = ["ARCHIVE"]
    for m in memories:
        lines.append(f" {m['id']}. [{m.get('category', 'other')}] {m['text']} "
                     f"(archived {m['archived']}: {m['reason']})")
    return "\n".join(lines)


# Restore from archive
def restore(memory_id):
    """Move a memory from the archive back to active memories."""
    data, archive = _load(MEMORIES_FILE), _load(ARCHIVE_FILE)
    m = next((m for m in archive["memories"] if m["id"] == memory_id), None)

    if not m:
        return f"There's no archived memory #{memory_id}."

    archive["memories"].remove(m)

    # Drop the archive fields, and give it a fresh start
    # {k: v for k, v in m.items() if ...} is a dict comprehension. It copies every key except the ones we don’t want.
    m = {k: v for k, v in m.items() if k not in ("archived", "reason")}
    m["last_used"] = data.get("active_days", 0)

    # Its old date already passed, so keep it without one
    # (otherwise the next start would archive it again right away)
    if m.get("expires") and m["expires"] < _today():
        m["expires"] = None

    data["memories"].append(m)

    _snapshot(f"restoring #{memory_id}")
    _save(MEMORIES_FILE, data)
    _save(ARCHIVE_FILE, archive)

    return f"Restored #{memory_id}: {m['text']}"


# AI assistant to orginize the memory
def setup(ask_llm):
    """Call once when the assistant starts. ask_llm: prompt text in, reply text out."""
    global _ask_llm
    _ask_llm = ask_llm

    data = _load(MEMORIES_FILE)
    # Count only the days that AI was active
    if data.get("last_active") != _today():
        data["active_days"] = data.get("active_days", 0) + 1
        data["last_active"] = _today()
        _save(MEMORIES_FILE, data)
    return _clean_up()


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
You are the long-term memory of a personal AI assistant. Today is {_today()}.
The user asked you to remember something. Turn their message into memories.

Rules:
- One idea per memory. Split "I like simple answers with examples" into "Likes simple answers" and "Likes examples in explanations".
- memory: one short, plain sentence about the user, like "Studies computer science".
- category: reuse an existing category if one fits. Otherwise make a short lowercase one (1 or 2 words, with _ instead of spaces).
- permanent: true if it will probably stay true for years (their name, degree, lasting preferences), else false.
- Never save passwords, keys, or ID numbers.
- expires: "YYYY-MM-DD" if it is only true until a date (a deadline, this quarter, this semester), else null. If no exact day is given, use the last day of that period.

Existing categories: {", ".join(categories) or "none yet"}

Reply with ONLY a JSON list, like:
[{{"memory": "Likes simple answers", "category": "answer_style", "expires": null, "permanent": true}},
 {{"memory": "Capstone is due in December", "category": "projects", "expires": "2026-12-31", "permanent": false}}]

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
You are the long-term memory of a personal AI assistant. Today is {_today()}.
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
- permanent: true if it will probably stay true for years (their name, degree, lasting preferences), else false.
- expires: "YYYY-MM-DD" if it is only true until a date (a deadline, this quarter, this semester), else null. If no exact day is given, use the last day of that period.
- If an idea is the same as one in "Waiting suggestions", copy that wording exactly, so it counts as a repeat.

Already saved:
{saved}

Waiting suggestions:
{waiting}

Existing categories: {", ".join(categories) or "none yet"}

Reply with ONLY a JSON list, or [] if nothing is worth saving. Example:
[{{"memory": "Likes simple answers", "category": "answer_style", "expires": null, "permanent": true}},
 {{"memory": "Capstone is due in December", "category": "projects", "expires": "2026-12-31", "permanent": false}}]

Messages:
{numbered}
"""
    return _parse_json_list(_ask_llm(prompt))


# Questions like "do you remember...?" are for the AI to answer, not saving requests
QUESTION_START = re.compile(
    r"^\s*(do|did|can|could|would|will|what|when|why|how)\b", re.IGNORECASE)

# "Save this" phrases that count only at the START of a message
# (Ex: "I can't remember the formula" should not match)
REMEMBER_START = re.compile(
    r"^\s*(please\s+)?(remember|don't forget|do not forget|keep in mind)\b", re.IGNORECASE)
# "Save this" phrases that are clear anywhere in the message
REMEMBER_ANYWHERE = re.compile(
    r"\b(from now on|for now on|going forward)\b", re.IGNORECASE)


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
    fallback = False

    if not items:
        if not force:
            return None
        # The AI found nothing, but /remember means save it anyway, so save in user's own words
        items = [{"memory": text}]
        fallback = True
    _snapshot("the last memory save")

    lines = [_save_item(item) for item in items]
    if fallback:
        # Saved, but tell the user it wasn't sorted, so it isn't a silent surprise
        lines.append("Note: I couldn't sort this properly, so I saved your exact words "
                     "under 'other'. To redo it, use /undo and try /remember again if you like.")
    return "\n".join(lines)


# Date
def _today():
    # "yyyy-mm-dd": this format also sorts correctly
    return date.today().isoformat()


# Helper to orginize categories
def _clean_category(name):
    """'Answer Style' -> 'answer_style'. Empty -> 'other'."""
    return str(name or "other").lower().strip().replace(" ", "_")


# Helper to orginize by date
def _clean_date(value):
    """Turn the AI's date into 'YYYY-MM-DD', or None if it isn't a valid date."""
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        # null, "December", "soon"... anything that isn't a real date
        return None


# Helper for inbox/suggestions
def _similarity(a, b):
    """0 to 1: how many words two sentences share. 1 means exactly the same words."""
    words_a = set(re.findall(r"[a-z']+", a.lower()))
    words_b = set(re.findall(r"[a-z']+", b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


# Common words that say nothing about a topic
STOPWORDS = {
    "the", "and", "for", "you", "your", "that", "this", "with", "have", "from",
    "like", "likes", "user", "about", "what", "when", "which", "would", "should",
    "could", "can", "are", "was", "will", "just", "want", "wants", "some", "more",
    "most", "into", "also", "very", "them", "they", "their", "there", "than",
    "then", "does", "did", "how", "why", "who", "its",
}


def _stem(word):
    """Rough word shortening, so 'studies', 'study' and 'studying' all become 'study'."""
    for ending in ("ies", "ing", "ed", "es", "s"):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            # 'studies' -> 'stud' + 'y'; everything else just loses its ending
            word = word[:-len(ending)] + ("y" if ending == "ies" else "")
            break

    # 'code' and 'cod(ing)' both end up as 'cod'
    return word.rstrip("e")


def _words(text):
    """The meaningful words in a text, shortened. 'Studies computer science' -> {'study', 'computer', 'scienc'}"""
    words = re.findall(r"[a-z']+", text.lower())
    return {_stem(w) for w in words if len(w) >= 3 and w not in STOPWORDS}


# Helper for memory save
def _save_item(item):
    """Save one memory from the AI, with its category, end date, and pin."""
    return save_memory(
        item["memory"],
        _clean_category(item.get("category")),
        _clean_date(item.get("expires")),
        AUTO_PIN and item.get("permanent") is True
    )


def _threshold(level):
    """How many times an idea must come up before it's shown, after `level` skips."""
    if level < len(ASK_AT):
        return ASK_AT[level]
    # Past the list: keep doubling (64, 128...), so it gets rarer but never "never"
    return ASK_AT[-1] * 2 ** (level - len(ASK_AT) + 1)


# Save memory file
def save_memory(text, category="other", expires=None, pinned=False):
    """Save one memory and return a message saying what happened."""
    text = text.strip()
    if not text:
        return "Nothing to save."

    # A date that already passed means it isn't true anymore
    if expires and expires < _today():
        return f"Not saved: {text} (its date {expires} alreadyy passed)."

    data = _load(MEMORIES_FILE)
    # Don't save the exact same thing twice (ignore upper/lowercase)
    for m in data["memories"]:
        if m["text"].lower() == text.lower():
            return f"Already saved as #{m['id']}."

    memory = {"id": data["next_id"], "text": text,
              "category": category, "added": _today(),
              "last_used": data.get("active_day", 0),
              "expires": expires,
              "pinned": pinned and not expires}
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
        for m in sorted(groups[category], key=lambda m: m["id"]):
            tags = []
            if m.get("pinned"):
                tags.append("pinned")
            if m.get("expires"):
                tags.append(f"until {m['expires']}")

            extra = f" ({', '.join(tags)})" if tags else ""
            lines.append(f"  {m['id']}. {m['text']}{extra}")
    return "\n".join(lines)


# Pick the memories
def _pick(user_message, memories):
    """Choose the memories that fit this message, best first, each with the reason it was picked."""
    message_words = _words(user_message)
    always, matched = [], []

    for m in memories:
        if m.get("scope") == "always":
            always.append((m, "applies to every answer"))
            continue

        # A memory can match through its text, its keywords, or its category name
        memory_words = (_words(m["text"])
                        | _words(" ".join(m.get("keywords", [])))
                        | _words(m.get("category", "other").replace("_", " ")))

        shared = message_words & memory_words

        if shared:
            matched.append((len(shared), m, "matched: " +
                           ", ".join(sorted(shared))))

    # More shared words first; on a tie, the newer memory (higher id) first
    matched.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
    always = always[-MAX_ALWAYS:]
    room = MAX_IN_PROMPT - len(always)

    return always + [(m, reason) for _, m, reason in matched[:room]]


# Memory prompt for each message
def build_memory_prompt(user_message):
    """The memory text added to the AI's system prompt each turn."""
    # Lets this function change the _last_used at the top of the file
    global _last_used
    data = _load(MEMORIES_FILE)
    _last_used = _pick(user_message, data["memories"])
    if not _last_used:
        return "Saved memories about the user: none fit this message.\n" + NO_SAVING_RULE

    # Being sent counts as being used, so it won't age into the archive.
    # These are the same dicts as in data, so changing them changes data too.
    for m, _ in _last_used:
        m["last_used"] = data.get("active_days", 0)
    _save(MEMORIES_FILE, data)

    lines = [
        f"- ({m.get('category', 'other')}) {m['text']}" for m, _ in _last_used]
    return ("Saved memories about the user:\n" + "\n".join(lines) +
            "\nUse these quietly when they help the answer. If one conflicts with what the user says now, follow the user. Don't list them unless the user asks.\n"
            + NO_SAVING_RULE)


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

    day = _load(MEMORIES_FILE).get("active_days", 0)

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
            same["last_seen_day"] = day
        else:
            inbox["suggestions"].append(
                {**item, "times_seen": 1, "level": 0, "last_seen_day": day})

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
        until = f"  (until {s['expires']})" if _clean_date(
            s.get("expires")) else ""
        print(
            f"  {n}. [{_clean_category(s.get('category'))}] {s['memory']}{until}")

    chosen = _ask_which(len(due))
    _snapshot("the last review")
    lines = []
    for n, s in enumerate(due, start=1):
        if n in chosen:
            lines.append(_save_item(s))
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


# Pin - Unpin - Forget
def set_pin(memory_id, pinned):
    """Pin a memory so it's never archived for being unused, or upin it."""
    data = _load(MEMORIES_FILE)
    m = next((m for m in data["memories"] if m["id"] == memory_id), None)

    if not m:
        return f"There's no active memory #{memory_id}."

    if pinned and m.get("expires"):
        return f"Sorry, #{memory_id} ends on {m['expires']}. Remove the deadline to use /pin."

    m["pinned"] = pinned

    _snapshot(f"{'pinning' if pinned else 'unpinning'} #{memory_id}")
    _save(MEMORIES_FILE, data)
    return f"{'Pinned' if pinned else 'Unpinned'} #{memory_id}: {m['text']}"


def forget(memory_id):
    """Delete a memory for good, whether it's active or archived."""
    data, archive = _load(MEMORIES_FILE), _load(ARCHIVE_FILE)

    # Check active memory first, then the archive
    for path, collection in ((MEMORIES_FILE, data), (ARCHIVE_FILE, archive)):
        m = next((m for m in collection["memories"]
                 if m["id"] == memory_id), None)
        if m:
            # Pinned memories can't be deleted till it's unpinned
            if m.get("pinned"):
                return f"{memory_id} is pinned. Use /unpin {memory_id} first if you want to forget {memory_id}."

            _snapshot(f"forgetting #{memory_id}")
            collection["memories"].remove(m)
            _save(path, collection)
            return f"Forgot #{memory_id}: {m['text']} (/undo brings it back)"
    return f"There's no memory #{memory_id}."


# Undo
def undo():
    """Put the memory files back the way they were before the last change."""
    history = _load(UNDO_FILE)

    if not history["changes"]:
        return "Nothing to undo."

    # The newest change
    change = history["changes"].pop()
    for name, path in UNDO_FILES.items():
        _save(path, change["files"][name])

    _save(UNDO_FILE, history)
    return f"Undid {change['description']}. ({len(history['changes'])} more to undo)"


# Why
def why():
    """Show which memories were given to the AI for the last answer."""
    if not _last_used:
        return "No saved memories were used for the last answer."

    lines = ["Memories given to the AI for the last answer:"]
    for m, reason in _last_used:
        lines.append(
            f" {m['id']}. [{m.get('category', 'other')}] {m['text']} ({reason})")
    return '\n'.join(lines)


# Fix the date manually
def set_until(memory_id, value):
    """Change a memory's end date, or remove it with 'never'."""
    data = _load(MEMORIES_FILE)
    m = next((m for m in data["memories"] if m["id"] == memory_id), None)

    if not m:
        return f"There's no active memory #{memory_id}."

    if value.lower() == "never":
        m["expires"] = None

    else:
        new_date = _clean_date(value)
        if not new_date:
            return f"Use: /until {memory_id} 2026-12-31   or   /until {memory_id} never"
        m["expires"] = new_date
        # Memory with an end date can't be permanent
        m["pinned"] = False

    _snapshot(f"changing the date of #{memory_id}")
    _save(MEMORIES_FILE, data)
    return f"#{memory_id} now lasts {'until ' + m['expires'] if m['expires'] else 'with no end date'}."

# Commands


def handle_message(user_message):
    """
    Call before the AI answers. Saves "remember ..." requests right away.
    Returns a notice to print, or None for a normal message.
    """

    text = user_message.strip()
    if text.endswith("?") or QUESTION_START.match(text):
        return None
    if REMEMBER_START.search(text) or REMEMBER_ANYWHERE.search(text):
        return remember_now(text)

    return None


def handle_command(text):
    """
    Runs a memory command: /memories, /review, /archive, /restore, /until, /remember, /pin, /unpin, /forget, /undo, or /why  <text>.
    Returns the text to print, or None if it isn't a memory command.
    """
    parts = text.split()
    command = parts[0]
    # The number after commands like /pin 4
    # None if there isn't a valid one
    number = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

    if text == "/memories":
        return list_memories()
    if text == "/review":
        return review()
    if text == "/archive":
        return list_archive()
    if text.startswith("/restore "):
        number = text[len("/restore "):].strip()
        return restore(int(number)) if number.isdigit() else "Use: /restore <number>"
    if text.startswith("/until "):
        parts = text.split()
        if len(parts) == 3 and parts[1].isdigit():
            return set_until(int(parts[1]), parts[2])
        return "Use: /until <number> <YYYY-MM-DD or never>"
    if text.startswith("/remember "):
        return remember_now(text[len("/remember "):], force=True)
    if command in ("/pin", "/unpin", "/forget"):
        if number is None:
            return f"Use:{command} <number>"
        if command == "/forget":
            return forget(number)
        return set_pin(number, command == "/pin")
    if text == "/undo":
        return undo()
    if text == "/why":
        return why()
    return None
