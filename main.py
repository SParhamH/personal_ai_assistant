from dotenv import load_dotenv
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from datetime import datetime

from prompts import SYSTEM_PROMPT
from model import llm, ask_llm, MODEL_NAME, MODEL_PROVIDER
from chat_mode import is_casual, casual_reply
import identity
from sources import sources_from
from detail import expand, results_text, is_failed
from tools import tools
from storage import (
    create_filename,
    save_to_json,
    save_to_txt,
    list_sessions,
    load_json,
)
import personal_memory as pm
import traceback
import re

load_dotenv()


# Set to True to see the agent's thought process and the raw AI reply
DEBUG = False


# Specify all of the fields as output from LLM
class Response(BaseModel):
    topic: str
    summary: str
    details: str = ""
    sources: list[str]
    tools_used: list[str]


# Set up the parser (the model itself lives in model.py)
parser = PydanticOutputParser(pydantic_object=Response)


# Prompt template
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("system",
         "Today's date is {today}. Use it to decide whether dates you read about are in the past or the future."),
        ("placeholder", "{chat_history}"),
        ("system", "{personal_memory}"),
        ("human", "{query}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
).partial(format_instructions=parser.get_format_instructions(),
          model_name=MODEL_NAME,
          model_provider=MODEL_PROVIDER)

# Tools that agent can call
agent = create_tool_calling_agent(
    llm=llm,
    prompt=prompt,
    tools=tools
)

# Agent excutor
# verbose is for asking agent to show its work
# return_intermediate_steps return the tools the agent really called, so we can check its claims
agent_executor = AgentExecutor(
    agent=agent, tools=tools, verbose=DEBUG, max_iterations=5, return_intermediate_steps=True)


# Chat history and searching old chats
# AI has no memory, so we resend this every turn
chat_history = []

# The last saved chat is kept aside. It is only given to the AI once Parham is verified.
old_history = []

# Load the most recent saved chat so the assistant can look back
past_chats = list_sessions()
if past_chats:
    old_chat = load_json(past_chats[0])

    # Check the last 20 messages only
    # Add each message once, as the right type.
    for m in old_chat["messages"][-20:]:
        if m["role"] == "user":
            old_history.append(HumanMessage(content=m["content"]))
        else:
            old_history.append(AIMessage(content=m["content"]))


