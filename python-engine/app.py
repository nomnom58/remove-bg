import io
import json
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import Response, JSONResponse
from rembg import remove
from PIL import Image, ImageFilter

app = FastAPI()

def process_image_bytes(input_bytes: bytes, options: dict) -> bytes:
    """
    Xử lý 1 ảnh:
    - Giới hạn kích thước
    - Remove background (rembg)
    - Làm mượt viền
    - Tạo shadow mềm
    - Background: xám nhạt
    - Trả về PNG bytes
    """
    # 1. Đọc ảnh & giới hạn kích thước
    im = Image.open(io.BytesIO(input_bytes)).convert("RGBA")

    max_side = 1600
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)

    # 2. Remove background bằng rembg (nền trong suốt)
    fg = remove(im)
    fg = fg.convert("RGBA")

    # 3. Lấy alpha mask & làm mịn viền
    alpha = fg.split()[3]
    alpha = alpha.filter(ImageFilter.GaussianBlur(radius=1.0))

    w, h = fg.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # 3.1 Ước lượng object đang "đứng" hay "nằm"
    orientation = "standing"  # mặc định

    bbox = alpha.getbbox()
    if bbox is not None:
        left, upper, right, lower = bbox
        obj_w = right - left
        obj_h = lower - upper

        # Tỷ lệ rộng/cao của object
        aspect = obj_w / float(obj_h + 1e-6)

        # Lấy dải mỏng ở đáy để xem "chân tiếp đất"
        strip_height = min(10, obj_h)
        bottom_box = alpha.crop((left, lower - strip_height, right, lower))
        bottom_data = list(bottom_box.getdata())
        contact_pixels = sum(1 for v in bottom_data if v > 0)
        contact_ratio = contact_pixels / float(obj_w * strip_height + 1e-6)

        # Heuristic: dẹt + chạm tiếp đất đủ rộng -> nằm
        # nới điều kiện để dễ nhận "lying" hơn
        if aspect > 1.2 and contact_ratio > 0.15:
            orientation = "lying"

    # 4. Shadow
    shadow_cfg = options.get("shadow", {})

    # Mặc định: cho phép bóng
    shadow_enabled = shadow_cfg.get("enabled", True)

    # Nếu user không chỉ định enabled mà object nằm (lying) → auto tắt bóng
    if "enabled" not in shadow_cfg and orientation == "lying":
        shadow_enabled = False

    # orientation: "standing" (đứng) hoặc "lying" (nằm)
    # cho phép override từ options nếu sau này cần
    orientation = options.get("orientation", orientation)

    if shadow_enabled:
        # Cấu hình gốc
        opacity = float(shadow_cfg.get("intensity", 0.20))  # 0–1
        base_blur = int(shadow_cfg.get("blur", 30))
        base_offset_x = int(shadow_cfg.get("offset_x", 20))
        base_offset_y = int(shadow_cfg.get("offset_y", 24))

        # Tuỳ chỉnh theo orientation
        if orientation == "lying":
            # Đồ nằm: bóng dẹt, gần object hơn, mờ nhẹ
            blur_radius = int(base_blur * 0.7)
            offset_x = int(base_offset_x * 0.5)
            offset_y = int(base_offset_y * 0.5)
        else:
            # Mặc định / đứng / unknown
            blur_radius = int(base_blur * 1.1)
            offset_x = int(base_offset_x * 1.2)
            offset_y = int(base_offset_y * 1.2)

        # Giảm độ đậm bóng cho đồ "nằm" (cho nhẹ hơn)
        if orientation == "lying":
            opacity *= 0.7  # bóng nhạt hơn một chút
        else:
            opacity *= 1.0  # giữ nguyên cho standing


        # Alpha cho bóng (nhạt hơn object)
        shadow_alpha = alpha.point(lambda v: int(v * opacity))
        shadow_alpha = shadow_alpha.filter(
            ImageFilter.GaussianBlur(radius=blur_radius)
        )

        # Vẽ bóng
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        out.paste(shadow, (offset_x, offset_y), mask=shadow_alpha)

    # 5. Dán object lên trên shadow (hoặc lên nền trắng/xám sau này)
    out = Image.alpha_composite(
        out,
        Image.merge("RGBA", (*fg.split()[:3], alpha)),
    )

    # 6. Xuất PNG bytes
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()




@app.post("/process")
async def process(
    file: UploadFile = File(...),
    options: Optional[str] = Form(None),
):
    """
    Endpoint cho Node API:
    - Nhận 1 file ảnh + options (JSON string)
    - Trả về PNG bytes (content-type image/png)
    """
    try:
        raw_bytes = await file.read()

        opts: dict = {}
        if options:
            try:
                opts = json.loads(options)
            except json.JSONDecodeError:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid JSON in options"},
                )

        output_bytes = process_image_bytes(raw_bytes, opts)

        # đặt tên file output
        original_name = file.filename or "image"
        if "." in original_name:
            base = original_name.rsplit(".", 1)[0]
        else:
            base = original_name
        output_name = f"{base}_result.png"

        headers = {
            "X-Output-Filename": output_name
        }

        return Response(content=output_bytes, media_type="image/png", headers=headers)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(e)},
        )
