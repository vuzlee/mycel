"""Write the original payload from a provider. Called only by `sources/`.

No transforms, no schema validation — malformed data is written too, because the point of
raw is being able to replay it when the transform logic turns out to be wrong.
"""
