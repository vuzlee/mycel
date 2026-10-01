"""Collection declarations: name, dimensions, distance metric.

**The dimension belongs to the model, so the name carries the model.** `bge-small` is 384
and a larger model is 768 or 1024; writing one into a collection built for the other is
refused by Qdrant, and the useful failure is at the name rather than at the write. Changing
model therefore means a new collection and a full reindex — there is no way to mix two
vector spaces in one, and no migration that converts between them.

Cosine, not dot product: `bge` is trained with cosine similarity, and on vectors that are
not unit-length the two disagree about which neighbour is nearest.
"""

from dataclasses import dataclass

from qdrant_client.models import Distance, VectorParams

#: Dimensions per model. Hard-coded rather than read from the loaded model, because the
#: collection has to be declared before anything is embedded — and a wrong guess here is
#: a collection that rejects every write, which is better than one that accepts half.
DIMENSIONS: dict[str, int] = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
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
    """The collection holding one point per gold work item.

    The name is `work_items__<model>` with the slashes and dots flattened: Qdrant accepts
    them, but a name that needs quoting in a URL is a name somebody will mistype.
    """
    if model not in DIMENSIONS:
        raise ValueError(
            f"unknown embedding model {model!r}; add its dimension to DIMENSIONS first "
            f"(known: {', '.join(sorted(DIMENSIONS))})"
        )
    slug = model.replace("/", "_").replace(".", "_").replace("-", "_").lower()
    return Collection(name=f"work_items__{slug}", dimensions=DIMENSIONS[model])
