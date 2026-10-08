"""Collection declarations; the name carries the model, since dimensions depend on it."""

from dataclasses import dataclass

from qdrant_client.models import Distance, VectorParams

#: Dimensions per model, needed before anything is embedded.
DIMENSIONS: dict[str, int] = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "jinaai/jina-embeddings-v2-small-en": 512,
}


@dataclass(frozen=True, slots=True)
class Collection:
    """One collection: what it is called, and the shape of what goes in it."""

    name: str
    dimensions: int

    @property
    def params(self) -> VectorParams:
        return VectorParams(size=self.dimensions, distance=Distance.COSINE)


def work_items(model: str) -> Collection:
    """`work_items__<model>`, one point per gold work item, with URL-unsafe characters flattened."""
    return _named("work_items", model)


def documents(model: str) -> Collection:
    """One point per document passage."""
    return _named("documents", model)


def _named(prefix: str, model: str) -> Collection:
    if model not in DIMENSIONS:
        raise ValueError(
            f"unknown embedding model {model!r}; add its dimension to DIMENSIONS first "
            f"(known: {', '.join(sorted(DIMENSIONS))})"
        )
    slug = model.replace("/", "_").replace(".", "_").replace("-", "_").lower()
    return Collection(name=f"{prefix}__{slug}", dimensions=DIMENSIONS[model])
