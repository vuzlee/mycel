# Inference local

Chạy một model nhỏ ngay trên máy để gánh phần việc khối lượng lớn: phân loại,
trích entity, chấm điểm liên quan, tóm tắt từng bản ghi. Phần tổng hợp cuối vẫn
gọi cloud — model 3B không đủ chất lượng để viết báo cáo.

## Vì sao chỉ một engine

vLLM và SGLang làm cùng một việc (serve LLM qua HTTP OpenAI-compatible). Dựng cả
hai chỉ tốn VRAM và thêm một thứ phải bảo trì. Dự án chọn **vLLM**.

## Ràng buộc phần cứng

Máy dev hiện tại: **GTX 1660 Ti 6GB** (Turing, sm_75).

| Ràng buộc | Hệ quả |
|---|---|
| Turing không có bf16 | phải chạy `--dtype float16` |
| Không FP8, không FlashAttention-2 | dùng kernel mặc định, throughput thấp hơn Ampere |
| 6GB VRAM | model 3B phải quantize 4-bit (~2GB), còn ~3.5GB cho KV cache |

Nên context phải giữ ngắn và không chạy song song nhiều request. Đây là giới hạn
thật của máy dev, không phải cấu hình cho prod.

## Chạy

```bash
docker compose --profile local-llm up -d vllm
```

Model mặc định: `Qwen/Qwen2.5-3B-Instruct-AWQ` — 4-bit AWQ, vừa 6GB.

Không bật profile thì mọi lượt gọi LLM đi cloud. Code không đổi: cả hai đều là
OpenAI-compatible endpoint, `llm/router.py` quyết định gọi cái nào.
