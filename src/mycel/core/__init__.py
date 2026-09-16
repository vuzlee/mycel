"""Nền chung của toàn hệ: config đọc từ env/file, logger, exception gốc, kiểu dùng chung.

Tầng đáy: **không import module nào khác trong `mycel`**. Mọi tầng khác đều import được
nó, nên hễ nó phụ thuộc ngược lên là sinh vòng tròn.

Cùng khuôn với `agents/core/`, khác phạm vi: cái kia là nền chung của riêng `agents/`.
Hễ thấy `core/` lồng trong một package thì hiểu là "nền chung của package đó".
"""
