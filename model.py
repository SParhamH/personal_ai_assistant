"""
model.py - the one place that knows which AI model is used.
This file makes switching models easier and keeps everything organized.
"""

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Load .env here. The API key must exist before the model is created
load_dotenv()

# Model that is used
llm = ChatOpenAI(model="gpt-4o-mini")


# Function that memory can use to talk to the AI
def ask_llm(text):
    """A plain AI call for the memory system (no tools, no chat history)."""
    content = llm.invoke(text).content
    # AI answers (OpenAI returns a string, Claude returns a list of parts)
    if isinstance(content, list):
        content = "".join(p.get("text", "")
                          for p in content if isinstance(p, dict))
    return content
