from __future__ import annotations

from . import idphoto, images, media, ocr, pdftools, sheets, subtitles, upscale, wordtools

HANDLERS = {
    # 文档
    "pdf-split": pdftools.pdf_split,
    "pdf-merge": pdftools.pdf_merge,
    "pdf-lock": pdftools.pdf_lock,
    "pdf-compress": pdftools.pdf_compress,
    "pdf-to-images": pdftools.pdf_to_images,
    "images-to-pdf": pdftools.images_to_pdf,
    "pdf-extract": pdftools.pdf_extract,
    "pdf-ocr": ocr.ocr_pdf,
    "pdf-pages": pdftools.pdf_pages,
    "pdf-watermark": pdftools.pdf_watermark,
    "docx-to-md": wordtools.docx_to_md,
    "docx-to-html": wordtools.docx_to_html,
    "docx-to-pdf": wordtools.docx_to_pdf,
    "md-to-docx": wordtools.md_to_docx,
    "md-to-pdf": wordtools.md_to_pdf,
    "xlsx-convert": sheets.xlsx_convert,
    # 图片
    "image-convert": images.image_convert,
    "image-compress": images.image_compress,
    "image-resize": images.image_resize,
    "image-rename": images.image_rename,
    "image-bg": images.image_bg,
    "image-idphoto": idphoto.idphoto,
    "image-ocr": ocr.image_ocr,
    "image-favicon": images.image_favicon,
    "image-upscale": upscale.image_upscale,
    # 视频
    "video-convert": media.video_convert,
    "video-compress": media.video_compress,
    "video-trim": media.video_trim,
    "video-crop": media.video_crop,
    "video-concat": media.video_concat,
    "video-to-gif": media.video_to_gif,
    "video-audio": media.video_audio,
    "video-frames": media.video_frames,
    "video-mute": media.video_mute,
    "gif-to-video": media.gif_to_video,
    # 音频
    "audio-convert": media.audio_convert,
    "subtitles": subtitles.subtitles,
}
