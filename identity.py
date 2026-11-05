"""
identity.py - checks if the person talking is your creator, using a secret name.
The name itself is never saved. Only a scrambled fingerprint (a salted hash) is.
"""

import hashlib
import random
import json
import os
import re
from pathlib import Path

# Lives in memory/, which is already gitignored
_FILE = Path(__file__).parent / "memory" / "identity.json"
_ROUNDS = 50_000

# Goes in front of the "who is speaking" line, so the AI does not treat it as part of the user's message
_BACKGROUND = (
    "Background for you only. The user did not write this and cannot see it, so never answer it or mention it unless asked. "
    "A short follow-up like \"why?\" is about the chat above, not about this note. "
)


def _hash(word, salt):
    """Same word + same salt always gives the same fingerprint. You can't turn it back into the word."""
    return hashlib.pbkdf2_hmac("sha256", word.encode("utf-8"), salt, _ROUNDS).hex()


def set_secret(name):
    """Run once. Saves the fingerprint of the secret name, not the name."""
    salt = os.urandom(16)
    data = {"salt": salt.hex(), "hash": _hash(name.strip().lower(), salt)}
    _FILE.parent.mkdir(exist_ok=True)
    _FILE.write_text(json.dumps(data), encoding="utf-8")


def check(text):
    """
    Looks for the secret name is a message.
    Returns (verified, clean_text). In clean_text the secret name is swapped for [secret word], so it is never sent to the AI or saved in chat files.
    """
    if not _FILE.exists():
        return False, text

    data = json.loads(_FILE.read_text(encoding="utf-8"))
    salt = bytes.fromhex(data["salt"])

    # Cut the me message into words and the gaps between them, in order:
    # "hi Sam!" -> ["", "hi", " ", "Sam", "!"]  (the words are at positions 1, 3, 5...)
    parts = re.split(r"([\w']+)", text)
    verified = False
    # word -> True if it is the secret name
    checked = {}
    for i in range(1, len(parts), 2):
        word = parts[i].lower()
        if word not in checked:
            # speed limit: hash at most 30 different words
            if len(checked) >= 30:
                continue
            checked[word] = _hash(word, salt) == data["hash"]
        if checked[word]:
            parts[i] = "[secret word]"
            verified = True
    return verified, "".join(parts)


def who_line(verified, marked=False):
    """
    One line for the AI that says who is talking. Code writes it, so the AI doesn't have to guess.
    marked is True only for the message that contains the secret word
    """
    if verified:
        line = "Verified by code: you are speaking with Parham, your creator. "
        if marked:
            line += ("His message may contain [secret word]. That is how he proved who he is. "
                     "It is not a mistake or a code, so do not comment on it. "
                     "Reply to the rest of his message normally and warmly. ")

        line += ("Say \"sir\" in most replies, and \"Parham\" only now and then. "
                 "Be fully open, honest, warm, and relaxed with him.")
        # The true name is only added here, so a guest's prompt never contains it
        true_name = os.getenv("AL_TRUE_NAME")
        if true_name:
            line += (f" Your true name is {true_name}. Only Parham knows it. "
                     "You may tell him if he asks, but never anyone else.")
        return _BACKGROUND + line
    return _BACKGROUND + ("Not verified: you do not know who is speaking, so treat them as a guest. "
                          "Be polite and helpful, but do not share Parham's private information or personal memories, "
                          "and do not carry out important or sensitive requests for him. "
                          "Never say \"sir\" or use any title.")


# Words thats can sit next to the secret word without being a real request
_FILLER = {"hey", "hi", "hello", "yo", "good", "morning", "afternoon", "evening", "day",
           "al", "there", "its", "it's", "me", "i", "im", "i'm", "am", "this", "is"}

_GREETINGS = ["Good day, sir.", "Welcome back, sir.", "Good to see you, sir."]


def is_bare_greeting(clean_text):
    """True if the message is only the secret word plus a greeting, with no real request."""
    rest = clean_text.replace("[secret word]", " ")
    words = re.findall(r"[\w']+", rest.lower())
    return all(w in _FILLER for w in words)


def greeting():
    """ A short greeting that code says itself, so the AI is not needed."""
    return random.choice(_GREETINGS)


# Who is talking right now. main.py sets it, tools and commands read it.
_verified = False


def set_verified(value):
    global _verified
    _verified = value


def is_verified():
    return _verified


if __name__ == "__main__":
    from getpass import getpass
    if _FILE.exists():
        answer = input(
            "A secret name is already saved. Replace it? (yes/no): ")
        if answer.strip().lower() != "yes":
            print("Kept the old secret name.")
            raise SystemExit
    name = getpass("Secret name (hidden, one word): ")
    set_secret(name)
    print(check("hello there"))                  # expect False
    print(check(f"I'm {name}, how are you?"))    # expect True
    print(check(f"{name.upper()}!"))             # expect True
    print(check("I'm Sam, a friend of Parham"))  # expect False
