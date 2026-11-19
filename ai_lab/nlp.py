"""Academic AI Lab entry point for the NLP material. The implementation moved to `shared/nlp.py` because the
production chatbot imports it at runtime; this module keeps the original `ai_lab.nlp` import path working."""
from shared.nlp import *          # noqa: F401,F403
from shared.nlp import (STOP_WORDS, Gazetteer, TfidfIndex, correct_spelling, edit_distance, expand_contractions,  # noqa: F401
                        lemmatize, normalize, stem, tokenize)
