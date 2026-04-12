import logging

from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from pydantic import BaseModel, Field

from bot import db

router = Router()
logger = logging.getLogger(__name__)

COMMANDS = {"facts": "Manage remembered facts — /facts | set &lt;key&gt; &lt;value&gt; | remove &lt;key&gt;"}


# ---- Pydantic parameter models ----

class _SetFactParams(BaseModel):
    key: str = Field(description="The fact name, e.g. 'name', 'timezone', 'preferred_news_source'.")
    value: str = Field(description="The value to store for this fact.")


class _RemoveFactParams(BaseModel):
    key: str = Field(description="The fact name to remove.")


# ---- Business logic ----

def list_facts(user_id: int) -> str:
    facts = db.get_facts(user_id)
    if not facts:
        return "No facts stored yet."
    lines = ["<b>Stored facts:</b>"]
    for key, value in facts.items():
        lines.append(f"• <b>{key}</b>: {value}")
    return "\n".join(lines)


def set_fact(user_id: int, key: str, value: str) -> str:
    db.set_fact(user_id, key.strip().lower(), value.strip())
    return f"Remembered: <b>{key}</b> = {value}"


def remove_fact(user_id: int, key: str) -> str:
    removed = db.remove_fact(user_id, key.strip().lower())
    if removed:
        return f"Forgot fact: <b>{key}</b>"
    return f"No fact named <b>{key}</b> found."


# ---- Tool factory — called by chat.py with the current user_id ----

def make_facts_tools(user_id: int) -> list:
    """Return AI tools with user_id pre-bound via closures."""

    def _do_set_fact(key: str, value: str) -> str:
        return set_fact(user_id, key, value)

    def _do_remove_fact(key: str) -> str:
        return remove_fact(user_id, key)

    def _do_list_facts() -> str:
        return list_facts(user_id)

    return [
        ai_tool(
            name="set_fact",
            description=(
                "Remember a fact about the user. Use this when the user tells you something "
                "they want you to remember, e.g. their name, timezone, preferred news source. "
                "The key should be a short lowercase identifier like 'name' or 'timezone'."
            ),
            parameters=_SetFactParams,
            execute=_do_set_fact,
        ),
        ai_tool(
            name="remove_fact",
            description="Forget a previously stored fact about the user.",
            parameters=_RemoveFactParams,
            execute=_do_remove_fact,
        ),
        ai_tool(
            name="list_facts",
            description="List all facts currently remembered about the user.",
            parameters={"type": "object", "properties": {}, "required": []},
            execute=_do_list_facts,
        ),
    ]


# ---- aiogram command handler ----

@router.message(Command("facts"))
async def cmd_facts(message: Message) -> None:
    user_id = message.from_user.id
    args = message.text.removeprefix("/facts").strip()

    if not args:
        await message.answer(list_facts(user_id))
    elif args.startswith("set "):
        rest = args.removeprefix("set ").strip()
        parts = rest.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Usage: /facts set &lt;key&gt; &lt;value&gt;")
        else:
            await message.answer(set_fact(user_id, parts[0], parts[1]))
    elif args.startswith("remove "):
        key = args.removeprefix("remove ").strip()
        await message.answer(remove_fact(user_id, key))
    else:
        await message.answer(
            "Usage:\n"
            "• /facts — list stored facts\n"
            "• /facts set &lt;key&gt; &lt;value&gt; — remember a fact\n"
            "• /facts remove &lt;key&gt; — forget a fact\n\n"
            "You can also just tell me in plain language:\n"
            "<i>e.g. 'Remember my name is Edwin' or 'Forget my timezone'</i>"
        )
