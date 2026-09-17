"""Collection declarations: name, dimensions, distance metric, index settings.

Dimensions are tied to the embedding model. Changing model means creating a new collection
and re-indexing everything — there is no way to mix two different vector spaces in one
collection. So the collection name must carry the model version.
"""
