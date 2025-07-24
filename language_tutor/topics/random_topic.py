import random
from .constants import TOPICS


def get_random_topic() -> str:
    return random.choice(TOPICS)
