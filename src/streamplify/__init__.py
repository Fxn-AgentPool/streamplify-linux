"""Linux client for the Streamplify DECK."""
from .device import Deck, KeyEvent, key_at, pos_of, ROWS, COLS, KEY_COUNT, KEY_SIZE

__all__ = ["Deck", "KeyEvent", "key_at", "pos_of", "ROWS", "COLS", "KEY_COUNT", "KEY_SIZE"]
__version__ = "0.1.0"
