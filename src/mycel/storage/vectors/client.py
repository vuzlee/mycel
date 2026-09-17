"""One shared Qdrant client, address read from config.

This is the only file importing Qdrant's SDK — the same principle that confines every
provider SDK to `agents/core/model_builder.py`.
Moving to a different vector store leaves the rest of the system unaware.
"""
