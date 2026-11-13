# Báo cáo cá nhân — Day 06

> Thông tin học viên và repo được ghi trong [`STUDENT.md`](../../STUDENT.md). Trước khi nộp, học viên cần tự xác nhận/sửa các nhãn audit sơ bộ và kiểm tra quyền tái phân phối corpus.

## Dữ liệu và pipeline

- **Chủ đề/nguồn:** 36 đơn vị nội dung khoa học vũ trụ từ các trang NASA Science chính thức. Mỗi trang web được lưu thành một đơn vị văn bản riêng, có `document_id`, URL, ngày truy cập, SHA-256 và metadata. Pipeline gán `page=1` cho đơn vị trang web này; đây không phải số trang in/PDF. Mỗi đơn vị có ít nhất 1.639 ký tự đã chuẩn hóa. Chủ đề gồm hành tinh, Mặt Trăng, hệ Mặt Trời, thiên thể nhỏ, Mặt Trời, ngoại hành tinh, vũ trụ và nhiệm vụ.
- **Quyền sử dụng:** ghi nguồn và credit NASA. NASA lưu ý một số nội dung bên thứ ba có quyền riêng; trang nguồn không cấp giấy phép riêng cho mọi đoạn văn. Corpus dùng cho lab giáo dục không thương mại; cần xác minh quyền trước khi công khai hoặc tái phân phối. Chi tiết nguồn ở [`starter/data/manifest.json`](../../starter/data/manifest.json) và [`starter/results/corpus_manifest.json`](../../starter/results/corpus_manifest.json).
- **Chuẩn hóa/giới hạn:** UTF-8, Unicode NFC, chuẩn hóa khoảng trắng và xuống dòng nhưng giữ ranh giới đoạn; không có trang rỗng trong 36 đơn vị được đưa vào index. Trang web có thể chứa menu, tiêu đề/phần điều hướng và văn bản thay đổi theo thời gian; manifest giữ snapshot và hash để truy nguyên.
- **Embedding:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 chiều, FastEmbed 0.9.1 + ONNX Runtime 1.23.2 trên CPU. Model Apache-2.0. Qdrant Client 1.20.0, embedded/persistent, cosine, exact search (HNSW tắt). Có thể chạy bằng `python -m src.run` trong `starter/`; model được cache một lần. Lần chạy xác nhận offline dùng `FASTEMBED_LOCAL_FILES_ONLY=true`. Không gọi embedding API, không cần API key; chi phí embedding là **$0**. Tải trang NASA và tải model lần đầu cần mạng, nhưng đó không phải embedding API.
- **Metadata:** `document_id`, `source`, `page`, `category`, `language`. `category` lấy từ manifest của nguồn, dùng làm filter khi câu hỏi đã cung cấp phạm vi; không suy ra filter từ đáp án/gold. Kiểm tra máy đối chiếu 45/45 hit test với manifest và 15/15 hit được lọc của C tuân thủ filter.

## Cấu hình và benchmark

- **A:** cửa sổ ký tự cố định 500, overlap 50; không lọc metadata.
- **B:** gom đoạn văn, tối đa 1.000 ký tự; không lọc metadata.
- **C:** cùng chunk và vector như B, chỉ thêm filter `category` khi câu hỏi cung cấp filter. Vì vậy B–C chỉ thay đổi việc lọc metadata.
- **Benchmark:** 20 câu hỏi (15 dev / 5 test), gồm 8 câu có filter (3 dev / 5 test). Các gold quote được kiểm tra tự động hiện diện trong đơn vị nguồn đã nêu; cần xác minh thủ công ý nghĩa và tính đầy đủ trước khi nộp. Bộ câu hỏi và trace: [`questions.json`](../../starter/data/questions.json), [`traces.jsonl`](../../starter/results/traces.jsonl).
- **Tiêu chí chọn:** dùng Evidence Hit@3 dev cao nhất; A đạt 10/15 so với B/C 8/15. Test đã được xem khi hoàn thiện báo cáo/audit, nên **không** xem 5 câu này là holdout độc lập hay bằng chứng tổng quát. Không thay cấu hình theo kết quả test.
- **Evidence Hit@3:** hit chỉ được tính khi top-3 có đúng nguồn/trang gold và chứa trọn quote (sau chuẩn hóa). Cách tính nghiêm ngặt này có thể bỏ sót nguồn NASA thay thế tương đương hoặc bằng chứng bị chia qua ranh giới chunk.

## Kết quả truy xuất

| Strategy | Split | Hit@1 | Evidence Hit@3 | Số chunk | Thời gian build | Chi phí embedding |
|---|---|---:|---:|---:|---:|---:|
| A | Dev | 7/15 (46.7%) | 10/15 (66.7%) | 562 | 58.209 s | $0 |
| A | Test | 1/5 (20%) | 1/5 (20%) | 562 | 58.209 s | $0 |
| B | Dev | 6/15 (40%) | 8/15 (53.3%) | 300 | 34.716 s | $0 |
| B | Test | 0/5 (0%) | 2/5 (40%) | 300 | 34.716 s | $0 |
| C | Dev | 6/15 (40%) | 8/15 (53.3%) | 300 | 3.048 s* | $0 |
| C | Test | 1/5 (20%) | 3/5 (60%) | 300 | 3.048 s* | $0 |

