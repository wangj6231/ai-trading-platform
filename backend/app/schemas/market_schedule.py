from enum import Enum


class MarketScheduleMode(str, Enum):
    CONTINUOUS_24_7 = "CONTINUOUS_24_7"
    SESSION_CALENDAR = "SESSION_CALENDAR"
