<!-- doc-id: docs-deployment | lang: vi | source-rev: 19243a73 -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/deployment.md`](../../../docs/deployment.md) (rev `19243a73`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Triển khai

Một container phục vụ cả hai pipeline. Trọng số v1 đến từ các repo Hugging Face công khai; các tệp v2 (`model.int8.onnx`, `vocab.json`, `scorer.json`) đến từ một repo Hugging Face (`dris1153/pronunciation-v2`, công khai). Cả hai được đóng sẵn vào image lúc build (không cần volume lưu trữ bền vững).

```mermaid
flowchart LR
    train["training/ (máy GPU)"] -->|"export_onnx --int8<br/>train_scorer"| files["model.int8.onnx<br/>vocab.json<br/>scorer.json"]
    files -->|"scripts/upload_v2_model.py<br/>(HF_TOKEN, quyền ghi)"| hf[("repo HF<br/>dris1153/pronunciation-v2")]
    hf -->|"download_model.py<br/>V2_MODEL_REPO"| build["docker build /<br/>nixpacks build"]
    pub[("facebook/wav2vec2-base-960h<br/>(công khai)")] -->|"download_model.py"| build
    build --> img["image: /app/model_cache<br/>+ /app/data/models/hubert-phone-ctc"]
    img --> run["python main.py<br/>(1 worker uvicorn)"]
```

## Làm một lần: công bố các tệp v2

Cần một tài khoản Hugging Face và một token có quyền **ghi**.

```powershell
$env:HF_TOKEN = "hf_xxx"          # write token, never commit it
python scripts/upload_v2_model.py --repo dris1153/pronunciation-v2
```

Script tạo repo ở chế độ riêng tư nếu repo chưa tồn tại (nó không bao giờ đổi chế độ hiển thị của một repo đã có) và tải lên ba tệp từ `data/models/hubert-phone-ctc/`. Repo đã xuất bản là công khai nên các lần build không cần token; với repo riêng tư, hãy tạo một token **đọc** riêng cho các lần build.

## Docker

```bash
# v1 only (v2 endpoint will answer 503)
docker build -t pronunciation-validator .

# v1 + v2 (the model repo is public, no token needed)
docker build --build-arg V2_MODEL_REPO=dris1153/pronunciation-v2 -t pronunciation-validator .

# private model repo: the token travels as a BuildKit secret, so it never lands in an image layer
docker build \
  --build-arg V2_MODEL_REPO=<org>/<private-repo> \
  --secret id=HF_TOKEN,env=HF_TOKEN \
  -t pronunciation-validator .

docker run -p 8000:8000 -e API_KEY=<32+ char key> -e DEBUG=false pronunciation-validator
```

Image làm gì: `python:3.11-slim` + ffmpeg/libsndfile, PyTorch chỉ CPU (v1), `requirements.txt` (có `onnxruntime` cho v2), chạy `download_model.py` (model v1, rồi các tệp v2 khi `V2_MODEL_REPO` được đặt), chuyển sang người dùng không phải root, khởi động `python main.py`. `.dockerignore` loại `data/` và `.venv-train/`, nên các dataset local không bao giờ vào build context.

> **Trạng thái:** bản build bằng Dockerfile đã được chạy trên Coolify (Docker build pack): nó tải các tệp v2 và v2 được nạp khi khởi động. Đường nixpacks chưa được chạy. Nếu build có dùng token, hãy chạy `docker history` một lần để xác nhận token không nằm trong layer nào.

## Railway

`railway.toml` dùng Dockerfile builder, health check `GET /health` (timeout 120 s) và khởi động lại khi lỗi (thử lại 3 lần). `PORT` do Railway gán và được pydantic-settings đọc. Hãy đặt `API_KEY`, `DEBUG=false` và các biến còn lại trong dashboard.

Với v2, hãy đặt `V2_MODEL_REPO` làm build variable. Chỉ repo riêng tư mới cần thêm `HF_TOKEN` được cung cấp cho lúc build. Railway mount build secret theo **tên service variable**, đó là lý do secret id trong Dockerfile là `HF_TOKEN`. Nếu không có secret nào được mount, build arg `HF_TOKEN` sẽ được dùng thay thế. Để trống `V2_MODEL_REPO` nếu chỉ muốn đưa v1 lên.

## Coolify / nixpacks

`nixpacks.toml` cài PyTorch bản CPU và `requirements.txt`, đóng sẵn model v1, rồi chạy `python download_model.py --v2-only`. Đặt `V2_MODEL_REPO` làm **build variable**; chỉ thêm `HF_TOKEN` nếu dùng repo riêng tư (nixpacks có thể giữ lại build variable trong image nó tạo ra, nên hãy dùng token chỉ đọc và đổi token nếu image từng bị chia sẻ). Ứng dụng khởi động với tư cách `appuser` qua `su`.

## Định cỡ tài nguyên và quy tắc lúc chạy

| Chủ đề | Hướng dẫn |
| --- | --- |
| Worker | **Một** worker uvicorn. Mỗi worker tải một bản sao riêng của tất cả model |
| RAM | RSS đo được sau khi tải: chỉ v1 796 MB, v1 + v2 INT8 cùng nhau 1030 MB, chỉ v2 ~430 MB, tăng lên 600-660 MB sau các request (ONNX arena). RSS khi chạy chung sau các request chưa được đo; hãy dự trù khoảng 2 GB cho tiến trình chạy chung |
| CPU | 4 vCPU: `MAX_CONCURRENT_INFERENCES=2`. 2 vCPU: để tự động. Phía sau Docker `--cpus`/Railway hãy đặt `OMP_NUM_THREADS` |
| Health | `GET /health` là công khai. Nó chỉ báo trạng thái tải của v1; model v2 bị thiếu sẽ hiện ra là `503` ở `/api/v2/evaluate`, và là một cảnh báo trong log khởi động |
| Cô lập lỗi | Model v2 thiếu hoặc hỏng không bao giờ cản trở khởi động; v1 vẫn phục vụ |
| Trước khi chuyển client | Chạy `python debugs/benchmark.py --api v2 --int8 --cpus 4` trên máy chủ thật. Số liệu tốc độ trong [evaluation.md](evaluation.md) đo trên máy dev |

Biến môi trường: [configuration.md](configuration.md).