`*` C tái sử dụng vector B; 3.048 giây chỉ là thời gian ghi index tăng thêm, không so sánh trực tiếp với build độc lập của A/B. A/B lần lượt gồm embedding + ghi index: A 52.573 + 5.636 giây; B 31.835 + 2.881 giây. Số liệu được lưu ở [`summary.json`](../../starter/results/summary.json) và [`run_metadata.json`](../../starter/results/run_metadata.json).

## Audit năm tiêu chí

Các nhãn coherence và grounding dưới đây là **gợi ý sơ bộ do Copilot AI**, chưa phải nhãn thủ công/độc lập của sinh viên. Metadata là phép đối chiếu máy với manifest. Cần đọc từng đoạn và xác nhận/sửa nhãn trước khi nộp.

| Strategy | Coherence trung bình /2 (n=10) | Metadata đúng/đủ (n=15 hit) | Filter đúng (n=15 hit test C) | Grounding 0/1/2 (5 câu) | Grounding trung bình /2 |
|---|---:|---:|---:|---:|---:|
| A | 1.0 | 15/15 | N/A | 0/1/2: 0/1/4 | 1.8 |
| B | 1.7 | 15/15 | N/A | 0/1/2: 1/1/3 | 1.4 |
| C | 1.7 | 15/15 | 15/15 | 0/1/2: 0/1/4 | 1.8 |

- **Coherence:** chọn 10 vị trí đầu (offset 0) theo `document_id`, cùng vị trí cho A/B/C; thang 0–2. A cắt cửa sổ cố định; B/C tốt hơn trong mẫu nhưng 3/10 chunk đầu còn trộn tiêu đề/liên kết hoặc danh sách nên chỉ được 1/2. Đây là đánh giá sơ bộ, cần người học xác nhận. Mẫu trống [`manual_audit_template.jsonl`](../../starter/results/manual_audit_template.jsonl); gợi ý có giải thích [`preliminary_ai_audit.jsonl`](../../starter/results/preliminary_ai_audit.jsonl) và [`preliminary_ai_audit_summary.json`](../../starter/results/preliminary_ai_audit_summary.json).
- **Metadata:** cả 45 hit test đều giữ đúng nguồn, trang, category và ngôn ngữ theo manifest; 15/15 kết quả lọc của C đúng filter. Metadata hỗ trợ truy vết và phân loại chủ đề; `category` còn khá thô và chưa hỗ trợ lọc theo thời gian/tiểu mục.
- **Grounding:** chấm sơ bộ 5 câu test mỗi cấu hình, theo mức độ top-3 hỗ trợ đầy đủ câu trả lời: 0 = không đủ; 1 = một phần/thiếu điều kiện; 2 = đủ và truy nguyên được. Điểm gợi ý không thay thế audit thủ công.

## Phân tích và kết luận

- **A–B:** chuyển từ cửa sổ ký tự sang đoạn văn giảm chunk 562 xuống 300 (46.6%) và build 58.209 xuống 34.716 giây; dev Evidence Hit@3 giảm 10/15 xuống 8/15. Chunk dài ít hơn nhưng có thể tăng nhiễu khi nhiều ý cùng đoạn.
- **B–C:** cùng 300 chunk và vector. Lọc category giữ dev Evidence Hit@3 bằng B (8/15), tăng test từ 2/5 lên 3/5 trong bộ test nhỏ; thời gian C chỉ là incremental. C là lựa chọn hợp lý khi phạm vi metadata do người dùng cung cấp rõ ràng, nhưng không chứng minh lọc luôn cải thiện kết quả.
- **Lỗi minh họa:** `q19` (so sánh tổng khối lượng asteroid với Mặt Trăng): B trả về các chunk Pluto/ngoại hành tinh, không có evidence cần thiết; C lọc `small_bodies` và tìm được nội dung asteroid. `q20` (Oort Cloud): ở cả A/B/C, câu trả lời cần cả trạng thái chưa quan sát trực tiếp lẫn cơ sở suy luận; top-3 không giữ trọn bằng chứng này, một phần bị cắt qua ranh giới chunk. Đây là lý do grounding chỉ được gợi ý 1/2 cho câu này.
- **Giới hạn metric:** `q18` có top hit từ trang NASA Black Hole Anatomy giải thích ánh sáng không thoát khỏi event horizon, nhưng gold chỉ trỏ đến trang Black Holes; chỉ số strict exact-source có thể không ghi nhận nguồn thay thế này. Không sửa gold sau khi đã xem test. Tập test chỉ có 5 câu, thời gian phụ thuộc máy/cache và lần chạy C không độc lập; không suy rộng kết quả.
- **Cải tiến:** nhờ người học xác minh thủ công toàn bộ gold/audit; bổ sung gold alternatives trước khi mở test mới; tạo test mới chưa xem, thêm câu hỏi và nguồn đa dạng; tách thời gian tải model lần đầu khỏi thời gian build.

## Công cụ và tái lập

AI được dùng để hỗ trợ triển khai và phân tích; các nhãn trong file preliminary được đánh dấu rõ là chưa xác nhận. Chạy kiểm thử bằng `python -m unittest discover -s tests -v`, sau đó `python -m src.run` trong thư mục `starter`. Kết quả, manifest, benchmark và source downloader được lưu trong thư mục tương ứng.
