"""
chat_mode.py - decides if a message is just chatting or a tast.
"""
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Test
from langchain_core.messages import AIMessage

from model import llm, ask_llm, MODEL_NAME, MODEL_PROVIDER
from prompts import CHAT_PROMPT


# Words that show the message asks for Al's own view
_OPINION = re.compile(
    r"\b(you think|your opinion|your take|your thoughts|do you agree|do you like|how do you feel"
    r"|how are you|how have you been|how's your day|how is your day|how's it going|what's up"
    r"|about me|who am i|who i am|remember me|who are you)\b",
    re.IGNORECASE,
)


def is_casual(text, last_reply="", after_task=False):
    """
    True if the message is just chatting. Flase if it needs facts, research, code, or a task.
    last_reply is Al's previous answer. It is only used to understand a short follow-up like "why?".
    after_task is True if Al's previous answer came from the research (task) path.
    """

    # A question right after a research-style answer is most likely a follow-up to it
    # Unless it asks for Al's own opinion
    if (after_task and len(text.split()) <= 12 and text.strip().endswith("?") and not _OPINION.search(text)):
        return False

    context = f"\nAl's last reply (context only): {last_reply[:300]}\n" if last_reply else ""

    question = f"""
    Read the message below and decide what kind it is.
    Replay with one word only:
    - CHAT: greetings, thanks, small talk, jokes, feelings, asking Al for his opinion or if he agrees, ideas or plans being talked over, asking what Al knows about the user in general (not what was said in a past chat), or talk about Al himself, his abilities, or the project they are building together.
    - TASK: asks Al to look something up or produce something: facts, research, news, code, a written plan or list, searching or saving information, or what was said in earlier chats.
    An opinion question is CHAT, even when the topic is technical.
    If the message asks for facts, current information, or something to be written, or you are not sure, reply TASK.
    A short message that asks what Al himself thinks or feels, or how he is doing, is CHAT, even right after facts or research.
    A short follow-up that asks what Al himself thinks or feels is CHAT, even right after facts or research.
    {context}

    Message: {text}
    """

    try:
        answer = ask_llm(question)
    except Exception:
        # No internet or the AI failed: use the normal path
        return False

    return answer.strip().upper().startswith("CHAT")


# The casual-chat prompt (same shape as the agent's prompt, but no JSON and no tools)
chat_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", CHAT_PROMPT),
        ("system", "Today's date is {today}."),
        ("system", "{personal_memory}"),
        ("placeholder", "{chat_history}"),
        ("human", "{query}")
    ]
).partial(model_name=MODEL_NAME, model_provider=MODEL_PROVIDER)

# prompt -> model -> plain text
chat_chain = chat_prompt | llm | StrOutputParser()


# Make Al to not end every reply with question
def question_rule(chat_history):
    """Looks at Al's last two replies. If either one ended with a question, tells the AI not to ask one now."""
    replies = [m.content for m in chat_history if m.type == "ai"][-2:]
    if any(r.strip().endswith("?") for r in replies):
        return "Do not end this reply with a question. End it with a statement."
    return ""


def casual_reply(query, chat_history, personal_memory, today):
    """Reply as plain, natural Al. No JSON, no tools."""
    rule = question_rule(chat_history)
    return chat_chain.invoke(
        {
            "query": query,
            "chat_history": chat_history,
            "personal_memory": (personal_memory + "\n" + rule).strip(),
            "today": today
        }
    )


# TEST
if __name__ == "__main__":
    tests = [
        ("I'm going to work on you today and add a database to you", True),
        ("do you prefer tea or coffee?", True),
        ("what do you think about learning to cook?", True),
        ("find the latest news on the Mars mission", False),
        ("write a function that reverses a string", False),
        ("what did I ask about Mars before?", False),
        ("what's the current price of a Raspberry Pi?", False),
    ]
    for text, expected in tests:
        result = is_casual(text)
        print("ok   " if result == expected else "WRONG",
              "CHAT" if result else "TASK", "<-", text)

    # Opinion follow-ups right after research should be casual
    print(is_casual("what do you think about that?",
          "NASA's CHAPEA crew returned after 378 days.", True))        # want True
    print(is_casual("do you agree with them?",
          "Naturalization needs about five years of residence.", True))     # want True
    # Fact follow-ups right after research should still be tasks
    print(is_casual("do they check the language level?",
          "Naturalization needs about five years of residence.", True))  # want False
    print(is_casual("how long does that take?",
          "Naturalization needs about five years of residence.", True))    # want False
    # want False
    print(is_casual("why?", "The ESCAPADE mission will fly by Earth on November 7.", True))
    # want True
    print(is_casual("thanks!", "NASA's CHAPEA crew returned after 378 days.", True))
    # want True
    print(is_casual("how are you?", "Japan launched a mission to Phobos.", True))
    print(is_casual("how's your day going?",
          "Japan launched a mission to Phobos.", True))       # want True
    print(is_casual("how long does that take?",
          "Japan launched a mission to Phobos.", True))    # want False
    print(is_casual("what do you know about me?",
          "Photosynthesis takes seconds to minutes.", True))   # want True
    print(is_casual("do you remember who I am?",
          "Photosynthesis takes seconds to minutes.", True))    # want True
    print(is_casual("what did I ask you before?",
          "Photosynthesis takes seconds to minutes.", True))   # want False
