"""
Maps semantic keys to Telegram custom (premium) emoji IDs, gathered via
/emojiid from the "Game Emoji" pack. pe(key) returns an HTML <tg-emoji>
tag to embed directly in message text -- this only works because the bot
now runs in HTML parse mode (see app/bot.py); it silently does nothing
under the old legacy-Markdown mode, which is why that switch had to
happen first.

`fallback` is what non-Premium viewers see, what shows in system
notifications, and what a message degrades to if forwarded somewhere
that can't render custom emoji. Picked to loosely match each icon's
theme -- not required to match the custom art pixel-for-pixel.
"""
EMOJI_IDS: dict[str, tuple[str, str]] = {
    "boss": ("5228962845672096235", "👹"),
    "crossed_swords": ("5454014806950429357", "⚔️"),
    "noob": ("5255738543673721267", "🐣"),
    "crit": ("5373342608028352831", "💥"),
    "rip": ("5463186335948878489", "💀"),
    "gold": ("5463046637842608206", "🪙"),
    "up": ("5463122435425448565", "📈"),
    "gg": ("5465465194056525619", "🎉"),
    "boom": ("5226813248900187912", "💣"),
    "rage": ("5463335865235288297", "😡"),
    "ko": ("5465137208878969279", "🥊"),
    "lol": ("5463121572137022242", "😂"),
    "buff": ("5462995330163289902", "💪"),
    "bg": ("5465198330558557107", "📉"),
    "wtf": ("5463139580934892960", "😳"),
    "res": ("5453870826761765894", "🔄"),
    "ns": ("5454177848203951217", "😅"),
    "sad": ("5463137996091962323", "😢"),
    "wp": ("5372957680174384345", "🤝"),
    "hype": ("5463412289883353404", "🚨"),
    "ban": ("5463358164705489689", "🚫"),
    "hit": ("5463156928307801722", "🎯"),
    "save": ("5462956611033117422", "🛡️"),
    "ez": ("5372965329511139384", "😎"),
    "pog": ("5375331860786200544", "🤯"),
    "loot": ("5463172695132745432", "🎁"),
    "l2p": ("5465225015190367274", "📉"),
    "top": ("5463071033256848094", "🏆"),
    "vip": ("5229011542011299168", "👑"),
    "cr8": ("5454092060527181056", "✅"),
    "play": ("5453921696354419743", "🎮"),
    "afk": ("5462990652943904884", "⏳"),
    "bff": ("5373110220232870002", "💸"),
    "pts": ("5199552030615558774", "💰"),
    "skull": ("5462882007451185227", "💀"),
    "wager": ("5226928895189598791", "🥷"),
    "bolt": ("5893450623449305489", "⚡"),
}


def pe(key: str) -> str:
    """Returns an inline <tg-emoji> HTML tag for `key`. An unmapped key
    falls back to a plain '❓' instead of raising, so a typo here degrades
    a message instead of crashing it."""
    if key not in EMOJI_IDS:
        return "❓"
    custom_id, fallback = EMOJI_IDS[key]
    return f'<tg-emoji emoji-id="{custom_id}">{fallback}</tg-emoji>'
