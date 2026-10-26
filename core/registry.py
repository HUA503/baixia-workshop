from __future__ import annotations

CATEGORIES = [
    {
        "id": "doc",
        "name": "文档",
        "tagline": "PDF、Word、表格与 OCR",
        "icon": "doc",
    },
    {
        "id": "image",
        "name": "图片",
        "tagline": "批量转换、压缩与抠图",
        "icon": "image",
    },
    {
        "id": "video",
        "name": "视频",
        "tagline": "压缩、剪辑与格式转换",
        "icon": "video",
    },
    {
        "id": "audio",
        "name": "音频",
        "tagline": "音轨提取与格式转换",
        "icon": "audio",
    },
]

IMAGE_ACCEPT = [".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".heif", ".bmp", ".tif", ".tiff", ".gif"]
VIDEO_ACCEPT = [".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts"]
AUDIO_ACCEPT = [".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff"]


def opt(key, label, type="text", default="", **extra):
    data = {"key": key, "label": label, "type": type, "default": default}
    data.update(extra)
    return data


TOOLS = [
    # ── 文档 ─────────────────────────────────────────────
    {
        "id": "pdf-split", "cat": "doc", "name": "PDF 拆分",
        "route": "PDF → PDF×N", "accept": [".pdf"], "multi": False,
        "desc": "按页码范围拆成多个文件，也可以让每一页单独成档。",
        "hint": "页码从 1 开始。用逗号分隔每一组，例如 1-3, 5, 8-10。",
        "options": [
            opt("pages", "页码范围", "text", "1-3, 5", placeholder="1-3, 5, 8-10"),
            opt("each", "每页单独成一个文件", "checkbox", False),
        ],
    },
    {
        "id": "pdf-merge", "cat": "doc", "name": "PDF 合并",
        "route": "PDF×N → PDF", "accept": [".pdf"], "multi": True,
        "desc": "把多份 PDF 按选择顺序合成一份，保留原始画质与文字。",
        "options": [],
    },
    {
        "id": "pdf-lock", "cat": "doc", "name": "PDF 加解密",
        "route": "PDF → 加密 / 解密 PDF", "accept": [".pdf"], "multi": False,
        "desc": "给 PDF 加打开密码，或移除已有密码。",
        "hint": "这是密码加密 / 解密，输出仍是普通 PDF；不是 PDF/A 归档转换。密码只在本次任务内存中使用。",
        "options": [
            opt("mode", "操作", "select", "encrypt", choices=[["encrypt", "加密"], ["decrypt", "解密"]]),
            opt("password", "密码", "text", "", placeholder="输入密码"),
        ],
    },
    {
        "id": "pdf-compress", "cat": "doc", "name": "PDF 压缩",
        "route": "PDF → PDF", "accept": [".pdf"], "multi": False,
        "desc": "默认无损清理；图像优化只重采样 PDF 内嵌照片，文字与矢量保持不变。",
        "hint": "平衡/强模式会压缩内嵌图片但保留文字层；仅极端模式会整页转图片。",
        "warning": "默认和图像优化都保留可选择、可搜索的文字；只有「极端 · 整页图像化」会丢失文字层。",
        "options": [
            opt("level", "压缩强度", "select", "light", choices=[
                ["light", "无损清理 · 默认（保留文字）"],
                ["balanced", "图像优化 · 平衡（文字可搜索）"],
                ["strong", "图像优化 · 强（文字可搜索）"],
                ["raster", "极端 · 整页图像化（文字不可搜索）"],
            ]),
        ],
    },
    {
        "id": "pdf-to-images", "cat": "doc", "name": "PDF 转图片",
        "route": "PDF → PNG / JPG", "accept": [".pdf"], "multi": False,
        "desc": "逐页导出为高清图片，适合做封面、预览图或归档。",
        "options": [
            opt("format", "图片格式", "select", "png", choices=[["png", "PNG"], ["jpg", "JPG"]]),
            opt("dpi", "清晰度 (DPI)", "number", 150, min=72, max=400, step=10),
            opt("pages", "页码范围", "text", "", placeholder="留空 = 全部页"),
        ],
    },
    {
        "id": "images-to-pdf", "cat": "doc", "name": "图片转 PDF",
        "route": "图片×N → PDF", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "把多张图片按顺序合成一份 PDF，可自动适配 A4。",
        "options": [
            opt("page_size", "页面尺寸", "select", "a4", choices=[["a4", "A4（居中留白）"], ["auto", "跟随图片尺寸"]]),
            opt("margin", "页边距 (mm)", "number", 12, min=0, max=40, step=1),
        ],
    },
    {
        "id": "pdf-extract", "cat": "doc", "name": "PDF 转 Word / 文本",
        "route": "PDF → DOCX / MD / TXT / HTML", "accept": [".pdf"], "multi": False,
        "desc": "提取文字、标题和表格，转成可编辑文档或适合喂给 AI 的 Markdown。",
        "hint": "扫描件没有文字层时，请改用「PDF OCR 识别」。",
        "options": [
            opt("format", "输出格式", "select", "docx", choices=[
                ["docx", "Word (.docx)"], ["md", "Markdown (.md)"], ["txt", "纯文本 (.txt)"], ["html", "网页 (.html)"],
            ]),
            opt("tables", "识别表格", "checkbox", True),
            opt("page_markers", "保留页码分隔", "checkbox", False),
        ],
    },
    {
        "id": "pdf-ocr", "cat": "doc", "name": "PDF OCR 识别",
        "route": "扫描 PDF → 文字 / 可搜索 PDF", "accept": [".pdf"], "multi": False,
        "desc": "把扫描件里的中英文抠出来，生成 TXT、Word 或带隐藏文字层的 PDF。",
        "hint": "页数多时耗时较长；可先填写页码范围测试效果，输出只包含所选页。",
        "options": [
            opt("format", "输出格式", "select", "txt", choices=[
                ["txt", "纯文本 (.txt)"], ["docx", "Word (.docx)"], ["searchable", "可搜索 PDF"],
            ]),
            opt("pages", "页码范围", "text", "", placeholder="留空 = 全部页"),
            opt("dpi", "识别清晰度 (DPI)", "number", 200, min=120, max=300, step=10),
        ],
    },
    {
        "id": "pdf-pages", "cat": "doc", "name": "PDF 页面管理",
        "route": "PDF → 拖拽重排 / 旋转 / 删页", "accept": [".pdf"], "multi": False,
        "desc": "把 PDF 变成缩略图画廊，拖拽调整顺序、旋转或删除页面，再导出新 PDF。",
        "hint": "先在缩略图里调整，再开始处理；文字、图片和矢量内容保持不变。",
        "gallery": True,
        "options": [],
    },
    {
        "id": "pdf-watermark", "cat": "doc", "name": "PDF 水印",
        "route": "PDF → 带文字水印 PDF", "accept": [".pdf"], "multi": False,
        "desc": "给合同、证件复印件加平铺或居中文字水印，适合标注用途与防滥用。",
        "hint": "文字在本地渲染，不会上传；默认平铺倾斜水印，可调透明度、角度和颜色。",
        "options": [
            opt("text", "水印文字", "text", "仅供内部使用", placeholder="例如：仅供 XX 认证使用"),
            opt("opacity", "透明度 (%)", "range", 18, min=5, max=100, step=1),
            opt("font_size", "字号", "range", 36, min=8, max=160, step=2),
            opt("angle", "角度", "range", 30, min=-90, max=90, step=5),
            opt("color", "颜色", "select", "gray", choices=[
                ["gray", "灰色"], ["red", "红色"], ["blue", "蓝色"], ["black", "黑色"], ["green", "绿色"],
            ]),
            opt("tile", "平铺整页", "checkbox", True),
            opt("pages", "页码范围", "text", "", placeholder="留空 = 全部页"),
        ],
    },
    {
        "id": "docx-to-md", "cat": "doc", "name": "Word 转 Markdown",
        "route": "DOCX → MD", "accept": [".docx"], "multi": False,
        "desc": "保留标题、列表、粗体、链接和表格，输出干净的 Markdown 给 AI 使用。",
        "hint": "勾选「导出图片」时，文字与图片会打包成一个 ZIP。",
        "options": [
            opt("tables", "转换表格", "checkbox", True),
            opt("images", "导出图片", "checkbox", False),
        ],
    },
    {
        "id": "docx-to-html", "cat": "doc", "name": "Word 转网页",
        "route": "DOCX → HTML", "accept": [".docx"], "multi": False,
        "desc": "生成单文件网页，图片自动内嵌，可直接分享或放进网站。",
        "options": [],
    },
    {
        "id": "docx-to-pdf", "cat": "doc", "name": "Word 转 PDF",
        "route": "DOCX → PDF", "accept": [".docx"], "multi": False,
        "desc": "在本地排版成 PDF，保留标题、表格与图片，无需 Office。",
        "options": [],
    },
    {
        "id": "md-to-docx", "cat": "doc", "name": "Markdown 转 Word",
        "route": "MD → DOCX", "accept": [".md", ".markdown", ".txt"], "multi": False,
        "desc": "把 Markdown 变成可编辑的 Word 文档，支持标题、列表、代码块与表格。",
        "options": [],
    },
    {
        "id": "md-to-pdf", "cat": "doc", "name": "Markdown 转 PDF",
        "route": "MD → PDF", "accept": [".md", ".markdown", ".txt"], "multi": False,
        "desc": "排版成干净的 PDF，适合打印、存档或交付。",
        "options": [],
    },
    {
        "id": "xlsx-convert", "cat": "doc", "name": "表格转换",
        "route": "XLSX / CSV → CSV / MD / JSON / XLSX", "accept": [".xlsx", ".xlsm", ".csv"], "multi": False,
        "desc": "把表格转成 CSV、Markdown 表格、JSON，或反向生成 Excel。",
        "hint": "「全部工作表」在导出 CSV 时会打包为 ZIP。",
        "options": [
            opt("format", "输出格式", "select", "md", choices=[
                ["md", "Markdown 表格"], ["csv", "CSV"], ["json", "JSON"], ["xlsx", "Excel (.xlsx)"],
            ]),
            opt("sheet", "工作表", "select", "first", choices=[["first", "仅第一个"], ["all", "全部工作表"]]),
            opt("header", "首行作为表头", "checkbox", True),
        ],
    },
    # ── 图片 ─────────────────────────────────────────────
    {
        "id": "image-convert", "cat": "image", "name": "批量格式转换",
        "route": "JPG · PNG · WebP · AVIF · HEIC", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "手机 HEIC、网页 AVIF/WebP 一键转成通用格式，也能反向压缩输出。",
        "options": [
            opt("format", "输出格式", "select", "jpg", choices=[
                ["jpg", "JPG"], ["png", "PNG"], ["webp", "WebP"], ["avif", "AVIF"], ["heic", "HEIC"], ["tiff", "TIFF"],
            ]),
            opt("quality", "质量", "range", 85, min=40, max=100, step=1),
            opt("max_width", "最大宽度 (px)", "number", 0, min=0, max=12000, step=100, hint="0 = 保持原尺寸"),
            opt("strip", "清除 EXIF / 定位信息", "checkbox", True),
        ],
    },
    {
        "id": "image-compress", "cat": "image", "name": "图片压缩",
        "route": "图片×N → 更小的图片", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "降低质量与分辨率，批量瘦身，也可以把每张图压到指定 KB。",
        "hint": "填「目标大小」后会逐张搜索质量与尺寸；填 0 则使用质量滑块。",
        "options": [
            opt("target_kb", "每张目标大小 (KB)", "number", 0, min=0, max=102400, step=10, hint="0 = 质量滑块；例如 200。PNG 等会转 WebP 以控制体积"),
            opt("quality", "质量", "range", 72, min=20, max=95, step=1, hint="PNG 为无损格式，主要靠限制最长边来减小体积"),
            opt("max_dim", "最长边不超过 (px)", "number", 1600, min=0, max=12000, step=100),
            opt("format", "输出格式", "select", "keep", choices=[
                ["keep", "保持原格式"], ["jpg", "JPG（最小）"], ["webp", "WebP"], ["avif", "AVIF"],
            ]),
        ],
    },
    {
        "id": "image-resize", "cat": "image", "name": "批量缩放",
        "route": "图片×N → 指定尺寸", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "统一像素尺寸，做自媒体封面、商品图或整理相册都很省事。",
        "options": [
            opt("width", "目标宽度 (px)", "number", 1080, min=0, max=20000, step=10, hint="0 = 按比例自动"),
            opt("height", "目标高度 (px)", "number", 0, min=0, max=20000, step=10, hint="0 = 按比例自动"),
            opt("mode", "缩放方式", "select", "contain", choices=[
                ["contain", "等比适应"], ["cover", "裁剪填满"], ["stretch", "强制拉伸"],
            ]),
        ],
    },
    {
        "id": "image-rename", "cat": "image", "name": "批量重命名",
        "route": "图片×N → 新文件名", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "按统一规则改名，支持序号、原名、日期占位符。",
        "hint": "占位符：{name} 原名 · {n} 序号 · {date} 日期 · {ext} 扩展名。输出为新文件名副本，不改动原文件。",
        "options": [
            opt("pattern", "命名规则", "text", "{name}_{n:02}", placeholder="{name}_{n:02}"),
            opt("start", "起始序号", "number", 1, min=0, max=99999, step=1),
            opt("zip", "打包为 ZIP", "checkbox", True),
        ],
    },
    {
        "id": "image-bg", "cat": "image", "name": "一键去背景",
        "route": "图片×N → 透明 PNG", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "本地 AI 智能抠图，发丝与复杂背景也能处理；输出透明 PNG。",
        "hint": "默认使用 AI 抠图；纯色背景可切换颜色容差模式，AI 不可用时也会自动降级。",
        "options": [
            opt("method", "抠图方式", "select", "ai", choices=[
                ["ai", "AI 智能抠图（推荐）"],
                ["color", "颜色容差（纯色背景）"],
            ]),
            opt("tolerance", "颜色容差", "range", 26, min=5, max=80, step=1, hint="仅颜色容差模式使用"),
            opt("feather", "边缘羽化", "range", 1, min=0, max=6, step=1),
        ],
    },
    {
        "id": "image-idphoto", "cat": "image", "name": "证件照制作",
        "route": "图片 → 一寸 / 二寸 / 护照", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "自动识别人脸并按证件照构图，裁剪成标准毫米尺寸，可换白底、蓝底或红底。",
        "hint": "换背景默认使用 AI 抠图；识别失败时会按构图中心裁剪。",
        "options": [
            opt("size", "证件照规格", "select", "one", choices=[
                ["one", "一寸 25×35 mm"], ["small_one", "小一寸 22×32 mm"], ["big_one", "大一寸 33×48 mm"],
                ["two", "二寸 35×49 mm"], ["small_two", "小二寸 35×45 mm"], ["big_two", "大二寸 35×53 mm"],
                ["passport", "中国护照 33×48 mm"], ["visa_us", "美国签证 51×51 mm"],
            ]),
            opt("bg", "背景", "select", "keep", choices=[
                ["keep", "保持原背景"], ["white", "白底"], ["blue", "蓝底"], ["red", "红底"], ["gray", "灰底"],
            ]),
            opt("dpi", "输出 DPI", "number", 300, min=200, max=600, step=50),
            opt("auto_face", "自动识别人脸并居中", "checkbox", True),
            opt("enhance", "轻微提亮与增强", "checkbox", True),
            opt("ai_cutout", "AI 智能换背景", "checkbox", True),
            opt("tolerance", "颜色容差（AI 不可用时）", "range", 30, min=5, max=80, step=1),
        ],
    },
    {
        "id": "image-ocr", "cat": "image", "name": "图片 OCR",
        "route": "图片×N → TXT / DOCX", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "识别截图、照片里的中英文，支持多张合并且按顺序输出。",
        "options": [
            opt("format", "输出格式", "select", "txt", choices=[["txt", "纯文本 (.txt)"], ["docx", "Word (.docx)"]]),
            opt("merge", "合并成一个文件", "checkbox", True),
        ],
    },
    {
        "id": "image-favicon", "cat": "image", "name": "生成网站图标",
        "route": "图片 → ICO", "accept": IMAGE_ACCEPT, "multi": False,
        "desc": "一次生成多尺寸 favicon.ico，直接放进网站根目录即可。",
        "options": [
            opt("sizes", "包含尺寸", "text", "16,32,48,64,128,256", placeholder="16,32,48,64,128,256"),
        ],
    },
    {
        "id": "image-upscale", "cat": "image", "name": "AI 高清放大",
        "route": "图片 → 2× / 3× / 4× 高清图", "accept": IMAGE_ACCEPT, "multi": True,
        "desc": "用本地 Real-ESRGAN 模型补细节放大，适合截图、头像、商品图和低清素材。",
        "hint": "AI 模式完全本地运行；超大图会受输出尺寸保护限制。含小字或文档截图时建议改用快速模式，避免 AI 重绘细节。",
        "options": [
            opt("scale", "放大倍率", "select", "2", choices=[["2", "2×"], ["3", "3×"], ["4", "4×"]]),
            opt("method", "放大方式", "select", "ai", choices=[["ai", "AI 超分（Real-ESRGAN）"], ["fast", "快速插值 + 锐化"]]),
            opt("format", "输出格式", "select", "auto", choices=[["auto", "自动"], ["png", "PNG"], ["jpg", "JPG"], ["webp", "WebP"]]),
        ],
    },
    # ── 视频 ─────────────────────────────────────────────
    {
        "id": "video-convert", "cat": "video", "name": "视频格式转换",
        "route": "MP4 · MKV · MOV · WebM", "accept": VIDEO_ACCEPT, "multi": False,
        "desc": "转换成通用视频格式，可同时调整画质和分辨率。",
        "options": [
            opt("format", "输出格式", "select", "mp4", choices=[
                ["mp4", "MP4 (H.264)"], ["webm", "WebM (VP9)"], ["mkv", "MKV"], ["mov", "MOV"],
            ]),
            opt("crf", "画质（数值越小越清晰）", "range", 23, min=16, max=35, step=1),
            opt("resolution", "分辨率", "select", "keep", choices=[
                ["keep", "保持原分辨率"], ["1080", "最高 1080p"], ["720", "最高 720p"], ["480", "最高 480p"],
            ]),
        ],
    },
    {
        "id": "video-compress", "cat": "video", "name": "视频压缩",
        "route": "视频 → 更小的 MP4", "accept": VIDEO_ACCEPT, "multi": False,
        "desc": "用三档预设快速瘦身，或按目标体积上限压缩；内容简单时输出会更小。",
        "hint": "目标为容量上限（≤），不会填充；滑杆上限跟随原视频，目标必须大于 0 且小于原文件。内容简单时会输出更小的高质量文件。",
        "options": [
            opt("level", "压缩强度", "select", "standard", choices=[
                ["light", "轻度 · 画质优先"], ["standard", "推荐 · 体积均衡"], ["strong", "强力 · 微信秒传"],
            ], enable_if={"key": "custom_size", "equals": False}),
            opt("custom_size", "按目标上限压缩", "checkbox", False),
            opt("target_mb", "目标上限 (MB)", "range", 10, min=0, max=102400, step=0.1,
                hint="滑杆上限自动跟随原视频大小；目标必须小于原文件",
                enable_if={"key": "custom_size", "equals": True}),
            opt("resolution", "分辨率", "select", "auto", choices=[
                ["auto", "自动（按目标大小选择）"], ["keep", "保持原分辨率"],
                ["1080", "1080p"], ["720", "720p"], ["480", "480p"],
            ]),
        ],
    },
    {
        "id": "video-trim", "cat": "video", "name": "视频裁剪",
        "route": "视频 → 片段", "accept": VIDEO_ACCEPT, "multi": False,
        "desc": "掐头去尾，只留下想要的片段；快速模式几乎瞬间完成。",
        "hint": "时间可写 00:00:10、1:30 或直接写秒数。",
        "options": [
            opt("start", "开始时间", "text", "00:00:00", placeholder="00:00:00"),
            opt("end", "结束时间", "text", "00:00:10", placeholder="00:00:10"),
            opt("copy", "快速模式（不重新编码）", "checkbox", True),
        ],
    },
    {
        "id": "video-crop", "cat": "video", "name": "视频画面裁剪",
        "route": "视频 → 改画幅 / 去黑边", "accept": VIDEO_ACCEPT, "multi": False,
        "desc": "按 16:9、9:16、1:1 等比例裁剪画面，适合横竖屏转换和去黑边。",
        "hint": "缩放比例越小裁得越多；位置决定保留画面的上方、下方或中心。",
        "options": [
            opt("ratio", "画面比例", "select", "original", choices=[
                ["original", "保持原比例"], ["16:9", "16:9 横屏"], ["9:16", "9:16 竖屏"],
                ["1:1", "1:1 方形"], ["4:3", "4:3"], ["3:4", "3:4"], ["custom", "自定义"],
            ]),
            opt("ratio_w", "自定义宽比", "number", 16, min=1, max=100, step=1, enable_if={"key": "ratio", "equals": "custom"}),
            opt("ratio_h", "自定义高比", "number", 9, min=1, max=100, step=1, enable_if={"key": "ratio", "equals": "custom"}),
            opt("zoom", "保留范围 (%)", "range", 100, min=30, max=100, step=1),
            opt("anchor", "裁剪位置", "select", "center", choices=[
                ["center", "居中"], ["top", "靠上"], ["bottom", "靠下"], ["left", "靠左"], ["right", "靠右"],
            ]),
        ],
    },
    {
        "id": "video-concat", "cat": "video", "name": "视频拼接",
        "route": "视频×N → MP4", "accept": VIDEO_ACCEPT, "multi": True,
        "desc": "把多段视频按顺序接成一段，自动统一分辨率和帧率。",
        "hint": "文件较多或分辨率差异大时，处理时间会更长。",
        "options": [],
    },
    {
        "id": "video-to-gif", "cat": "video", "name": "视频转 GIF",
        "route": "视频 → GIF", "accept": VIDEO_ACCEPT, "multi": False,
        "desc": "截取任意几秒做成高质量 GIF 表情包，自动生成调色板。",
        "options": [
            opt("start", "开始时间", "text", "0", placeholder="0 或 00:00:03"),
            opt("duration", "时长（秒）", "number", 3, min=0.5, max=30, step=0.5),
            opt("fps", "帧率", "number", 12, min=5, max=30, step=1),
            opt("width", "宽度 (px)", "number", 640, min=120, max=1280, step=20),
        ],
    },
    {
        "id": "video-audio", "cat": "video", "name": "提取音频",
        "route": "视频 → MP3 / WAV / M4A / FLAC", "accept": VIDEO_ACCEPT, "multi": False,
        "desc": "把视频里的声音单独提取出来，做播客、铃声或背景音乐。",
        "options": [
            opt("format", "音频格式", "select", "mp3", choices=[
                ["mp3", "MP3"], ["m4a", "M4A (AAC)"], ["wav", "WAV"], ["flac", "FLAC"],
            ]),
            opt("bitrate", "码率", "select", "192", choices=[["128", "128 kbps"], ["192", "192 kbps"], ["320", "320 kbps"]]),
        ],
    },
    {
        "id": "video-frames", "cat": "video", "name": "视频截帧",
        "route": "视频 → 图片序列", "accept": VIDEO_ACCEPT, "multi": False,
        "desc": "按固定间隔抽帧，用来做封面、分镜或素材图。",
        "options": [
            opt("interval", "每隔几秒抽一帧", "number", 1, min=0.2, max=60, step=0.2),
            opt("format", "图片格式", "select", "jpg", choices=[["jpg", "JPG"], ["png", "PNG"]]),
        ],
    },
    {
        "id": "video-mute", "cat": "video", "name": "视频静音",
        "route": "视频 → 无声视频", "accept": VIDEO_ACCEPT, "multi": False,
        "desc": "移除音轨，文件更小，适合做循环背景或无声素材。",
        "options": [],
    },
    {
        "id": "gif-to-video", "cat": "video", "name": "GIF 转视频",
        "route": "GIF → MP4 / WebM", "accept": [".gif"], "multi": False,
        "desc": "把表情包或动画 GIF 转成视频，方便剪辑和发布。",
        "options": [
            opt("format", "输出格式", "select", "mp4", choices=[["mp4", "MP4"], ["webm", "WebM"]]),
        ],
    },
    # ── 音频 ─────────────────────────────────────────────
    {
        "id": "subtitles", "cat": "audio", "name": "音视频转字幕",
        "route": "音频 / 视频 → SRT 字幕", "accept": VIDEO_ACCEPT + AUDIO_ACCEPT, "multi": False,
        "desc": "用本地 Whisper 模型把讲话转成带时间轴的字幕，完全离线，适合会议、网课和短视频。",
        "hint": "首次使用前请运行 install.bat 安装依赖；模型已内置，识别全程不上传。",
        "options": [
            opt("format", "输出格式", "select", "srt", choices=[
                ["srt", "SRT 字幕"], ["txt", "纯文本"], ["both", "SRT + 文本"],
            ]),
            opt("language", "语言", "select", "auto", choices=[
                ["auto", "自动识别"], ["zh", "中文"], ["en", "英语"], ["ja", "日语"],
                ["ko", "韩语"], ["fr", "法语"], ["de", "德语"], ["es", "西班牙语"], ["ru", "俄语"],
            ]),
            opt("vad", "跳过静音片段", "checkbox", True),
        ],
    },
    {
        "id": "audio-convert", "cat": "audio", "name": "音频格式转换",
        "route": "MP3 · WAV · FLAC · M4A · AAC", "accept": AUDIO_ACCEPT, "multi": False,
        "desc": "常见音频格式互转，可控制码率，兼顾音质与体积。",
        "options": [
            opt("format", "输出格式", "select", "mp3", choices=[
                ["mp3", "MP3"], ["wav", "WAV"], ["flac", "FLAC"], ["m4a", "M4A"], ["aac", "AAC"],
            ]),
            opt("bitrate", "码率", "select", "192", choices=[["128", "128 kbps"], ["192", "192 kbps"], ["320", "320 kbps"]]),
            opt("sample_rate", "采样率", "select", "keep", choices=[
                ["keep", "保持原样"], ["44100", "44.1 kHz"], ["48000", "48 kHz"],
            ]),
        ],
    },
]


TOOL_MAP = {t["id"]: t for t in TOOLS}
CATEGORY_MAP = {c["id"]: c for c in CATEGORIES}


def public_tools() -> list[dict]:
    return TOOLS
