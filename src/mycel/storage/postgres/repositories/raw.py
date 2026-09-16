"""Ghi payload nguyên bản từ provider. Chỉ `sources/` gọi.

Không transform, không validate schema — sai thì cũng ghi, vì mục đích của raw là
replay được khi logic transform hoá ra sai.
"""
