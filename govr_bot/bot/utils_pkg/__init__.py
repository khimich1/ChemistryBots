# Utils package
from typing import Any
import os
import json

# Импортируем все из utils.py
from ..utils import (
    ALL_TOPICS,
    LEARNING_TOPICS,
    TEXTBOOK_CONTENT,
    user_topics,
    user_learning_state,
    BEGIN_CHEM_TOPICS,
    ELEMENT_CHEM_TOPICS,
    PREPARED_LECTURES_DB,
    clean_html,
    latex_to_codeblock,
    get_prepared_chunks_count,
    get_prepared_lecture,
    ensure_chunk_title_column,
    get_chunk_title,
    set_chunk_title,
    get_audio_from_db,
    get_qa_questions,
    get_qa_answers,
    get_total_questions_count_for_topic,
    _parse_qa_field,
)
