"""e-Gerak SPR - Streamlit edition.

Sistem Penjejak Pergerakan Sektor Perancangan PPD Dalat, dibina semula
menggunakan Streamlit + SQLite. Berkongsi pangkalan data yang sama dengan
sistem Node.js/HTML sedia ada (server/movements.db), jadi kedua-dua sistem
boleh berjalan serentak dan berkongsi rekod yang sama.

Jalankan dengan: streamlit run app.py
"""

import io
import re
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import db

ALLOWED_EMAIL_REGEX = re.compile(r"^[^@]+@moe\.gov(?:\.my)?$")

TUJUAN_OPTIONS = [
    "Mesyuarat",
    "Bengkel",
    "Kursus",
    "Pemantauan",
    "Cuti Umum",
    "Pelepasan",
    "Cuti",
    "Tugas Rasmi Lain",
]
TUJUAN_LABELS = {
    "Mesyuarat": "Mesyuarat / Perbincangan",
    "Bengkel": "Bengkel Kerja",
    "Kursus": "Kursus / Latihan",
    "Pemantauan": "Pemantauan Sekolah",
    "Cuti Umum": "Cuti Umum",
    "Pelepasan": "Pelepasan",
    "Cuti": "Cuti Rehat / Cuti Sakit",
    "Tugas Rasmi Lain": "Tugas Rasmi Lain",
}
TUJUAN_COLORS = {
    "Mesyuarat": "#3b82f6",
    "Bengkel": "#a855f7",
    "Kursus": "#f59e0b",
    "Pemantauan": "#10b981",
    "Cuti Umum": "#64748b",
    "Pelepasan": "#06b6d4",
    "Cuti": "#eab308",
    "Tugas Rasmi Lain": "#f43f5e",
}
POSITION_OPTIONS = ["Penolong Pegawai Pendidikan", "Timbalan Sektor Perancangan"]

HARI_MALAY = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"]
BULAN_MALAY = [
    "Januari", "Februari", "Mac", "April", "Mei", "Jun",
    "Julai", "Ogos", "September", "Oktober", "November", "Disember",
]
BULAN_PENDEK = ["Jan", "Feb", "Mac", "Apr", "Mei", "Jun", "Jul", "Ogo", "Sep", "Okt", "Nov", "Dis"]

PERIOD_LABELS = {"day": "Hari", "week": "Minggu", "month": "Bulan", "year": "Tahun", "all": "Semua"}
EXPORT_SUFFIX = {"day": "Harian", "week": "Mingguan", "month": "Bulanan", "year": "Tahunan", "all": "Semua"}


# ---------------------------------------------------------------------------
# Period-range helpers (mirrors the day/week/month/year logic from index.html)
# ---------------------------------------------------------------------------

def get_period_range(period, reference=None):
    if period == "all":
        return None
    reference = reference or date.today()
    if period == "day":
        start = reference
        end = start + timedelta(days=1)
    elif period == "week":
        js_weekday = (reference.weekday() + 1) % 7  # Sunday=0 .. Saturday=6, like JS getDay()
        start = reference - timedelta(days=js_weekday)
        end = start + timedelta(days=7)
    elif period == "month":
        start = reference.replace(day=1)
        end = (start.replace(year=start.year + 1, month=1) if start.month == 12
               else start.replace(month=start.month + 1))
    elif period == "year":
        start = reference.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
    else:
        return None
    return start, end


def is_record_in_period(tarikh_str, period):
    range_ = get_period_range(period)
    if range_ is None:
        return True
    start, end = range_
    try:
        record_date = datetime.strptime(tarikh_str, "%Y-%m-%d").date()
    except ValueError:
        return False
    return start <= record_date < end


def format_period_range_label(period):
    if period == "all":
        return "Sepanjang masa"
    start, end = get_period_range(period)
    end_inclusive = end - timedelta(days=1)
    fmt = lambda d: f"{d.day:02d} {BULAN_PENDEK[d.month - 1]}"
    if period == "day":
        return f"{fmt(start)} {start.year}"
    if period == "year":
        return f"Tahun {start.year}"
    return f"{fmt(start)} - {fmt(end_inclusive)} {end_inclusive.year}"