# This chat's record, rewritten after every answer
filename = create_filename("chat")
session = {"started": datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"), "messages": []}


def save_session():
    """Rewrites this chat's files with everything said so far."""
    transcript = "\n\n".join(
        f"{m['role'].title()}: {m['content']}" for m in session["messages"]
    )
    save_to_txt(transcript, filename)
    save_to_json(session, filename)


# Helper
def parse_response(text):
    """Turn the AI's reply into a Response. Returns None if it isn't valid JSON."""
    try:
        return parser.parse(text)
    except Exception:
        # The AI sometimes writes text before the JSON, so try just the {...} part
        start, end = text.find("{"), text.rfind("}")
        try:
            return parser.parse(text[start:end + 1])
        except Exception:
            return None


# Old summery: the rest of the answer that is not in the summary (steps, explanation, examples). Keep every explanation. Only write "No more details." if the summary already covers everything.
def rewrite_as_json(text):
    """The AI skipped the JSON format, so ask it once to rewrite its own answer."""
    prompt = f"""Rewrite the answer below as JSON. Change only the structure. Do not add new facts.
- topic: a short topic name.
- summary: a short answer to the question, in 1 or 2 sentences, taken from the answer below.
- details: everything else (steps, explanation, examples). If there is nothing else, write "No more details."
- sources: source names that appear in the answer, otherwise ["No external sources used"].
- tools_used: []

{parser.get_format_instructions()}

Answer:
{text}"""
    try:
        return parse_response(ask_llm(prompt))
    except Exception:
        # No internet or the AI failed: show the raw answer instead
        return None


# Helper to keep the code if the answer needs rewriting
def put_code_back(summary, source):
    """If the full text has code blocks but the short answer lost them, put them back in front."""
    if "```" in summary:
        return summary
    blocks = re.findall(r"```.*?```", source, flags=re.DOTALL)
    return "\n".join(blocks + [summary])


def has_more(details):
    """True if the full answer says more than the short one."""
    return bool(details) and details.strip(" .").lower() != "no more details"


EXIT_WORDS = ["goodbye", "bye", "exit", "quit"]


# Messages that show the full answer from the last reply
MORE_WORDS = ["tell me more", "more", "more details"]


# The full answer from the last reply, shown on "tell me more"
last_details = ""


# True if Al's last answer came from the research (task) path. Questions after it are follow-ups.
last_was_task = False


# Sources found by the last search tools. "/sources" prints them.
last_sources = []


# What the last research turn found. "tell me more" uses these.
last_question = ""
last_short = ""
last_results = ""


def memory_for(query):
    """Says who is talking. Parham's memories are only added when he is verified."""
    if identity.is_verified():
        marked = "[secret word]" in query
        return identity.who_line(True, marked) + "\n" + pm.build_memory_prompt(query)
    return identity.who_line(False)


# Give the memory system a way to talk to the AI
# Count today as an active day, archive old memories, and get any notices
memory_notices = pm.setup(ask_llm)

# Chat structure
print("\nAssistant: Good day.")
print("(Type 'goodbye' to end, /sources for sources, or /help for memory commands.)")

if memory_notices:
    print(f"[Memory] {memory_notices}")

try:
    while True:
        query = input("\nYou: ").strip()

        # Empty input
        if not query:
            continue

        # Look for the secret name. The cleaned message hides it from the AI and the chat files.
        found, query = identity.check(query)
        if found and not identity.is_verified():
            identity.set_verified(True)
            # Put the old chat in front of this chat
            chat_history[:0] = old_history
            print("[Identity] Recognized. Personal mode is on.")

        # Only the secret word and a greeting
        if found and identity.is_bare_greeting(query):
            print(f"\nAssistant: {identity.greeting()}")
            continue

        # "tell me more" prints the saved full answer, with no new AI call
        if query.lower().strip(" !.?") in MORE_WORDS:
            fuller = None
            if last_results:

                if DEBUG:
                    print("[DEBUG] Saved results: ", last_results)

                # mode's keyword only for a verified user. A guest gets none.
                fuller = expand(last_question, last_results,
                                mode=identity.is_verified())
            if fuller:
                print(f"\nAssistant: {fuller}")
                print("(From the saved search results)")
            elif has_more(last_details):
                print(f"\nAssistant: {last_details}")
                print("(From the model's own notes, not from saved search results)")
            else:
                print("\nAssistant: I'm afraid I have nothing more to add.")
            continue

        # "/sources" shows where the last research came from, with no new AI call
        if query.lower().strip() == "/sources":
            if last_sources:
                print("\nSources found by the last search:")
                for i, line in enumerate(last_sources, 1):
                    print(f"    {i}. {line}")
            else:
                print(
                    "\nNo sources yet. I only list them when a search tool found some.")
            continue

        if query.startswith("/"):
            print(pm.handle_command(query)
                  or "Unknown command. Type /help to see the memory commands.")
            continue

        if query.lower().strip(" !.") in EXIT_WORDS:

            # Review what the memory noticed before closing
            print(pm.review())

            print("Assistant: Until next time.")
            break

        # "Remember ..." in a normal sentence is saved right away
        memory_notice = pm.handle_message(query)
        if memory_notice:
            print(f"[Memory] {memory_notice}")

        last_reply = chat_history[-1].content if chat_history else ""
        if is_casual(query, last_reply, last_was_task):
            if DEBUG:
                print("[DEBUG] mode: casual")
            try:
                answer = casual_reply(
                    query,
                    chat_history,
                    memory_for(query),
                    datetime.now().strftime("%B %d, %Y")
                )
            except Exception as e:
                traceback.print_exc()
                print(
                    f"\nAssistant: Something went wrong, please try again. ({type(e).__name__})")
                continue

            print(f"\nAssistant: {answer}")
            last_details = ""
            last_results = ""
            last_was_task = False

            # Same bookkeeping as a normal turn
            chat_history.append(HumanMessage(content=query))
            chat_history.append(AIMessage(content=answer))
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session["messages"].append(
                {"role": "user", "content": query, "time": now}
            )
            session["messages"].append(
                {"role": "assistant", "content": answer, "time": now}
            )
            save_session()
            if not memory_notice:
                pm.note_message(query)
            continue

        # Send the question plus everything said so far
        try:
            raw_response = agent_executor.invoke(
                {"query": query, "chat_history": chat_history,
                 "today": datetime.now().strftime("%B %d, %Y"),
                 "personal_memory": memory_for(query),
                 }
            )
        except Exception as e:
            # Problem - No internet, API error, or a tool crash
            traceback.print_exc()
            print(
                f"\nAssistant: Something went wrong, please try again. ({type(e).__name__})")
            continue

        # OpenAI returns a string, Claude return a list
        # This is for more testing, should remove one later
        output = raw_response.get("output")
        if isinstance(output, list):
            output = output[0]["text"]

        if DEBUG:
            print("\n[DEBUG] Raw reply:", output)

        # The tools that the agent called. We trust this over what the AI says it used.
        steps = raw_response.get("intermediate_steps", [])
        tools_called = [action.tool for action,
                        out in steps if not is_failed(out)]
        failed_tools = [action.tool for action, out in steps if is_failed(out)]

        last_was_task = True

        structured_response = parse_response(output)
        # If the AI skips the JSON format, keep its plain reply so the code isn't lost
        plain_text = ""
        if not structured_response:
            plain_text = output
            # The AI skipped the JSON format: ask it once to rewrite its own answer
            structured_response = rewrite_as_json(output)

        if structured_response:
            # The rewrite can drop code blocks, so put them back before the short answer
            answer = put_code_back(
                structured_response.summary, plain_text or structured_response.details)
            # Keep the full answer for "tell me more"
            last_details = structured_response.details
            print(f"\nAssistant: {answer}")
        else:
            answer = output
            last_details = ""
            print("\nAssistant:", answer)
            print(
                "(Note: this answer was not in the expected format, so there is no short and full version.)")

        # Keep what the tools found, so "tell me more" can use it
        last_question = query
        last_short = answer
        last_results = results_text(raw_response.get("intermediate_steps", []))

        # Sources come from the tool results, not from the AI
        new_sources = sources_from(raw_response.get("intermediate_steps", []))
        if new_sources:
            last_sources = new_sources

        # Show which tools really ran, whether or not the JSON worked
        if tools_called:
            # dict.fromkeys removes repeats but keeps the order
            tools_text = ", ".join(dict.fromkeys(tools_called))
            hint = f" | {len(new_sources)} sources found, type /sources" if new_sources else ""
            print(f"(Tools used: {tools_text}{hint})")
        else:
            print("(No tools used: this answer comes from the model's own knowledge.)")

        # Searches that returned an error, so a weak answer is not a mystery
        if failed_tools:
            print(
                f"(Searches that failed: {', '.join(dict.fromkeys(failed_tools))})")

        if has_more(last_details):
            print('(Say "tell me more" for the full answer.)')

        # Remember this turn for the next question
        chat_history.append(HumanMessage(content=query))
        chat_history.append(AIMessage(content=answer))

        # Save now, so closing the terminal loses nothing
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session["messages"].append(
            {"role": "user", "content": query, "time": now})
        session["messages"].append(
            {"role": "assistant", "content": answer, "time": now})
        save_session()

        # Collect this message so the AI can look for things worth remembering.
        # Skipped when it was already saved as a "remember" request.
        if not memory_notice:
            pm.note_message(query)

except KeyboardInterrupt:
    print("\nChat ended.")
