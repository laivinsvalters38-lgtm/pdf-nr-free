import re
import pandas as pd
import streamlit as st
from pdf2image import convert_from_bytes
import pytesseract

st.set_page_config(page_title="PDF → brīvie Nr", layout="wide")

ROW_RE = re.compile(
    r"(?:^|[^\d])(\d{1,7})\s*(?:\*{1,3}|»)?\s+"
    r"(\d{5,7}[.,]\d{1,3})\s+"
    r"(\d{5,7}[.,]\d{1,3})(?!\d)",
    re.MULTILINE
)

def norm_float(s: str) -> float:
    return float(s.replace(",", "."))

def extract_points_from_text(text: str, x_min: float, x_max: float, y_min: float, y_max: float, nr_max: int):
    points = {}
    for m in ROW_RE.finditer(text):
        nr = int(m.group(1))
        x = norm_float(m.group(2))
        y = norm_float(m.group(3))

        if not (x_min <= x <= x_max and y_min <= y <= y_max):
            continue
        if not (1 <= nr <= nr_max):
            continue

        points.setdefault(nr, (x, y))

    df = pd.DataFrame(
        [{"Nr": nr, "X": points[nr][0], "Y": points[nr][1]} for nr in sorted(points)]
    )
    return df

def extract_points_from_text(text: str, x_min: float, x_max: float, y_min: float, y_max: float, nr_max: int):
    """
    2 režīmi:
    A) Ja tekstā ir 'ROBEŽPUNKTU KOORDINĀTAS' -> kolonnu režīms (Nr saraksts + X saraksts + Y saraksts)
    B) Citādi -> vecais "rindu regex" režīms
    """

    # ---------- A) KOLONNU REŽĪMS ----------
    key = "ROBEŽPUNKTU KOORDINĀTAS"
    if key in text:
        sec = text.split(key, 1)[1]

        # 1) atrodam pirmo decimālskaitli -> līdz tam krājam Nr kandidātus
        first_float = re.search(r"\d{5,7}[.,]\d{1,3}", sec)
        head = sec[: first_float.start()] if first_float else sec

        # Nr kandidāti: skaitlis + iespējams » vai * vai -
        nr_tokens = re.findall(r"\b(\d{1,7})\s*[»*\-]?\b", head)
        nrs = []
        for t in nr_tokens:
            n = int(t)
            if 1 <= n <= nr_max:
                nrs.append(n)

        # 2) savācam visus decimālskaitļus (gan X, gan Y)
        float_tokens = re.findall(r"(\d{5,7}[.,]\d{1,3})", sec)
        vals = [norm_float(v) for v in float_tokens]

        # 3) sadalām X/Y pēc vērtības (šim plānu tipam X ~ 4xxk, Y ~ 5xxk..)
        #    Robeža 500000 strādā uz tava 2010 PDF (X ~ 409-412k; Y ~ 596-598k)
        xs = [v for v in vals if v < 500000 and x_min <= v <= x_max]
        ys = [v for v in vals if v >= 500000 and y_min <= v <= y_max]

        # 4) salāgojam pēc garuma (ņemam kopējo min)
        m = min(len(nrs), len(xs), len(ys))
        nrs, xs, ys = nrs[:m], xs[:m], ys[:m]

        df = pd.DataFrame({"Nr": nrs, "X": xs, "Y": ys})

        # unikāli pēc Nr (ja OCR atkārto)
        df = df.drop_duplicates(subset=["Nr"]).sort_values("Nr").reset_index(drop=True)
        return df

    # ---------- B) RINDU REGEX (vecais) ----------
    points = {}
    for m in ROW_RE.finditer(text):
        nr = int(m.group(1))
        x = norm_float(m.group(2))
        y = norm_float(m.group(3))

        if not (x_min <= x <= x_max and y_min <= y <= y_max):
            continue
        if not (1 <= nr <= nr_max):
            continue

        points.setdefault(nr, (x, y))

    df = pd.DataFrame(
        [{"Nr": nr, "X": points[nr][0], "Y": points[nr][1]} for nr in sorted(points)]
    )
    return df


st.title("PDF → Nr brīvie (OCR + tabula)")

with st.sidebar:
    st.header("Iestatījumi")
    lang = st.selectbox("OCR valoda", ["lav+eng", "eng", "lav"], index=0)
    dpi = st.slider("DPI (kvalitāte)", 150, 450, 300, 50)
    max_pages = st.slider("Maks. lapas OCR", 1, 40, 12, 1)

    st.subheader("Filtri (lai nesajauc ar datumiem u.c.)")
    x_min = st.number_input("X min", value=200000.0, step=1000.0)
    x_max = st.number_input("X max", value=800000.0, step=1000.0)
    y_min = st.number_input("Y min", value=200000.0, step=1000.0)
    y_max = st.number_input("Y max", value=800000.0, step=1000.0)
    nr_max = st.number_input("Nr max", value=20000000, step=100000)

    st.subheader("Brīvie numuri")
    how_many = st.slider("Cik brīvos rādīt", 10, 200, 50, 10)

uploaded = st.file_uploader("Iemet PDF (arī skenētu)", type=["pdf"])

if uploaded:
    pdf_bytes = uploaded.read()

    st.info("1) PDF → attēli…")
    images = convert_from_bytes(pdf_bytes, dpi=dpi)
    images = images[:max_pages]

    st.info("2) OCR lasa tekstu…")
    all_text = []
    prog = st.progress(0)
    for i, img in enumerate(images, start=1):
        txt = pytesseract.image_to_string(img, lang=lang)
        all_text.append(txt)
        prog.progress(int(i / len(images) * 100))

    text = "\n".join(all_text)

    st.info("3) Izvelk Nr, X, Y…")
    df = extract_points_from_text(text, x_min, x_max, y_min, y_max, int(nr_max))

    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("Atrasti punkti")
        st.write(f"Punktu skaits: **{len(df)}**")
        st.dataframe(df, use_container_width=True, height=420)

    with c2:
        st.subheader("Brīvie Nr")
        free = find_free_numbers(df["Nr"].tolist() if len(df) else [], how_many=how_many)
        st.write(f"Mazākais brīvais: **{free[0] if free else '—'}**")
        st.dataframe(pd.DataFrame({"FreeNr": free}), use_container_width=True, height=420)

    st.subheader("Lejupielāde")
    st.download_button("Lejupielādēt points.csv", df.to_csv(index=False).encode("utf-8"), "points.csv", "text/csv")
    st.download_button("Lejupielādēt free.csv", pd.DataFrame({"FreeNr": free}).to_csv(index=False).encode("utf-8"), "free.csv", "text/csv")

    with st.expander("Debug: OCR teksts (pirmais gabals)"):
        st.text(text[:4000])

