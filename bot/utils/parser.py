import re
from typing import Union


def parse_chat_target(text: str) -> Union[int, str]:
    """
    Parse a chat target from various formats:
    - Private channel/group link: https://t.me/c/1234567890/123 -> -1001234567890
    - Private channel link without msg ID: https://t.me/c/1234567890 -> -1001234567890
    - Invite link: https://t.me/+AbCdEf or https://t.me/joinchat/AbCdEf -> invite URL
    - Public link: https://t.me/channel_name -> channel_name
    - Username: @channel_name -> channel_name
    - Numeric ID string: "-100123456789" -> -100123456789
    """
    text = (text or "").strip()

    # 1. Private message/channel link: https://t.me/c/4349941925 or /68327 or topic /5/68327
    priv_match = re.search(r't\.me/c/(\d+)(?:/\d+)*', text)
    if priv_match:
        return int(f"-100{priv_match.group(1)}")

    # 2. Private invite link: https://t.me/+hash or https://t.me/joinchat/hash
    invite_match = re.search(r'(?:https?://)?t\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', text)
    if invite_match:
        return f"invite:{invite_match.group(1)}"

    # 3. Public link or username: https://t.me/username or @username
    pub_match = re.search(r'(?:https?://)?t\.me/([a-zA-Z0-9_]{3,32})', text)
    if pub_match:
        val = pub_match.group(1)
        if val.lower() not in ['c', 'joinchat']:
            return val

    if text.startswith('@'):
        # Extract first token cleanly in case extra text trails
        return text[1:].split()[0]

    # 4. Numeric ID
    try:
        return int(text)
    except ValueError:
        pass

    return text
