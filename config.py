import os
from typing import List

class Config:
    # Telegram Config
    TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
    AUTHORIZED_USER_IDS: List[int] = [int(id_) for id_ in os.getenv("AUTHORIZED_USER_IDS", "").split(",") if id_]
    SOURCE_CHANNEL_ID: int = int(os.getenv("SOURCE_CHANNEL_ID"))
    DESTINATION_GROUP_ID: int = int(os.getenv("DESTINATION_GROUP_ID"))
    
    # Behavior Config
    DELAY_BETWEEN_FORWARDS: float = float(os.getenv("DELAY_BETWEEN_FORWARDS", "1.5"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def validate(cls):
        if not all([cls.TOKEN, cls.AUTHORIZED_USER_IDS, cls.SOURCE_CHANNEL_ID, cls.DESTINATION_GROUP_ID]):
            raise ValueError("Missing required environment variables")
