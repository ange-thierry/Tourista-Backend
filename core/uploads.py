"""Image uploads for catalog items, company photos and avatars.

Files are decoded and re-encoded with Pillow, which rejects anything that isn't
a real image and strips metadata (EXIF/GPS) before saving.
"""

import io
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, UnidentifiedImageError
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

ALLOWED_FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}
MAX_DIMENSION = 2400


class ImageUploadView(APIView):
    """POST multipart `file` → `{url}`. Signed-in users only."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'upload'

    def post(self, request):
        upload = request.FILES.get('file')
        if upload is None:
            raise ValidationError({'file': 'Choose an image to upload.'})
        if upload.size > settings.UPLOAD_MAX_BYTES:
            raise ValidationError({'file': f'Images must be under {settings.UPLOAD_MAX_BYTES // (1024 * 1024)} MB.'})
        try:
            image = Image.open(upload)
            image_format = image.format
            image.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValidationError({'file': 'This file is not a supported image.'})
        if image_format not in ALLOWED_FORMATS:
            raise ValidationError({'file': 'Use a JPG, PNG or WebP image.'})

        image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
        if image_format == 'JPEG' and image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        buffer = io.BytesIO()
        save_kwargs = {'quality': 85, 'optimize': True} if image_format in ('JPEG', 'WEBP') else {'optimize': True}
        image.save(buffer, format=image_format, **save_kwargs)

        name = f'uploads/{request.user.pk}/{uuid.uuid4().hex}.{ALLOWED_FORMATS[image_format]}'
        saved = default_storage.save(name, ContentFile(buffer.getvalue()))
        url = request.build_absolute_uri(default_storage.url(saved))
        return Response({'url': url, 'width': image.width, 'height': image.height},
                        status=status.HTTP_201_CREATED)
