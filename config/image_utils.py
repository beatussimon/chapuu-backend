import os
from io import BytesIO
from django.core.files.base import ContentFile
from PIL import Image

def compress_image(image_field, quality=70, max_width=1200):
    """
    Compresses an image from an ImageField and returns a ContentFile.
    """
    if not image_field:
        return None
        
    img = Image.open(image_field)
    
    # Convert RGBA to RGB if necessary (JPEG doesn't support alpha)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
        
    # Resize if too large
    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(float(img.height) * ratio)
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        
    temp_io = BytesIO()
    img.save(temp_io, format="WEBP", quality=quality)
    
    # Extract filename without path
    filename = os.path.basename(image_field.name)
    # Ensure .webp extension for the compressed version
    name_parts = os.path.splitext(filename)
    new_filename = f"{name_parts[0]}_compressed.webp"
    
    return ContentFile(temp_io.getvalue(), name=new_filename)
