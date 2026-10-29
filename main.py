from dotenv import load_dotenv
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from datetime import datetime

from prompts import SYSTEM_PROMPT
from tools import tools
from storage import (
    create_filename,
    save_to_json,
    save_to_txt,
    list_sessions,
    load_json,
)
import personal_memory as pm

load_dotenv()


# Specify all of the fields as output from LLM
class Response(BaseModel):
    topic: str
    summary: str
    sources: list[str]
    tools_used: list[str]


# Set up LLM
llm = ChatOpenAI(model="gpt-4o-mini")
parser = PydanticOutputParser(pydantic_object=Response)

# Function that memory can use to talk to the AI
# A plain AI call for the memory system (no tools, no chat history)


def ask_llm(text):
    content = llm.invoke(text).content
    # AI answers (OpenAI returns a string, Claude returns a list of parts)
    if isinstance(content, list):
        content = "".join(p.get("text", "")
                          for p in content if isinstance(p, dict))
    return content


# Prompt template
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("system",
         "Today's date is {today}. Use it to decide whether dates you read about are in the past or the future."),
        ("system", "{personal_memory}"),
        ("placeholder", "{chat_history}"),
        ("human", "{query}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
).partial(format_instructions=parser.get_format_instructions())

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
    agent=agent, tools=tools, verbose=True, max_iterations=5, return_intermediate_steps=True)


# Chat history and searching old chats
# AI has no memory, so we resend this every turn
chat_history = []

# Load the most recent saved chat so the assistant can look back
past_chats = list_sessions()
if past_chats:
    old_chat = load_json(past_chats[0])

    # Check the last 20 messages only
    # Add each message once, as the right type.
    for m in old_chat["messages"][-20:]:
        if m["role"] == "user":
            chat_history.append(HumanMessage(content=m["content"]))
        else:
            chat_history.append(AIMessage(content=m["content"]))


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


EXIT_WORDS = ["goodbye", "bye", "exit", "quit"]

# Give the memory system a way to talk to the AI
# Count today as an active day, archive old memories, and get any notices
memory_notices = pm.setup(ask_llm)

# Chat structure
print("\nAssistant: Hello. How can I help you today? ")
print("(Type 'goodbye' to end.)")

if memory_notices:
    print(f"[Memory] {memory_notices}")

try:
    while True:
        query = input("\nYou: ").strip()

        # Empty input
        if not query:
            continue

        if query.startswith("/"):
            print(pm.handle_command(query) or "Unknown command.")
            continue

        if query.lower().strip(" !.") in EXIT_WORDS:

            # Review what the memory noticed before closing
            print(pm.review())

            print("Assistant: Please let me know if you require any further help.")
            break

        # "Remember ..." in a normal sentence is saved right away
        memory_notice = pm.handle_message(query)
        if memory_notice:
            print(f"[Memory] {memory_notice}")

        # Send the question plus everything said so far
        raw_response = agent_executor.invoke(
            {"query": query, "chat_history": chat_history,
             "today": datetime.now().strftime("%B %d, %Y"),
             "personal_memory": pm.build_memory_prompt(),
             }
        )

        # OpenAI returns a string, Claude return a list
        # This is for more testing, should remove one later
        output = raw_response.get("output")
        if isinstance(output, list):
            output = output[0]["text"]

        # The tools that the agent called. We trust this over what the AI says it used.
        tools_called = [action.tool for action,
                        _ in raw_response.get("intermediate_steps", [])]

        try:
            structured_response = parser.parse(output)
        except Exception:
            # The AI sometimes writes text before the JSON, so try just the {...} part
            start, end = output.find("{"), output.rfind("}")
            try:
                structured_response = parser.parse(output[start:end + 1])
            except Exception:
                structured_response = None

        if structured_response:
            answer = structured_response.summary
            print(f"\nAssistant: {answer}")
        else:
            answer = output
            print("\nAssistant:", answer)

        # Show which tools really ran, whether or not the JSON worked
        if tools_called:
            # Only a parsed answer has a sources list
            if structured_response:
                print(f"(Sources: {', '.join(structured_response.sources)})")
            # dict.fromkeys removes repeats but keeps the order
            print(
                f"(Tools used: {', '.join(dict.fromkeys(tools_called))})")
        else:
            # No tool ran, so any sources the AI listed were never checked
            print(
                "(No tools used: this answer comes from the model's own knowledge.)")

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
