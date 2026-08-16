"""auth-service ve user-service icin PDF dokumantasyonu uretir.

Calistirma (education conda ortami):
    python docs/generate_service_docs.py

Cikti: docs/auth-service.pdf, docs/user-service.pdf

Tablo semalari ELLE YAZILMADI, canli veritabanindan alinan cikti buraya
gomuldu (bkz. TABLES). Semayi degistirirsen buradaki listeyi de guncelle;
aksi halde dokuman sessizce bayatlar.
"""

from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Renkler: mobil uygulamanin paletiyle ayni -------------------------------
INK = colors.HexColor("#262135")      # baslik/vurgu (Figma "primary")
ACCENT = colors.HexColor("#0F6E78")
MUTED = colors.HexColor("#6B7684")
LINE = colors.HexColor("#D9D9D9")
BG_SOFT = colors.HexColor("#F4F3F7")
WARN = colors.HexColor("#B3261E")


def _register_fonts() -> tuple[str, str, str]:
    """Turkce karakterler icin TTF gerekiyor.

    Reportlab'in gomulu Helvetica'si Latin-1; 'ş', 'ğ', 'İ' gibi harfleri
    basamiyor. Windows'un DejaVu/Arial dosyalari varsa onlar kullaniliyor,
    yoksa Helvetica'ya dusuluyor ve metin bozuk gorunebilir.
    """
    candidates = [
        ("DejaVu", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf"),
        ("Arial", "arial.ttf", "arialbd.ttf", "ariali.ttf"),
    ]
    search = [
        r"C:\Windows\Fonts",
        "/usr/share/fonts/truetype/dejavu",
    ]
    for name, reg, bold, ital in candidates:
        for folder in search:
            p_reg = os.path.join(folder, reg)
            p_bold = os.path.join(folder, bold)
            if os.path.exists(p_reg) and os.path.exists(p_bold):
                pdfmetrics.registerFont(TTFont(name, p_reg))
                pdfmetrics.registerFont(TTFont(name + "-Bold", p_bold))
                p_ital = os.path.join(folder, ital)
                if os.path.exists(p_ital):
                    pdfmetrics.registerFont(TTFont(name + "-Italic", p_ital))
                    return name, name + "-Bold", name + "-Italic"
                return name, name + "-Bold", name + "-Bold"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


FONT, FONT_B, FONT_I = _register_fonts()


# --- Stiller -----------------------------------------------------------------

_base = getSampleStyleSheet()

S_TITLE = ParagraphStyle("t", parent=_base["Title"], fontName=FONT_B,
                         fontSize=24, leading=29, textColor=INK, spaceAfter=2)
S_SUB = ParagraphStyle("s", parent=_base["Normal"], fontName=FONT,
                       fontSize=11, leading=15, textColor=MUTED,
                       alignment=TA_CENTER, spaceAfter=14)
S_H1 = ParagraphStyle("h1", parent=_base["Heading1"], fontName=FONT_B,
                      fontSize=15, leading=19, textColor=INK,
                      spaceBefore=14, spaceAfter=7)
S_H2 = ParagraphStyle("h2", parent=_base["Heading2"], fontName=FONT_B,
                      fontSize=11.5, leading=15, textColor=ACCENT,
                      spaceBefore=10, spaceAfter=4)
S_BODY = ParagraphStyle("b", parent=_base["Normal"], fontName=FONT,
                        fontSize=9.5, leading=14, textColor=colors.black,
                        spaceAfter=5)
S_SMALL = ParagraphStyle("sm", parent=S_BODY, fontSize=8.5, leading=12,
                         textColor=MUTED)
S_CELL = ParagraphStyle("c", parent=S_BODY, fontSize=8, leading=10.5,
                        spaceAfter=0)
S_CELL_B = ParagraphStyle("cb", parent=S_CELL, fontName=FONT_B)
# `borderPadding` cerceveyi metnin DISINA cizer — yukari dogru da. Bu, onceki
# flowable'in alanina tasar ve diyagramlarin uzerine biner. `spaceBefore`
# padding'den buyuk olmak zorunda.
S_NOTE = ParagraphStyle("n", parent=S_BODY, fontSize=9, leading=13,
                        leftIndent=8, borderPadding=6,
                        spaceBefore=10, spaceAfter=8,
                        backColor=BG_SOFT, borderColor=LINE, borderWidth=0.6)


def body(text: str) -> Paragraph:
    return Paragraph(text, S_BODY)


def note(text: str) -> Paragraph:
    return Paragraph(text, S_NOTE)


def code(text: str) -> Paragraph:
    return Paragraph(f'<font face="Courier" size="8.5">{text}</font>', S_BODY)


# --- Tablo semasi cizimi -----------------------------------------------------

def schema_table(title: str, subtitle: str, rows: list[tuple[str, str, str]]) -> KeepTogether:
    """Bir veritabani tablosunu kolon listesi olarak cizer.

    `rows`: (kolon, tip, aciklama). Aciklamasi 'PK'/'FK' ile baslayan satirlar
    vurgulaniyor — okuyan kisi anahtarlari taramadan gorebilsin.
    """
    data = [[Paragraph("Kolon", S_CELL_B),
             Paragraph("Tip", S_CELL_B),
             Paragraph("Aciklama", S_CELL_B)]]
    highlight: list[int] = []
    for i, (col, typ, desc) in enumerate(rows, start=1):
        if desc.startswith(("PK", "FK", "UNIQUE")):
            highlight.append(i)
        data.append([
            Paragraph(f'<font face="Courier">{col}</font>', S_CELL),
            Paragraph(typ, S_CELL),
            Paragraph(desc, S_CELL),
        ])

    tbl = Table(data, colWidths=[42 * mm, 30 * mm, 96 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in highlight:
        style.append(("BACKGROUND", (0, i), (-1, i), BG_SOFT))
    tbl.setStyle(TableStyle(style))

    parts = [Paragraph(f'<font face="Courier">{title}</font>', S_H2)]
    if subtitle:
        parts.append(Paragraph(subtitle, S_SMALL))
    parts.append(tbl)
    parts.append(Spacer(1, 7))
    return KeepTogether(parts)


class FlowDiagram(Flowable):
    """Adimlari kutu-ok zinciri olarak cizen basit akis diyagrami.

    Metin olarak numarali liste yazmak da mumkundu; kutu-ok bicimi
    "hangi bilesen ne yapiyor" sorusunu tek bakista cevapladigi icin secildi.
    """

    def __init__(self, steps: list[tuple[str, str]], width: float = 168 * mm):
        super().__init__()
        self.steps = steps
        self.width = width
        self.box_h = 13 * mm
        self.gap = 4.5 * mm
        # Sondaki bosluk: bir sonraki flowable (cogunlukla not kutusu) son
        # kutuya yapismasin.
        self.pad_bottom = 4 * mm
        self.height = (len(steps) * self.box_h
                       + (len(steps) - 1) * self.gap
                       + self.pad_bottom)

    def draw(self):
        c = self.canv
        y = self.height - self.pad_bottom
        for i, (actor, action) in enumerate(self.steps):
            y -= self.box_h
            c.setFillColor(BG_SOFT)
            c.setStrokeColor(LINE)
            c.setLineWidth(0.6)
            c.roundRect(0, y, self.width, self.box_h, 2 * mm, stroke=1, fill=1)

            c.setFillColor(INK)
            c.setFont(FONT_B, 8.5)
            c.drawString(4 * mm, y + self.box_h - 5.4 * mm, actor)

            c.setFillColor(colors.black)
            c.setFont(FONT, 8)
            c.drawString(4 * mm, y + 3.2 * mm, action)

            if i < len(self.steps) - 1:
                c.setStrokeColor(ACCENT)
                c.setLineWidth(1.1)
                mid = self.width / 2
                c.line(mid, y, mid, y - self.gap)
                c.setFillColor(ACCENT)
                p = c.beginPath()
                p.moveTo(mid, y - self.gap)
                p.lineTo(mid - 1.6 * mm, y - self.gap + 2.1 * mm)
                p.lineTo(mid + 1.6 * mm, y - self.gap + 2.1 * mm)
                p.close()
                c.drawPath(p, fill=1, stroke=0)
                y -= self.gap


class Relations(Flowable):
    """Tablolar arasi iliskiyi kutu + ok olarak cizer (basit ER diyagrami)."""

    def __init__(self, root: str, children: list[tuple[str, str]],
                 detached: list[tuple[str, str]], width: float = 168 * mm):
        super().__init__()
        self.root = root
        self.children = children
        self.detached = detached
        self.width = width
        self.height = 40 * mm + len(detached) * 15 * mm

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        bw, bh = 46 * mm, 11 * mm

        # Kok tablo — ustte ortada
        rx, ry = (w - bw) / 2, h - bh
        c.setFillColor(INK); c.setStrokeColor(INK)
        c.roundRect(rx, ry, bw, bh, 2 * mm, stroke=1, fill=1)
        c.setFillColor(colors.white); c.setFont(FONT_B, 9)
        c.drawCentredString(w / 2, ry + 4 * mm, self.root)

        # Cocuk tablolar — altta yan yana
        n = len(self.children)
        cy = ry - 22 * mm
        for i, (name, label) in enumerate(self.children):
            cx = (w / n) * i + (w / n - bw) / 2
            c.setFillColor(BG_SOFT); c.setStrokeColor(LINE); c.setLineWidth(0.6)
            c.roundRect(cx, cy, bw, bh, 2 * mm, stroke=1, fill=1)
            c.setFillColor(INK); c.setFont(FONT_B, 8.5)
            c.drawCentredString(cx + bw / 2, cy + 4 * mm, name)

            c.setStrokeColor(ACCENT); c.setLineWidth(1.1)
            c.line(w / 2, ry, cx + bw / 2, cy + bh)
            c.setFillColor(ACCENT); c.setFont(FONT, 7)
            c.drawCentredString((w / 2 + cx + bw / 2) / 2,
                                (ry + cy + bh) / 2 + 1 * mm, label)

        # Iliskisi olmayan tablolar — kesikli cerceve
        dy = cy - 15 * mm
        for name, label in self.detached:
            c.setFillColor(colors.white); c.setStrokeColor(MUTED)
            c.setLineWidth(0.6); c.setDash(2, 2)
            c.roundRect((w - bw) / 2, dy, bw, bh, 2 * mm, stroke=1, fill=1)
            c.setDash()
            c.setFillColor(MUTED); c.setFont(FONT_B, 8.5)
            c.drawCentredString(w / 2, dy + 4 * mm, name)
            c.setFont(FONT, 7)
            c.drawString((w + bw) / 2 + 4 * mm, dy + 4 * mm, label)
            dy -= 15 * mm


def _page_furniture(service: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE); canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 15 * mm, A4[0] - 20 * mm, 15 * mm)
        canvas.setFont(FONT, 7.5); canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 10 * mm, f"AI Fitness Coach · {service}")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()
    return draw


def build(filename: str, service: str, tagline: str, story: list) -> None:
    doc = SimpleDocTemplate(
        os.path.join(OUT_DIR, filename), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title=f"{service} — teknik dokumantasyon", author="AI Fitness Coach",
    )
    head = [Paragraph(service, S_TITLE), Paragraph(tagline, S_SUB)]
    doc.build(head + story,
              onFirstPage=_page_furniture(service),
              onLaterPages=_page_furniture(service))
    print("olusturuldu:", filename)
