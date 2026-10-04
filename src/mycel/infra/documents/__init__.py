"""Uploaded files into passages: parse with docling, then chunk by structure.

parse.py    file -> DoclingDocument
chunk.py    DoclingDocument -> passages, tables kept whole or split by row
tokens.py   token counting with the embedding model's own tokenizer
"""
