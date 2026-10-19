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

# Prompt template
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
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
agent_executor = AgentExecutor(
    agent=agent, tools=tools, verbose=True, max_iterations=5)


# Using memory and searching old chats
# AI has no memory, so we resend this every turn
chat_history = []

# Load the most recent saved chat so the assistant can look back
past_chats = list_sessions()
if past_chats:
    old_chat = load_json(past_chats[0])

    # Check the last 20 messages only
    for m in old_chat["messages"][-20:]:
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

# Chat structure
print("\nAssistant: Hello. How can I help you today? ")
print("(Type 'goodbye' to end.)")

try:
    while True:
        query = input("\nYou: ").strip()

        # Empty input
        if not query:
            continue

        if query.lower().strip(" !.") in EXIT_WORDS:
            print("Assistant: Please let me know if you require any further help.")
            break

        # Send the question plus everything said so far
        raw_response = agent_executor.invoke(
            {"query": query, "chat_history": chat_history}
        )

        # OpenAI returns a string, Claude return a list
        # This is for more testing, should remove one later
        output = raw_response.get("output")
        if isinstance(output, list):
            output = output[0]["text"]

        try:
            structured_response = parser.parse(output)
            answer = structured_response.summary
            print(f"\nAssistant: {answer}")
            print(f"(Sources: {', '.join(structured_response.sources)})")
        except Exception:
            answer = output
            print("\nAssistant:", answer)

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

except KeyboardInterrupt:
    print("\nChat ended.")
