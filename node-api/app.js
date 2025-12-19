
const form = document.getElementById('uploadForm');
const fileInput = document.getElementById('fileInput');
const optionsInput = document.getElementById('options-input');
const statusEl = document.getElementById('status');
const galleryEl = document.getElementById('gallery');
const gridEl = document.getElementById('previewGrid');
const shadowToggleEl = document.getElementById('shadow-toggle');
const downloadAllBtn = document.getElementById('downloadAllBtn');

// lưu danh sách URL kết quả đã xử lý để "Download all"
let currentResultUrls = [];
function setStatus(message, isError = false) {
    statusEl.textContent = message;
    statusEl.classList.toggle('error', !!isError);
}

function renderGallery(files) {
    gridEl.innerHTML = '';
    if (!files || !files.length) {
        galleryEl.style.display = 'none';
        currentResultUrls = [];
        return;
    }
    galleryEl.style.display = 'block';

    // reset danh sách URL kết quả
    currentResultUrls = [];

    files.forEach((file, index) => {
        const card = document.createElement('div');
        card.className = 'preview-card';

        // chọn url từ nhiều nguồn, tránh undefined
        const url = (typeof file === 'string')
            ? file
            : (file.url || file.dataUrl || file.data_url);
        if (!url) {
            console.warn('renderGallery: missing url for file', file);
            return;
        }

        // chỉ lưu URL đã xử lý (không lưu object URL local)
        currentResultUrls.push(url);

        // tạo khung nền caro
        const bg = document.createElement("div");
        bg.className = "preview-bg-checker";
        bg.style.padding = "12px";
        bg.style.borderRadius = "8px";

        // ảnh
        const img = document.createElement("img");
        img.src = url;
        img.style.width = "100%";
        img.style.height = "auto";
        img.style.display = "block";

        // cho ảnh vào khung caro
        bg.appendChild(img);

        // cho khung caro vào card
        card.appendChild(bg);


        const name = document.createElement('div');
        name.className = 'preview-name';
        name.textContent = file.name || `Image ${index + 1}`;

        const footer = document.createElement('div');
        footer.className = 'preview-footer';

        const indexLabel = document.createElement('span');
        indexLabel.className = 'preview-index';
        indexLabel.textContent = `#${index + 1}`;

        const downloadBtn = document.createElement('button');
        downloadBtn.type = 'button';
        downloadBtn.className = 'btn-secondary';
        downloadBtn.textContent = 'Download';
        downloadBtn.addEventListener('click', () => {
            const a = document.createElement('a');
            a.href = url;
            a.download = file.name || 'image.png';
            document.body.appendChild(a);
            a.click();
            a.remove();
        });

        footer.appendChild(indexLabel);
        footer.appendChild(downloadBtn);

        card.appendChild(img);
        card.appendChild(name);
        card.appendChild(footer);

        gridEl.appendChild(card);
    });
}

// ===== Submit form: gửi ảnh + options xuống backend =====
form.addEventListener('submit', async (e) => {
    console.log('SUBMIT FIRED');   // thêm
    e.preventDefault();
    console.log('preventDefault OK'); // thêm

    const files = fileInput.files;
    if (!files || !files.length) {
        setStatus('Vui lòng chọn ít nhất 1 ảnh.', true);
        return;
    }

    // Gom ảnh vào formData
    const formData = new FormData();
    for (const file of files) {
        formData.append('file', file);
    }

    // ---- Tạo options từ checkbox + textarea ----
    const optionsText = optionsInput.value.trim();

    // Default chỉ dùng trạng thái checkbox
    let finalOptions = {
        shadow: {
            enabled: shadowToggleEl.checked,
        },
    };

    // Nếu user nhập JSON thủ công thì merge đè lên
    if (optionsText) {
        try {
            const manual = JSON.parse(optionsText); // ví dụ {"orientation": "lying"}
            finalOptions = { ...finalOptions, ...manual };
        } catch (err) {
            alert('Options JSON không hợp lệ – đang dùng thiết lập mặc định.');
        }
    }

    // Đẩy options thật vào formData (chỉ 1 lần)
    formData.append('options', JSON.stringify(finalOptions));

    // Gửi request
    setStatus('Đang xử lý, vui lòng đợi...', false);

    try {
        const res = await fetch('/api/v1/process-preview', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            let detail = '';
            try {
                const errJson = await res.json();
                detail = errJson.error || errJson.detail || '';
            } catch (_) {
                // bỏ qua
            }
            throw new Error(detail || `Request failed with status ${res.status}`);
        }

        const data = await res.json();
        // render bằng danh sách file trả về; URL thực sẽ được trích trong renderGallery
        renderGallery(data.files || []);
        setStatus('Xử lý xong – có thể tải từng ảnh ở dưới.', false);
    } catch (err) {
        console.error(err);
        setStatus('Lỗi: ' + err.message, true);
    }
});


// ===== Download all: tải toàn bộ kết quả dưới dạng ZIP =====
if (downloadAllBtn) {
    downloadAllBtn.addEventListener('click', async () => {
        if (!currentResultUrls.length) {
            alert('Chưa có kết quả để tải.');
            return;
        }

        if (typeof JSZip === 'undefined') {
            alert('JSZip chưa được load. Vui lòng thử lại.');
            return;
        }

        try {
            const zip = new JSZip();

            // tải lần lượt từng ảnh và thêm vào zip
            const fetchPromises = currentResultUrls.map(async (url, idx) => {
                const res = await fetch(url);
                if (!res.ok) {
                    console.warn('Không thể tải file:', url);
                    return;
                }
                const blob = await res.blob();
                // đặt tên dạng result_001.png, result_002.png, ...
                const indexStr = String(idx + 1).padStart(3, '0');
                // cố gắng đoán đuôi file từ URL, fallback .png
                let ext = 'png';
                const urlMatch = url.split('?')[0].match(/\.([a-zA-Z0-9]+)$/);
                if (urlMatch && urlMatch[1]) {
                    ext = urlMatch[1];
                }
                const filename = `result_${indexStr}.${ext}`;
                zip.file(filename, blob);
            });

            await Promise.all(fetchPromises);

            const zipBlob = await zip.generateAsync({ type: 'blob' });
            const zipUrl = URL.createObjectURL(zipBlob);

            const a = document.createElement('a');
            a.href = zipUrl;
            a.download = 'results.zip';
            document.body.appendChild(a);
            a.click();
            a.remove();

            URL.revokeObjectURL(zipUrl);
        } catch (err) {
            console.error('Download all error:', err);
            alert('Không thể tạo file ZIP để tải tất cả kết quả.');
        }
    });
}


