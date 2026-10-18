from datetime import datetime
from pathlib import Path
import json
import re

# Filename


def create_filename(topic: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    clean_topic = topic.lower()
    clean_topic = re.sub(r"[^a-z0-9]+", "_", clean_topic)
    clean_topic = clean_topic.strip("_")

    if not clean_topic:
        clean_topic = "research"

    return f"{clean_topic}_{timestamp}.txt"

# Save txt


def save_to_txt(data: str, filename: str, folder: str = "research_logs"):
    folder_path = Path(folder)
    folder_path.mkdir(exist_ok=True)

    file_path = folder_path / filename

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(data)

    return f"Data successfully saved to {file_path}"

# Json


def save_to_json(data: dict, filename: str, folder: str = "memory"):
    folder_path = Path(folder)
    folder_path.mkdir(exist_ok=True)

    json_filename = filename.replace(".txt", ".json")
    file_path = folder_path / json_filename

    # Save structured memory for the AI to use later
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    return f"JSON memory saved to {file_path}"

# Order the saved chats
# (Newest first)


def list_sessions(folder: str = "memory"):
    folder_path = Path(folder)

    # If no chats exits
    if not folder_path.exists():
        return []
    files = folder_path.glob("*.json")
    # Sort by last-changed time
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)

# Read one saved chat back into Python dictionary


def load_json(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