def display_date(tarikh_str):
    try:
        y, m, d = tarikh_str.split("-")
        return f"{d}/{m}/{y}"
    except ValueError:
        return tarikh_str


def match_tujuan_bucket(tujuan):
    low = tujuan.lower()
    for bucket in TUJUAN_OPTIONS:
        if bucket.lower() in low:
            return bucket
    return "Tugas Rasmi Lain"


# ---------------------------------------------------------------------------
# Page config + theme (Antigravity space theme, ported from index.html)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="e-Gerak SPR - Sektor Perancangan PPD Dalat",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      :root {
        --bg-dark: #090d16;
        --bg-card: rgba(17, 24, 39, 0.75);
        --primary-blue: #2563eb;
        --secondary-blue: #1e3a8a;
        --accent-cyan: #06b6d4;
        --accent-pink: #f43f5e;
        --success-green: #10b981;
        --text-muted: #94a3b8;
      }
      .stApp {
        background: radial-gradient(circle at 20% 20%, #0b1226 0%, var(--bg-dark) 55%, #050810 100%);
        color: #e5e7eb;
      }
      section[data-testid="stSidebar"] {
        background: rgba(9, 13, 22, 0.9);
        border-right: 1px solid rgba(37, 99, 235, 0.25);
      }
      .glass-card {
        background: var(--bg-card);
        border: 1px solid rgba(37, 99, 235, 0.25);
        border-radius: 16px;
        padding: 1.4rem 1.6rem;
        margin-bottom: 1.2rem;
        backdrop-filter: blur(6px);
        animation: floaty 6s ease-in-out infinite;
      }
      @keyframes floaty {
        0%, 100% { transform: translateY(0px); }
        50% { transform: translateY(-6px); }
      }
      .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #fff;
      }
      .brand-title, .brand-title span {
        background: linear-gradient(45deg, var(--accent-cyan), var(--primary-blue));
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent !important;
        -webkit-text-fill-color: transparent !important;
        font-weight: 800;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--bg-card) !important;
        border: 1px solid rgba(37, 99, 235, 0.25) !important;
        border-radius: 16px !important;
        backdrop-filter: blur(6px);
        margin-bottom: 1.2rem;
      }
      .user-tag {
        border: 1px solid rgba(6, 182, 212, 0.35);
        border-radius: 12px;
        padding: 0.6rem 0.9rem;
        background: rgba(6, 182, 212, 0.08);
      }
      .day-event-item {
        display: flex; flex-direction: column; gap: 2px;
        padding: 8px 10px; border-bottom: 1px solid rgba(148,163,184,0.15);
      }
      .day-event-name { font-weight: 600; color: #fff; }
      .day-event-dest { font-size: 0.8rem; color: var(--text-muted); }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "user_session" not in st.session_state:
    st.session_state.user_session = None
if "nav" not in st.session_state:
    st.session_state.nav = "Utama"
if "cal_year" not in st.session_state:
    today = date.today()
    st.session_state.cal_year = today.year
    st.session_state.cal_month = today.month
if "selected_day" not in st.session_state:
    st.session_state.selected_day = date.today().isoformat()


# ---------------------------------------------------------------------------
# Auth / identify gate (no password - matches the original "identify" flow)
# ---------------------------------------------------------------------------

def render_identify_gate():
    st.markdown('<h1 class="brand-title">🛰️ e-Gerak SPR</h1>', unsafe_allow_html=True)
    st.caption("Sistem Penjejak Pergerakan Sektor Perancangan PPD Dalat")

    with st.container(border=True):
        st.subheader("Kenal Pasti Diri Anda")
        with st.form("identify_form"):
            name = st.text_input("Nama Penuh")
            email = st.text_input("Alamat E-mel (MOE)", placeholder="nama@moe.gov.my")
            position = st.selectbox("Jawatan", ["Pilih Jawatan..."] + POSITION_OPTIONS)
            submitted = st.form_submit_button("Masuk ke Pangkalan Orbit", use_container_width=True)

        if submitted:
            email_clean = email.strip().lower()
            if not name.strip():
                st.error("Sila masukkan nama penuh.")
            elif not ALLOWED_EMAIL_REGEX.match(email_clean):
                st.error("Akses disekat. Sila gunakan e-mel rasmi MOE (@moe.gov.my atau @moe.gov).")
            elif position == "Pilih Jawatan...":
                st.error("Sila pilih jawatan anda.")
            else:
                st.session_state.user_session = {
                    "name": name.strip(),
                    "email": email_clean,
                    "position": position,
                }
                st.session_state.nav = "Utama"
                st.rerun()

        st.markdown(
            'Hanya akaun e-mel berakhiran <strong>@moe.gov.my</strong> atau '
            '<strong>@moe.gov</strong> dibenarkan meneruskan.',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_utama(records):
    st.markdown('<h1 class="brand-title">🛰️ Utama</h1>', unsafe_allow_html=True)
    session = st.session_state.user_session

    today_str = date.today().isoformat()
    total = len(records)
    active_today = sum(1 for r in records if r["tarikh"] == today_str)
    unique_officers = len({r["nama"].strip().lower() for r in records})

    col1, col2, col3 = st.columns(3)
    col1.metric("Jumlah Log Pergerakan", total)
    col2.metric("Aktif Hari Ini", active_today)
    col3.metric("Pegawai Unik", unique_officers)

    with st.container(border=True):
        st.markdown(f"### 👋 Selamat kembali, {session['name']}")
        st.write(
            "e-Gerak SPR membantu Sektor Perancangan PPD Dalat menjejak pergerakan pegawai "
            "secara masa nyata - dari mesyuarat, bengkel, kursus, hingga pemantauan sekolah. "
            "Gunakan navigasi di sebelah kiri untuk merekod pergerakan baharu, menyemak analisis, "
            "melihat kalendar, atau menjana fail Excel."
        )


def page_kalendar(records):
    st.markdown('<h1 class="brand-title">🛰️ Kalendar</h1>', unsafe_allow_html=True)

    with st.container(border=True):
        st.components.v1.html(
            f"""
            <div style="font-family: 'Courier New', monospace; text-align:center; color:#e5e7eb;">
              <div id="clock" style="font-size:2.4rem; font-weight:700; color:#06b6d4;"></div>
              <div id="dateline" style="color:#94a3b8; margin-top:4px;"></div>
            </div>
            <script>
              const hari = ["Ahad","Isnin","Selasa","Rabu","Khamis","Jumaat","Sabtu"];
              const bulan = {BULAN_MALAY};
              function tick() {{
                const now = new Date();
                const hh = String(now.getHours()).padStart(2,'0');
                const mm = String(now.getMinutes()).padStart(2,'0');
                const ss = String(now.getSeconds()).padStart(2,'0');
                document.getElementById('clock').textContent = hh+':'+mm+':'+ss;
                document.getElementById('dateline').textContent =
                  hari[now.getDay()] + ', ' + now.getDate() + ' ' + bulan[now.getMonth()] + ' ' + now.getFullYear();
              }}
              tick();
              setInterval(tick, 1000);
            </script>
            """,
            height=100,
        )

    with st.container(border=True):
        nav_prev, nav_title, nav_next = st.columns([1, 3, 1])
        if nav_prev.button("⬅ Bulan Lepas", use_container_width=True):
            m, y = st.session_state.cal_month - 1, st.session_state.cal_year
            if m < 1:
                m, y = 12, y - 1
            st.session_state.cal_month, st.session_state.cal_year = m, y
            st.rerun()
        nav_title.markdown(
            f"<h3 style='text-align:center;'>{BULAN_MALAY[st.session_state.cal_month - 1]} {st.session_state.cal_year}</h3>",
            unsafe_allow_html=True,
        )
        if nav_next.button("Bulan Depan ➡", use_container_width=True):
            m, y = st.session_state.cal_month + 1, st.session_state.cal_year
            if m > 12:
                m, y = 1, y + 1
            st.session_state.cal_month, st.session_state.cal_year = m, y
            st.rerun()

        movement_dates = {r["tarikh"] for r in records}
        year, month = st.session_state.cal_year, st.session_state.cal_month
        first_of_month = date(year, month, 1)
        first_weekday = first_of_month.weekday()  # Monday=0
        days_in_month = ((first_of_month.replace(year=year + 1, month=1) if month == 12
                           else first_of_month.replace(month=month + 1)) - first_of_month).days

        header_cols = st.columns(7)
        for c, label in zip(header_cols, HARI_MALAY):
            c.markdown(f"<div style='text-align:center; color:#94a3b8; font-size:0.75rem;'>{label}</div>", unsafe_allow_html=True)

        today = date.today()
        day_num = 1
        total_cells = first_weekday + days_in_month
        weeks = -(-total_cells // 7)  # ceil
        for _week in range(weeks):
            cols = st.columns(7)
            for col_idx, c in enumerate(cols):
                cell_index = _week * 7 + col_idx
                if cell_index < first_weekday or day_num > days_in_month:
                    c.markdown("&nbsp;", unsafe_allow_html=True)
                    continue
                this_date = date(year, month, day_num)
                date_str = this_date.isoformat()
                has_movement = date_str in movement_dates
                is_today = this_date == today
                label = f"{'🔵' if has_movement else ''} {day_num}"
                btn_type = "primary" if is_today else "secondary"
                if c.button(label.strip(), key=f"cal_{date_str}", use_container_width=True, type=btn_type):
                    st.session_state.selected_day = date_str
                    st.rerun()
                day_num += 1
        st.caption("🔵 = hari dengan pergerakan berdaftar")

    with st.container(border=True):
        sel_str = st.session_state.selected_day
        st.markdown(f"### Pergerakan Tarikh: {display_date(sel_str)}")
        matched = [r for r in records if r["tarikh"] == sel_str]
        if not matched:
            st.info("Tiada pergerakan berjadual pada tarikh ini. Semua berada di pangkalan.")
        else:
            for r in matched:
                st.markdown(
                    f'<div class="day-event-item"><span class="day-event-name">{r["nama"]}</span>'
                    f'<span class="day-event-dest">📍 {r["destinasi"]} ({r["tujuan"]})</span></div>',
                    unsafe_allow_html=True,
                )


def page_borang():
    st.markdown('<h1 class="brand-title">🛰️ Borang Pergerakan</h1>', unsafe_allow_html=True)
    session = st.session_state.user_session

    with st.container(border=True):
        with st.form("borang_pergerakan"):
            st.text_input("Nama Pegawai", value=session["name"], disabled=True)
            tarikh = st.date_input("Tarikh Pergerakan", value=date.today(), format="YYYY-MM-DD")
            destinasi = st.text_input("Destinasi / Lokasi", placeholder="Contoh: Pejabat Pendidikan Daerah Dalat")
            tujuan = st.selectbox(
                "Tujuan Pergerakan",
                ["Pilih Tujuan Misi..."] + TUJUAN_OPTIONS,
                format_func=lambda v: TUJUAN_LABELS.get(v, v),
            )
            nota = st.text_area("Nota (pilihan)")
            submitted = st.form_submit_button("Hantar Pergerakan", use_container_width=True)

        if submitted:
            if not destinasi.strip():
                st.error("Sila isi destinasi / lokasi.")
            elif tujuan == "Pilih Tujuan Misi...":
                st.error("Sila pilih tujuan pergerakan.")
            else:
                db.insert_movement(
                    nama=session["name"],
                    tarikh=tarikh.isoformat(),
                    destinasi=destinasi.strip(),
                    tujuan=tujuan,
                    nota=nota.strip(),
                    submitted_by=session["email"],
                )
                st.success(f"Pergerakan {session['name']} berjaya dihantar ke log Sektor Perancangan!")
                st.session_state.nav = "Analisis Pergerakan"
                st.rerun()


def page_analisis(records):
    st.markdown('<h1 class="brand-title">🛰️ Analisis Pergerakan</h1>', unsafe_allow_html=True)
    session = st.session_state.user_session

    with st.container(border=True):
        period = st.radio(
            "Tempoh", list(PERIOD_LABELS.keys()), format_func=lambda p: PERIOD_LABELS[p],
            horizontal=True, index=1, key="analisis_period",
        )
        st.caption(format_period_range_label(period))
        search = st.text_input("Cari (nama, destinasi, tujuan, nota)", key="analisis_search")

        period_records = [r for r in records if is_record_in_period(r["tarikh"], period)]
        period_records.sort(key=lambda r: r["tarikh"], reverse=True)

        if search:
            needle = search.lower()
            period_records = [
                r for r in period_records
                if needle in " ".join(str(r[k]) for k in ("nama", "destinasi", "tujuan", "nota")).lower()
            ]

        if not period_records:
            if not records:
                st.info("Semua pegawai berada di pangkalan utama (PPD Dalat).")
            else:
                st.info(f"Tiada log pergerakan bagi tempoh ini ({format_period_range_label(period)}).")
            return

        header = st.columns([2, 1.2, 2, 1.4, 2.4, 0.8])
        for c, label in zip(header, ["Nama", "Tarikh", "Destinasi", "Tujuan", "Nota", ""]):
            c.markdown(f"**{label}**")

        for r in period_records:
            bucket = match_tujuan_bucket(r["tujuan"])
            color = TUJUAN_COLORS[bucket]
            cols = st.columns([2, 1.2, 2, 1.4, 2.4, 0.8])
            cols[0].write(r["nama"])
            cols[1].write(display_date(r["tarikh"]))
            cols[2].write(f'📍 {r["destinasi"]}')
            cols[3].markdown(f'<span class="badge" style="background:{color};">{r["tujuan"]}</span>', unsafe_allow_html=True)
            cols[4].write(r["nota"] or "-")
            is_own = r["submittedBy"] == session["email"]
            if is_own:
                if cols[5].button("🗑️", key=f"del_{r['id']}", help="Padam Rekod"):
                    ok, err = db.delete_movement(r["id"], session["email"])
                    if ok:
                        st.toast(f"Rekod pergerakan {r['nama']} telah dikeluarkan dari pangkalan.")
                    else:
                        st.error(err)
                    st.rerun()
            else:
                cols[5].markdown("🔒")

    render_insights(period_records)


def render_insights(records):
    with st.container(border=True):
        st.markdown("### Analisis Tujuan")
        counts = {t: 0 for t in TUJUAN_OPTIONS}
        for r in records:
            counts[match_tujuan_bucket(r["tujuan"])] += 1
        df = pd.DataFrame({"Tujuan": list(counts.keys()), "Bilangan": list(counts.values())}).set_index("Tujuan")
        st.bar_chart(df, color="#06b6d4")


def build_export_dataframe(records):
    rows = [
        {
            "NAMA PEGAWAI": r["nama"],
            "TARIKH PERGERAKAN": display_date(r["tarikh"]),
            "DESTINASI / LOKASI": r["destinasi"],
            "TUJUAN MISI": r["tujuan"],
            "NOTA TAMBAHAN / AGENDA": r["nota"] or "-",
        }
        for r in records
    ]
    return pd.DataFrame(rows)


def to_excel_bytes(df):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Log Pergerakan")
        worksheet = writer.sheets["Log Pergerakan"]
        widths = [35, 18, 25, 18, 45]
        for col_idx, width in enumerate(widths, start=1):
            worksheet.column_dimensions[worksheet.cell(row=1, column=col_idx).column_letter].width = width
    return buffer.getvalue()


def page_jana(records):
    st.markdown('<h1 class="brand-title">🛰️ Jana Fail</h1>', unsafe_allow_html=True)

    with st.container(border=True):
        period = st.radio(
            "Tempoh Eksport", list(PERIOD_LABELS.keys()), format_func=lambda p: PERIOD_LABELS[p],
            horizontal=True, index=4, key="export_period",
        )
        st.caption(format_period_range_label(period))

        export_records = [r for r in records if is_record_in_period(r["tarikh"], period)]
        st.metric("Rekod Bagi Tempoh Ini", len(export_records))

        if not export_records:
            st.warning("Tiada rekod data pergerakan untuk dieksport bagi tempoh ini!")
        else:
            df = build_export_dataframe(export_records)
            excel_bytes = to_excel_bytes(df)
            suffix = EXPORT_SUFFIX[period]
            st.download_button(
                "⬇️ Jana & Muat Turun Excel",
                data=excel_bytes,
                file_name=f"Log_Pergerakan_Sektor_Perancangan_Dalat_{suffix}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )


def page_tetapan(records):
    st.markdown('<h1 class="brand-title">🛰️ Tetapan</h1>', unsafe_allow_html=True)
    session = st.session_state.user_session

    with st.container(border=True):
        st.markdown(f"**Nama:** {session['name']}")
        st.markdown(f"**E-mel:** {session['email']}")
        st.markdown(f"**Jawatan:** {session['position']}")
        if st.button("Log Keluar"):
            st.session_state.user_session = None
            st.rerun()

    with st.container(border=True):
        st.markdown("#### ⚠️ Tetap Semula Orbit")
        st.caption(
            "Perhatian: Menetapkan semula orbit akan memadamkan KESEMUA pergerakan yang "
            "tersimpan dalam pangkalan data ini secara kekal, bagi semua pengguna."
        )
        confirm = st.checkbox(f"Saya faham dan mahu memadam kesemua {len(records)} rekod pergerakan.")
        if st.button("☢️ Tetap Semula Orbit (Clear Data)", disabled=not confirm):
            db.delete_all()
            st.success("Semua data pergerakan telah dipadamkan.")
            st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if st.session_state.user_session is None:
        render_identify_gate()
        return

    session = st.session_state.user_session
    records = db.list_movements()

    with st.sidebar:
        st.markdown('<h2 class="brand-title">🛰️ e-Gerak SPR</h2>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="user-tag">👤 <strong>{session["name"]}</strong><br>'
            f'<span style="color:#94a3b8; font-size:0.8rem;">{session["position"]}</span></div>',
            unsafe_allow_html=True,
        )
        st.write("")
        pages = ["Utama", "Kalendar", "Borang Pergerakan", "Analisis Pergerakan", "Jana Fail", "Tetapan"]
        icons = {"Utama": "🏠", "Kalendar": "📅", "Borang Pergerakan": "📝",
                 "Analisis Pergerakan": "📊", "Jana Fail": "📁", "Tetapan": "⚙️"}
        st.session_state.nav = st.radio(
            "Navigasi",
            pages,
            index=pages.index(st.session_state.nav) if st.session_state.nav in pages else 0,
            format_func=lambda p: f"{icons[p]}  {p}",
            label_visibility="collapsed",
        )
        if db.is_using_fallback_storage():
            st.caption("⚠️ Storan sementara pada hos ini - data akan reset bila app dimulakan semula.")

    nav = st.session_state.nav
    if nav == "Utama":
        page_utama(records)
    elif nav == "Kalendar":
        page_kalendar(records)
    elif nav == "Borang Pergerakan":
        page_borang()
    elif nav == "Analisis Pergerakan":
        page_analisis(records)
    elif nav == "Jana Fail":
        page_jana(records)
    elif nav == "Tetapan":
        page_tetapan(records)

    st.markdown(
        '<p style="text-align:center; color:#64748b; font-size:0.75rem; margin-top:2rem;">'
        "© 2026 Sektor Perancangan, Pejabat Pendidikan Daerah Dalat.</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
