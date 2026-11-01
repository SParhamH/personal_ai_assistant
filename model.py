"""
model.py - the one place that knows which AI model is used.
This file makes switching models easier and keeps everything organized.
"""

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Load .env here. The API key must exist before the model is created
load_dotenv()


# The one place the model is chosen. The prompt reads these too, so the assistant always knows which model it runs on.
MODEL_PROVIDER = "OpenAI"
MODEL_NAME = "gpt-4o-mini"

# Model that is used
llm = ChatOpenAI(model=MODEL_NAME)


# Function that memory can use to talk to the AI
def ask_llm(text):
    """A plain AI call for the memory system (no tools, no chat history)."""
    content = llm.invoke(text).content
    # AI answers (OpenAI returns a string, Claude returns a list of parts)
    if isinstance(content, list):
        content = "".join(p.get("text", "")
                          for p in content if isinstance(p, dict))
    return content
