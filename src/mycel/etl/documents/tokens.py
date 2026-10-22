"""Token counting with the embedding model's own tokenizer."""

from functools import lru_cache
from typing import Any

from mycel.core.config import get_settings


@lru_cache(maxsize=1)
def _tokenizer() -> Any:
    from tokenizers import Tokenizer

    return Tokenizer.from_pretrained(get_settings().document_embedding_model)


def count(text: str) -> int:
    return len(_tokenizer().encode(text, add_special_tokens=False).ids)
