import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit

w, h = letter
LEFT = 0.75 * inch
RIGHT = w - 0.75 * inch
MID = w / 2
CONTENT_W = RIGHT - LEFT


def generate_contract_pdf(data, logo_path):
    """
    Generate a contract PDF from a data dict.

    Expected keys:
        date, contract_number, seller, buyer, quality,
        quantity, uom, shipment, price, grades, weights,
        governing_contract, discount, moisture, damage,
        heat_damage, foreign_materials, splits, payment,
        other_conditions, demurrage, broker
    Missing keys render as empty string.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    y = h - 0.6 * inch

    # --- LOGO ---
    logo_w = CONTENT_W
    logo_h = logo_w * (86 / 576)
    c.drawImage(logo_path, LEFT, y - logo_h, width=logo_w, height=logo_h, preserveAspectRatio=True)
    y -= logo_h + 0.15 * inch

    # --- ADDRESS ---
    c.setFont("Helvetica", 7.5)
    c.drawString(LEFT, y, "12500 Sherwood Drive, Leawood KS 66209")
    c.drawString(LEFT, y - 10, "1803 S Foothills Hwy., Suite P, Boulder, Colorado 80303")
    c.drawString(MID + inch, y, "Phone: (913) 491-3711  Email: mcdonald@mcdonaldpelz.com")
    c.drawString(MID + inch, y - 10, "Phone: (303) 543-7033  Email: bobby@mcdonaldpelz.com")
    y -= 0.4 * inch

    # --- RULE ---
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.5)
    c.line(LEFT, y, RIGHT, y)
    y -= 0.35 * inch

    label_x = LEFT
    value_x = LEFT + 1.6 * inch
    line_h = 0.22 * inch

    def row(label, value):
        nonlocal y
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(label_x, y, label)
        c.setFont("Helvetica", 9.5)
        c.drawString(value_x, y, str(value) if value else '')
        y -= line_h

    # --- DATE / CONTRACT NUMBER ---
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(label_x, y, "DATE:")
    c.setFont("Helvetica", 9.5)
    c.drawString(value_x, y, str(data.get('date', '')))
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(MID + 0.5 * inch, y, "CONTRACT:")
    c.setFont("Helvetica", 9.5)
    c.drawString(MID + 1.4 * inch, y, str(data.get('contract_number', '')))
    y -= line_h

    y -= 0.04 * inch
    row("SELLER:", data.get('seller', ''))
    y -= 0.04 * inch
    row("BUYER:", data.get('buyer', ''))
    y -= 0.04 * inch
    row("QUALITY:", data.get('quality', ''))
    y -= 0.04 * inch
    row("QUANTITY:", f"{data.get('quantity', '')} {data.get('uom', '')}".strip())
    row("SHIPMENT:", data.get('shipment', ''))
    row("PRICE:", data.get('price', ''))
    row("GRADES:", data.get('grades', ''))
    row("WEIGHTS:", data.get('weights', ''))

    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(label_x, y, "GOVERNING")
    y -= line_h
    row("CONTRACT:", data.get('governing_contract', ''))
    row("DISCOUNT:", data.get('discount', ''))
    row("MOISTURE:", data.get('moisture', ''))
    row("DAMAGE:", data.get('damage', ''))
    row("HEAT DAMAGE:", data.get('heat_damage', ''))

    # FOREIGN MATERIALS — wider label needs its own indent
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(label_x, y, "FOREIGN MATERIALS:")
    c.setFont("Helvetica", 9.5)
    fm_x = LEFT + 2.2 * inch
    fm_lines = simpleSplit(data.get('foreign_materials', ''), 'Helvetica', 9.5, CONTENT_W - 2.2 * inch)
    for i, line in enumerate(fm_lines):
        c.drawString(fm_x if i == 0 else value_x, y, line)
        y -= line_h

    row("SPLITS:", data.get('splits', ''))
    row("PAYMENT:", data.get('payment', ''))

    y -= 0.05 * inch
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(label_x, y, "OTHER CONDITIONS:")
    y -= line_h
    c.setFont("Helvetica", 9.5)
    other = data.get('other_conditions', '')
    if other:
        for line in simpleSplit(other, 'Helvetica', 9.5, CONTENT_W - inch):
            c.drawString(value_x, y, line)
            y -= line_h

    y -= 0.04 * inch
    row("DEMURRAGE SCHEDULE:", data.get('demurrage', ''))

    # --- BROKER ---
    y -= 0.2 * inch
    c.setFont("Helvetica", 9.5)
    c.drawString(RIGHT - 1.5 * inch, y, str(data.get('broker', '')))
    y -= line_h
    c.drawString(RIGHT - 1.0 * inch, y, "BROKER")

    # --- SELLER / BUYER SIGNATURE ---
    y -= 0.4 * inch
    c.setFont("Helvetica", 9.5)
    c.drawString(LEFT, y, "SELLER")
    c.drawString(MID + inch, y, "BUYER")

    # --- FOOTER ---
    y -= 0.3 * inch
    c.setLineWidth(0.5)
    c.line(LEFT, y, RIGHT, y)
    y -= 0.15 * inch

    footer = (
        "Please communicate any discrepancies to us within one business day of receipt of this electronic "
        "confirmation. If no discrepancies are reported it is assumed that all parties involved accept and "
        "agree to all terms as outlined above. We thank you for your business and kindly ask you to promptly "
        "sign and return a copy of this confirmation. However, the validity of this contract shall not be "
        "affected by the non-return of a signed copy."
    )
    c.setFont("Helvetica", 8)
    for line in simpleSplit(footer, 'Helvetica', 8, CONTENT_W):
        c.drawString(LEFT, y, line)
        y -= 11

    c.save()
    buffer.seek(0)
    return buffer