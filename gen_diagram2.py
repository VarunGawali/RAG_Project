"""
gen_diagram2.py — Contract360 Architecture Diagram (single slide, with business case + tech stack)
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.oxml.ns import qn
from lxml import etree


def rgb(h):
    h = h.lstrip('#')
    return RGBColor(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))


def box(slide, x, y, w, h, fill, title, detail=None, tsz=9.5, dsz=7.5, border='#30363D'):
    from pptx.enum.shapes import MSO_SHAPE
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    # corner radius
    sp = s.element
    pg = sp.find('.//' + qn('a:prstGeom'))
    if pg is not None:
        al = pg.find(qn('a:avLst'))
        if al is None:
            al = etree.SubElement(pg, qn('a:avLst'))
        for g in al.findall(qn('a:gd')):
            al.remove(g)
        gd = etree.SubElement(al, qn('a:gd'))
        gd.set('name', 'adj')
        gd.set('fmla', 'val 8000')
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    s.line.color.rgb = rgb(border)
    s.line.width = Pt(0.5)
    tf = s.text_frame
    tf.word_wrap = True
    tf._txBody.set('anchor', 'ctr')
    p0 = tf.paragraphs[0]
    p0.alignment = PP_ALIGN.CENTER
    r0 = p0.add_run()
    r0.text = title
    r0.font.bold = True
    r0.font.size = Pt(tsz)
    r0.font.color.rgb = RGBColor(0xFF,0xFF,0xFF)
    r0.font.name = 'Calibri'
    if detail:
        p1 = tf.add_paragraph()
        p1.alignment = PP_ALIGN.CENTER
        r1 = p1.add_run()
        r1.text = detail
        r1.font.bold = False
        r1.font.size = Pt(dsz)
        r1.font.color.rgb = RGBColor(0xC9,0xD1,0xD9)
        r1.font.name = 'Calibri'
    return s


def arrow(slide, x1, y1, x2, y2, c='#6E7681'):
    conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                      Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    conn.line.color.rgb = rgb(c)
    conn.line.width = Pt(1.2)
    ln = conn.line._ln
    he = ln.find(qn('a:headEnd'))
    if he is None:
        he = etree.SubElement(ln, qn('a:headEnd'))
    he.set('type','triangle'); he.set('w','med'); he.set('len','med')
    te = ln.find(qn('a:tailEnd'))
    if te is None:
        te = etree.SubElement(ln, qn('a:tailEnd'))
    te.set('type','none')
    return conn


def hline(slide, x1, y, x2, c='#6E7681'):
    conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                      Inches(x1), Inches(y), Inches(x2), Inches(y))
    conn.line.color.rgb = rgb(c)
    conn.line.width = Pt(1.2)
    return conn


def label(slide, x, y, w, h, text, sz=8, bold=False, col='#8B949E', align=PP_ALIGN.CENTER):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.fill.background(); tb.line.fill.background()
    tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = text
    r.font.bold = bold; r.font.size = Pt(sz)
    r.font.color.rgb = rgb(col); r.font.name = 'Calibri'
    return tb


def bullet_box(slide, x, y, w, h, title, items, title_col, item_col='#C9D1D9',
               bg='#161B22', border='#30363D', tsz=9, isz=8):
    """Text box with a title and bullet items (no shape fill — plain textbox)."""
    from pptx.enum.shapes import MSO_SHAPE
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    sp = s.element
    pg = sp.find('.//' + qn('a:prstGeom'))
    if pg is not None:
        al = pg.find(qn('a:avLst'))
        if al is None:
            al = etree.SubElement(pg, qn('a:avLst'))
        for g in al.findall(qn('a:gd')):
            al.remove(g)
        gd = etree.SubElement(al, qn('a:gd'))
        gd.set('name','adj'); gd.set('fmla','val 6000')
    s.fill.solid(); s.fill.fore_color.rgb = rgb(bg)
    s.line.color.rgb = rgb(border); s.line.width = Pt(0.75)
    tf = s.text_frame; tf.word_wrap = True
    tf._txBody.set('anchor','t')
    # margin
    tf._txBody.set('marL', str(int(0.12 * 914400)))
    tf._txBody.set('marR', str(int(0.12 * 914400)))
    tf._txBody.set('marT', str(int(0.1  * 914400)))
    p0 = tf.paragraphs[0]; p0.alignment = PP_ALIGN.LEFT
    r0 = p0.add_run(); r0.text = title
    r0.font.bold = True; r0.font.size = Pt(tsz)
    r0.font.color.rgb = rgb(title_col); r0.font.name = 'Calibri'
    for item in items:
        p = tf.add_paragraph(); p.alignment = PP_ALIGN.LEFT
        r = p.add_run(); r.text = item
        r.font.bold = False; r.font.size = Pt(isz)
        r.font.color.rgb = rgb(item_col); r.font.name = 'Calibri'
    return s


def build():
    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb('#0D1117')

    AW = '#6E7681'   # arrow color
    BD = '#30363D'   # border

    # ── TITLE BAR ────────────────────────────────────────────────────────────
    from pptx.enum.shapes import MSO_SHAPE
    tb = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                Inches(0), Inches(0), Inches(13.33), Inches(0.32))
    tb.fill.solid(); tb.fill.fore_color.rgb = rgb('#161B22')
    tb.line.fill.background()
    tf = tb.text_frame; tf._txBody.set('anchor','ctr')
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = 'Contract360  —  System Architecture'
    r.font.bold = True; r.font.size = Pt(13); r.font.color.rgb = RGBColor(0xFF,0xFF,0xFF)
    r.font.name = 'Calibri'

    # ── VERTICAL DIVIDER between diagram and right panel ─────────────────────
    dv = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                    Inches(8.55), Inches(0.32), Inches(8.55), Inches(7.5))
    dv.line.color.rgb = rgb('#21262D'); dv.line.width = Pt(1)
    ln = dv.line._ln
    pd = etree.SubElement(ln, qn('a:prstDash')); pd.set('val','sysDash')

    # ════════════════════════════════════════════════════════════════════════
    #  LEFT SIDE — ARCHITECTURE DIAGRAM  (x: 0.15 → 8.4, width budget ~8.25")
    # ════════════════════════════════════════════════════════════════════════
    DW = 8.25   # diagram total width
    DX = 0.15   # diagram left edge
    CX = DX + DW/2  # center x = 4.275

    # ── React UI ─────────────────────────────────────────────────────────────
    box(slide, DX, 0.35, DW, 0.47, '#1F6FEB',
        'React (Vite) UI',
        'Chat  •  Contract Selector  •  Upload  •  SSE Streaming  •  Citation Cards',
        tsz=10, dsz=8, border=BD)

    arrow(slide, CX, 0.82, CX, 0.95, AW)
    label(slide, CX+0.05, 0.79, 1.5, 0.2, 'REST + SSE', sz=7, col='#8B949E')

    # ── FastAPI ───────────────────────────────────────────────────────────────
    box(slide, DX, 0.95, DW, 0.47, '#1158C7',
        'FastAPI API',
        '/ingest  •  /contracts  •  /sessions  •  /ask/stream  •  /health',
        tsz=10, dsz=8, border=BD)

    # fork arrows from FastAPI
    LCX = DX + 1.3   # ingestion worker center x
    RCX = DX + 5.8   # query service center x
    arrow(slide, LCX, 1.42, LCX, 1.57, AW)
    arrow(slide, RCX, 1.42, RCX, 1.57, AW)

    # ── Ingestion Worker (left) ───────────────────────────────────────────────
    box(slide, DX, 1.57, 2.8, 0.47, '#0D419D',
        'Ingestion Worker',
        'worker.py  •  job state tracking',
        tsz=9.5, dsz=7.5, border=BD)

    # ── Query + Session Service (right) ──────────────────────────────────────
    box(slide, DX+4.45, 1.57, 3.8, 0.47, '#0D419D',
        'Query + Session Service',
        'query_service.py  •  scoping',
        tsz=9.5, dsz=7.5, border=BD)

    # Cosmos NoSQL below Query Service
    CDBX = DX+4.45; CDBY = 2.17
    arrow(slide, RCX, 2.04, RCX, 2.17, AW)
    box(slide, CDBX, 2.17, 3.8, 0.5, '#92400E',
        'Cosmos DB  (NoSQL)',
        'Sessions  •  Messages  •  Ingestion jobs',
        tsz=9.5, dsz=7.5, border='#B45309')

    # ── Ingestion Pipeline ────────────────────────────────────────────────────
    IPY = 2.85
    arrow(slide, LCX, 2.04, LCX, IPY, AW)
    arrow(slide, RCX, 2.67, RCX, IPY, AW)   # Cosmos → pipeline merge

    box(slide, DX, IPY, DW, 0.75, '#1A7F37',
        'Ingestion Pipeline',
        'Doc Intelligence  →  Clause Tree  →  Chunk  →  Embed  →  Summary  →  Search Index  →  KG Extract  →  Resolve  →  Graph Write',
        tsz=10, dsz=7.5, border='#238636')

    # ── Query Router ──────────────────────────────────────────────────────────
    QRY = 3.73
    arrow(slide, RCX, 3.6, RCX, QRY, AW)
    box(slide, DX+4.0, QRY, 4.25, 0.47, '#6E40C9',
        'Query Router',
        'LLM classifier  •  scope resolution  •  comparison detection',
        tsz=9.5, dsz=7.5, border='#8957E5')

    # ── Storage layer arrows from ingestion ───────────────────────────────────
    SY = 6.55  # storage boxes top y
    arrow(slide, DX+0.9,  3.6,  DX+0.9,  SY, AW)
    arrow(slide, DX+2.55, 3.6,  DX+2.55, SY, AW)
    arrow(slide, DX+4.1,  3.6,  DX+4.1,  SY, AW)

    # ── RAG Retrievers (Tree | Graph | Hybrid) ────────────────────────────────
    RRTY = 4.33
    TR_CX = DX + 5.0
    GR_CX = DX + 7.2
    arrow(slide, TR_CX, 4.2,  TR_CX, RRTY, AW)
    arrow(slide, GR_CX, 4.2,  GR_CX, RRTY, AW)
    hline(slide, TR_CX, 4.26, GR_CX, AW)

    box(slide, DX+3.85, RRTY, 1.9, 0.72, '#388BFD',
        'Tree Route',
        'Azure Search\nBM25 + vector',
        tsz=9, dsz=7.5, border=BD)
    box(slide, DX+6.1, RRTY, 2.1, 0.72, '#388BFD',
        'Graph Route',
        'Gremlin KG\nentity linking',
        tsz=9, dsz=7.5, border=BD)

    # ── Hybrid + Comparison ───────────────────────────────────────────────────
    HY = 5.18
    arrow(slide, TR_CX, 5.05, TR_CX, HY, AW)
    arrow(slide, GR_CX, 5.05, GR_CX, HY, AW)
    hline(slide, TR_CX, 5.12, GR_CX, AW)

    box(slide, DX+3.85, HY, 4.35, 0.47, '#6E40C9',
        'Hybrid Merge  +  Comparison Branch',
        'CONTRACT A / B side-by-side  •  grounded context',
        tsz=9.5, dsz=7.5, border='#8957E5')

    # ── Answer Generation ─────────────────────────────────────────────────────
    AGY = 5.78
    AGCX = DX + 6.025
    arrow(slide, AGCX, 5.65, AGCX, AGY, AW)
    box(slide, DX+3.85, AGY, 4.35, 0.55, '#6E40C9',
        'Answer Generation + Grounding',
        'GPT-4o  •  [S#] citations  •  SSE stream to UI',
        tsz=9.5, dsz=7.5, border='#8957E5')

    # ── Storage Bar ───────────────────────────────────────────────────────────
    sbar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(0), Inches(6.47), Inches(8.55), Inches(1.03))
    sbar.fill.solid(); sbar.fill.fore_color.rgb = rgb('#161B22')
    sbar.line.fill.background()

    label(slide, 0.18, 6.47, 4.0, 0.22,
          'AZURE STORAGE & SERVICES', sz=7, bold=True, col='#E3B341', align=PP_ALIGN.LEFT)

    storage = [
        (0.18,  'Azure Blob',         'PDFs • artifacts'),
        (2.3,   'Azure AI Search',    'BM25 + vector'),
        (4.45,  'Cosmos Gremlin',     'Knowledge Graph'),
        (6.55,  'Azure OpenAI',       'GPT-4o • embeddings'),
    ]
    for sx, st, sd in storage:
        box(slide, sx, 6.7, 1.95, 0.68, '#92400E', st, sd,
            tsz=8.5, dsz=7.5, border='#B45309')

    # ════════════════════════════════════════════════════════════════════════
    #  RIGHT PANEL — BUSINESS USE CASE + TECH STACK  (x: 8.65 → 13.15)
    # ════════════════════════════════════════════════════════════════════════
    RX = 8.68
    RW = 4.47

    # ── Business Use Case ─────────────────────────────────────────────────────
    bullet_box(slide, RX, 0.35, RW, 3.3,
               'Business Use Case',
               [
                   '',
                   'Legal teams manage hundreds of contracts',
                   'manually — finding obligations or risk',
                   'clauses takes hours per document.',
                   '',
                   'Cross-contract comparison is nearly',
                   'impossible at scale, creating exposure',
                   'to missed deadlines and obligations.',
                   '',
                   '→  Ask any legal question across your',
                   '    entire contract portfolio and get',
                   '    cited, structured answers — instantly.',
               ],
               title_col='#79C0FF', item_col='#C9D1D9',
               bg='#0D1F38', border='#1F6FEB', tsz=10, isz=8)

    # ── Tech Stack ────────────────────────────────────────────────────────────
    bullet_box(slide, RX, 3.78, RW, 3.6,
               'Tech Stack',
               [
                   '',
                   'Frontend    React (Vite) + TypeScript',
                   'Backend     FastAPI (Python) + Uvicorn',
                   'LLM           Azure OpenAI  GPT-4o',
                   'Embeddings  text-embedding-3-large',
                   'Search        Azure AI Search (BM25+vector)',
                   'Graph DB    Cosmos DB  Gremlin API',
                   'Session DB  Cosmos DB  NoSQL',
                   'Storage      Azure Blob Storage',
                   'Doc Parse   Azure Document Intelligence',
                   'Deploy       Docker  +  Azure Container Apps',
               ],
               title_col='#3FB950', item_col='#C9D1D9',
               bg='#0D1F1A', border='#238636', tsz=10, isz=8)

    prs.save('/home/user/RAG_Project_EY/architecture_diagram2.pptx')
    print('Saved → architecture_diagram2.pptx')


if __name__ == '__main__':
    build()
