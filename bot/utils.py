import telegramify_markdown


def md_to_tg(text: str) -> str:
    """Convert Markdown to Telegram MarkdownV2."""
    return telegramify_markdown.markdownify(text)
