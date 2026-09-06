"""
Alert message templates for sirens broadcasts.
"""

MESSAGES = {
    # base / legacy
    "air_raid_alert": "🟠 Повітряна тривога!",
    "air_raid_alert_cancelled": "🟢 Відбій тривоги!",
    "threat_of_shelling": "🟤 Загроза артобстрілу!",
    "threat_of_shelling_cancelled": "🟢 Відбій загрози артобстрілу !",
    # єТривога, дворівнева система
    "air_raid_alert:yellow": "🟡 Жовтий рівень тривоги!",
    "air_raid_alert:red": "🔴 Червоний рівень тривоги!",
}


def alert_message_key(alert_type: str, level: str | None = None) -> str:
    """Ключ тексту: з рівнем, якщо для нього є свій текст, інакше базовий."""
    if level:
        key = f"{alert_type}:{level}"
        if key in MESSAGES:
            return key
    return alert_type
