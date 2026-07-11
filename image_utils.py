import os
import time
from io import BytesIO
from werkzeug.utils import secure_filename
from PIL import Image

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_SIZE_MB = 5


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_image_content(file_stream):
    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        img = Image.open(file_stream)
        img.verify()
        file_stream.seek(0)
        return True
    except Exception:
        return False


def validate_image_size(file_storage, max_mb=MAX_IMAGE_SIZE_MB):
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    return size <= max_mb * 1024 * 1024


def save_upload(file_storage, upload_folder, prefix=''):
    os.makedirs(upload_folder, exist_ok=True)
    filename = secure_filename(file_storage.filename)
    filename = f"{prefix}{int(time.time())}_{filename}"
    file_path = os.path.join(upload_folder, filename)
    file_storage.save(file_path)
    return f"/static/uploads/{filename}"
