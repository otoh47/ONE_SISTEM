import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from utils.pdf_generator import PDF
import os
import shutil
import base64
import requests
from pytz import timezone
from apscheduler.schedulers.background import BackgroundScheduler
import time

# Fungsi untuk format angka dengan pemisah ribuan
def format_angka(value):
    """Format angka dengan titik sebagai pemisah ribuan, tanpa desimal"""
    try:
        return f"{int(value):,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(value)

# --- START: Pengaturan Halaman Full Screen ---
st.set_page_config(layout="wide", page_title="Aplikasi Surat Jalan & Slip Penimbangan")
# --- END: Pengaturan Halaman Full Screen ---

# Konfigurasi direktori
TEMP_PDF_DIR = "temp_pdf"
BACKUP_DIR = "backup"
os.makedirs(TEMP_PDF_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# Backup database dengan timestamp
if os.path.exists("surat_jalan.db"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"surat_jalan_backup_{timestamp}.db")
    try:
        shutil.copy("surat_jalan.db", backup_path)
        st.sidebar.info(f"Backup berhasil sebagai '{backup_path}'")
    except Exception as e:
        st.sidebar.warning(f"Gagal backup database: {e}")

# Koneksi ke database
try:
    conn = sqlite3.connect('surat_jalan.db', check_same_thread=False)
    c = conn.cursor()
except Exception as e:
    st.error(f"Gagal koneksi ke database: {e}")
    st.stop()

# Buat tabel jika belum ada
try:
    c.execute('''
        CREATE TABLE IF NOT EXISTS surat_jalan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tanggal_masuk TEXT,
            jam_masuk TEXT,
            tanggal_keluar TEXT,
            jam_keluar TEXT,
            nomor_do TEXT,
            nomor_polisi TEXT,
            nama_sopir TEXT,
            nama_barang TEXT,
            po_do TEXT,
            transport TEXT,
            bruto REAL,
            tara REAL,
            netto REAL,
            tanggal_input TEXT,
            nama_ditimbang TEXT,
            nama_diterima TEXT,
            nama_diketahui TEXT
        )
    ''')
    conn.commit()
except Exception as e:
    st.error(f"Gagal membuat tabel: {e}")
    st.stop()

# --- FUNGSI BARU: MIGRASI DATABASE ---
def add_missing_columns(conn, c):
    c.execute("PRAGMA table_info(surat_jalan)")
    existing_columns = [col[1] for col in c.fetchall()]

    new_columns = {
        "nama_ditimbang": "TEXT",
        "nama_diterima": "TEXT",
        "nama_diketahui": "TEXT"
    }

    for col_name, col_type in new_columns.items():
        if col_name not in existing_columns:
            try:
                c.execute(f"ALTER TABLE surat_jalan ADD COLUMN {col_name} {col_type} DEFAULT ''")
                conn.commit()
                st.sidebar.success(f"Kolom '{col_name}' berhasil ditambahkan ke database.")
            except sqlite3.OperationalError as e:
                st.sidebar.error(f"Gagal menambahkan kolom '{col_name}': {e}")

# Panggil fungsi migrasi
add_missing_columns(conn, c)

# --- KONFIGURASI TELEGRAM ---
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

def send_telegram_message(message):
    """Mengirim pesan ke Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        st.error("Token atau Chat ID Telegram belum dikonfigurasi!")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload)
        return response.status_code == 200
    except Exception as e:
        st.error(f"Error mengirim pesan Telegram: {e}")
        return False

# Fungsi utilitas cetak dan preview
def get_ready_printer():
    if os.name == 'nt':
        try:
            import win32print
            import win32api
            printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
            for printer in printers:
                printer_name = printer[2]
                try:
                    hprinter = win32print.OpenPrinter(printer_name)
                    status = win32print.GetPrinter(hprinter)[18]
                    win32print.ClosePrinter(hprinter)
                    if status == 0:  # 0 berarti siap
                        return printer_name
                except:
                    continue
            return None
        except Exception as e:
            st.error(f"Error checking printers: {e}")
            return None
    else:
        st.warning("Fitur cetak lokal hanya tersedia di sistem operasi Windows.")
        return None

def print_pdf_to_ready_printer(pdf_path):
    if os.name == 'nt':
        try:
            import win32print
            import win32api
        except ImportError:
            st.error("Modul 'pywin32' tidak ditemukan. Harap instal dengan `pip install pywin32`.")
            return False

        printer_name = get_ready_printer()
        if not printer_name:
            st.error("Tidak ada printer READY yang ditemukan.")
            return False
        try:
            win32api.ShellExecute(0, "print", pdf_path, f'/d:"{printer_name}"', ".", 0)
            return True
        except Exception as e:
            st.error(f"Gagal memanggil fungsi cetak: {e}. Pastikan PyWin32 terinstal dan printer siap.")
            return False
    else:
        st.warning("Fitur cetak lokal hanya tersedia di sistem operasi Windows.")
        return False

def show_pdf_preview(pdf_path):
    with open(pdf_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode("utf-8")
        
        width_inches = 11.0
        height_inches = 9.5
        
        width_px = int(width_inches * 96)
        height_px = int(height_inches * 96)
        
        pdf_display = f'<embed src="data:application/pdf;base64,{base64_pdf}" width="{width_px}px" height="{height_px}px" type="application/pdf">'
        
        st.markdown(pdf_display, unsafe_allow_html=True)


st.title("🚛 Aplikasi Surat Jalan dan Slip Penimbangan")
st.markdown("---")

# --- SCHEDULER UNTUK LAPORAN HARIAN ---
def send_daily_report():
    """Mengirim laporan harian otomatis ke Telegram"""
    today = datetime.now().date()
    query = "SELECT * FROM surat_jalan WHERE tanggal_input LIKE ?"
    try:
        laporan_df = pd.read_sql_query(query, conn, params=[f"{today}%"])
    except:
        # Jika terjadi error, coba lagi dengan koneksi baru
        conn = sqlite3.connect('surat_jalan.db', check_same_thread=False)
        laporan_df = pd.read_sql_query(query, conn, params=[f"{today}%"])
    
    if not laporan_df.empty:
        total_kendaraan = laporan_df['nomor_polisi'].nunique()
        total_netto = laporan_df['netto'].sum()
        
        telegram_message = f"📊 <b>LAPORAN HARIAN {today.strftime('%d/%m/%Y')}</b>\n\n"
        telegram_message += f"<b>Total Kendaraan:</b> {total_kendaraan}\n"
        telegram_message += f"<b>Total Netto:</b> {format_angka(total_netto)} kg\n\n"
        telegram_message += "<b>Detail Transaksi:</b>\n"
        
        # Tambahkan 5 transaksi terbaru
        for _, row in laporan_df.head(5).iterrows():
            telegram_message += f"• {row['nomor_do']} | {row['nomor_polisi']} | {row['nama_sopir']} | {format_angka(row['netto'])} kg\n"
        
        if len(laporan_df) > 5:
            telegram_message += f"\n<i>+ {len(laporan_df) - 5} transaksi lainnya...</i>"
        
        telegram_message += f"\n\n<i>Dikirim otomatis pada: {datetime.now().strftime('%H:%M:%S')}</i>"
        
        send_telegram_message(telegram_message)

# Inisialisasi scheduler
if not hasattr(st, 'scheduler') and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    try:
            jakarta = timezone("Asia/Jakarta")  # gunakan timezone dari pytz
            st.scheduler = BackgroundScheduler(timezone=jakarta)
            st.scheduler.add_job(send_daily_report, 'cron', hour=17, minute=0)
            st.scheduler.start()
            st.sidebar.success("Scheduler laporan harian diaktifkan (setiap jam 17:00 WIB)")
    except Exception as e:
            st.sidebar.error(f"Gagal memulai scheduler: {e}")

# Bagian Input Data
st.header("📝 Input Data Surat Jalan Baru")
with st.form("form_surat_jalan", clear_on_submit=True):
    col1, col2 = st.columns(2)
    
    with col1:
        tanggal_masuk = st.date_input("Tanggal Masuk", value=datetime.today().date())
        jam_masuk = st.time_input("Jam Masuk", value=datetime.now().time()).strftime("%H:%M")
        nomor_do = st.text_input("Nomor DO / Slip", value=f"{tanggal_masuk.strftime('%d%m%Y')}-{jam_masuk.replace(':', '')}", disabled=True)
        nomor_polisi = st.text_input("Nomor Polisi", placeholder="Contoh: B 1234 ABC")
        nama_barang = st.text_input("Nama Barang", placeholder="Contoh: Pasir, Batu Split")
    
    with col2:
        tanggal_keluar = st.date_input("Tanggal Keluar", value=datetime.today().date())
        jam_keluar = st.time_input("Jam Keluar", value=datetime.now().time()).strftime("%H:%M")
        nama_sopir = st.text_input("Nama Sopir", placeholder="Contoh: Budi Santoso")
        po_do = st.text_input("PO / DO", placeholder="Contoh: PO2023001")
        transport = st.text_input("Transport", placeholder="Contoh: PT. Angkut Jaya")
    
    col_bruto, col_tara, col_netto = st.columns(3)
    with col_bruto:
        bruto = st.number_input("Timbangan I / Bruto (kg)", min_value=0.0, step=1.0, format="%.0f")
    with col_tara:
        tara = st.number_input("Timbangan II / Tara (kg)", min_value=0.0, step=1.0, format="%.0f")
    with col_netto:
        netto = bruto - tara
        st.metric("NETTO (kg)", format_angka(netto))

    # --- INPUT FORM TANDA TANGAN BARU ---
    st.subheader("Informasi Tanda Tangan")
    col_ttd1, col_ttd2 = st.columns(2)
    with col_ttd1:
        nama_ditimbang = st.text_input("Nama Ditimbang", value="[Nama Operator Timbang]", help="Nama Petugas yang melakukan penimbangan.")
    with col_ttd2:
        nama_diterima = st.text_input("Nama Diterima", help="Nama Petugas yang menerima barang.")
    
    nama_diketahui = ""

    st.markdown("---")
    submitted = st.form_submit_button("💾 Simpan Data Surat Jalan")
    if submitted:
        if not nomor_polisi or not nama_sopir or not nama_barang:
            st.error("🚨 Nomor Polisi, Nama Sopir, dan Nama Barang wajib diisi!")
        elif bruto <= tara:
            st.error("🚨 Bruto harus lebih besar dari Tara!")
        else:
            tanggal_input = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                c.execute('''
                    INSERT INTO surat_jalan (
                        tanggal_masuk, jam_masuk, tanggal_keluar, jam_keluar, nomor_do,
                        nomor_polisi, nama_sopir, nama_barang, po_do, transport,
                        bruto, tara, netto, tanggal_input,
                        nama_ditimbang, nama_diterima, nama_diketahui
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(tanggal_masuk), jam_masuk, str(tanggal_keluar), jam_keluar, nomor_do,
                    nomor_polisi, nama_sopir, nama_barang, po_do, transport,
                    bruto, tara, netto, tanggal_input,
                    nama_ditimbang, nama_diterima, nama_diketahui
                ))
                conn.commit()
                
                # Kirim notifikasi Telegram
                telegram_message = f"📝 <b>INPUT DATA BARU</b>\n\n"
                telegram_message += f"<b>Nomor DO:</b> {nomor_do}\n"
                telegram_message += f"<b>Tanggal Masuk:</b> {tanggal_masuk} {jam_masuk}\n"
                telegram_message += f"<b>Nomor Polisi:</b> {nomor_polisi}\n"
                telegram_message += f"<b>Sopir:</b> {nama_sopir}\n"
                telegram_message += f"<b>Barang:</b> {nama_barang}\n"
                telegram_message += f"<b>Netto:</b> {format_angka(netto)} kg\n\n"
                telegram_message += f"<i>Dikirim pada: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
                
                if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
                    if send_telegram_message(telegram_message):
                        st.success("✅ Data berhasil disimpan dan notifikasi terkirim ke Telegram.")
                    else:
                        st.success("✅ Data berhasil disimpan, tetapi gagal mengirim notifikasi Telegram.")
                else:
                    st.success("✅ Data berhasil disimpan. (Token Telegram tidak dikonfigurasi)")
                
                st.rerun()
            except Exception as e:
                st.error(f"❌ Terjadi kesalahan saat menyimpan data: {e}")

st.markdown("---")

# Bagian Riwayat Data
st.header("📚 Riwayat Data Surat Jalan")
col_search1, col_search2 = st.columns(2)
with col_search1:
    search_nopol = st.text_input("Cari berdasarkan Nomor Polisi", placeholder="Contoh: B 1234 ABC")
with col_search2:
    search_do = st.text_input("Cari berdasarkan Nomor DO", placeholder="Contoh: DO12345")

query = "SELECT * FROM surat_jalan WHERE 1=1"
params = []
if search_nopol:
    query += " AND nomor_polisi LIKE ?"
    params.append(f"%{search_nopol}%")
if search_do:
    query += " AND nomor_do LIKE ?"
    params.append(f"%{search_do}%")

query += " ORDER BY tanggal_input DESC"

result_df = pd.read_sql_query(query, conn, params=params).set_index('id')

if not result_df.empty:
    st.dataframe(result_df, use_container_width=True)

    # Fitur Edit Data dengan expander
    st.subheader("⚙️ Edit Data")
    selected_id_edit = st.selectbox("Pilih ID untuk Edit:", result_df.index.tolist(), key="select_id_edit")
    selected_row_edit = result_df.loc[selected_id_edit]
    
    with st.expander(f"Buka Form Edit Data ID: {selected_id_edit}"):
        with st.form(f"edit_form_{selected_id_edit}"):
            col_edit1, col_edit2 = st.columns(2)
            with col_edit1:
                edit_tanggal_masuk = st.date_input("Tanggal Masuk", value=datetime.strptime(selected_row_edit['tanggal_masuk'], "%Y-%m-%d").date(), key=f"edit_tgl_masuk_{selected_id_edit}")
                jam_masuk_value = selected_row_edit['jam_masuk']
                if len(jam_masuk_value) > 5:
                    jam_masuk_value = jam_masuk_value[:5]
                edit_jam_masuk = st.time_input("Jam Masuk", value=datetime.strptime(jam_masuk_value, "%H:%M").time()).strftime("%H:%M")
                
                edit_nomor_do = st.text_input("Nomor DO / Slip", value=selected_row_edit['nomor_do'], key=f"edit_do_{selected_id_edit}")
                edit_nomor_polisi = st.text_input("Nomor Polisi", value=selected_row_edit['nomor_polisi'], key=f"edit_nopol_{selected_id_edit}")
                edit_nama_barang = st.text_input("Nama Barang", value=selected_row_edit['nama_barang'], key=f"edit_barang_{selected_id_edit}")
            
            with col_edit2:
                edit_tanggal_keluar = st.date_input("Tanggal Keluar", value=datetime.strptime(selected_row_edit['tanggal_keluar'], "%Y-%m-%d").date(), key=f"edit_tgl_keluar_{selected_id_edit}")
                jam_keluar_value = selected_row_edit['jam_keluar']
                if len(jam_keluar_value) > 5:
                    jam_keluar_value = jam_keluar_value[:5]
                edit_jam_keluar = st.time_input("Jam Keluar", value=datetime.strptime(jam_keluar_value, "%H:%M").time()).strftime("%H:%M")
                
                edit_nama_sopir = st.text_input("Nama Sopir", value=selected_row_edit['nama_sopir'], key=f"edit_sopir_{selected_id_edit}")
                edit_po_do = st.text_input("PO / DO", value=selected_row_edit['po_do'], key=f"edit_podo_{selected_id_edit}")
                edit_transport = st.text_input("Transport", value=selected_row_edit['transport'], key=f"edit_transport_{selected_id_edit}")
            
            col_edit_bruto, col_edit_tara, col_edit_netto = st.columns(3)
            with col_edit_bruto:
                edit_bruto = st.number_input("Timbangan I / Bruto (kg)", min_value=0.0, value=float(selected_row_edit['bruto']), step=1.0, format="%.0f", key=f"edit_bruto_{selected_id_edit}")
            with col_edit_tara:
                edit_tara = st.number_input("Timbangan II / Tara (kg)", min_value=0.0, value=float(selected_row_edit['tara']), step=1.0, format="%.0f", key=f"edit_tara_{selected_id_edit}")
            with col_edit_netto:
                edit_netto = edit_bruto - edit_tara
                st.metric("NETTO (kg)", format_angka(edit_netto))
            
            # --- INPUT FORM TANDA TANGAN PADA SAAT EDIT ---
            st.subheader("Informasi Tanda Tangan (Edit)")
            col_edit_ttd1, col_edit_ttd2 = st.columns(2)
            with col_edit_ttd1:
                edit_nama_ditimbang = st.text_input("Nama Ditimbang", value=selected_row_edit.get('nama_ditimbang', ''), key=f"edit_nama_ditimbang_{selected_id_edit}")
            with col_edit_ttd2:
                edit_nama_diterima = st.text_input("Nama Diterima", value=selected_row_edit.get('nama_diterima', ''), key=f"edit_nama_diterima_{selected_id_edit}")
            
            edit_nama_diketahui = selected_row_edit.get('nama_diketahui', '')

            updated = st.form_submit_button("🔄 Update Data")
            if updated:
                if not edit_nomor_polisi or not edit_nama_sopir or not edit_nama_barang:
                    st.error("🚨 Nomor Polisi, Nama Sopir, dan Nama Barang wajib diisi!")
                elif edit_bruto <= edit_tara:
                    st.error("🚨 Bruto harus lebih besar dari Tara!")
                else:
                    try:
                        c.execute('''
                            UPDATE surat_jalan SET
                                tanggal_masuk = ?, jam_masuk = ?, tanggal_keluar = ?, jam_keluar = ?,
                                nomor_do = ?, nomor_polisi = ?, nama_sopir = ?, nama_barang = ?,
                                po_do = ?, transport = ?, bruto = ?, tara = ?, netto = ?,
                                nama_ditimbang = ?, nama_diterima = ?, nama_diketahui = ?
                            WHERE id = ?
                        ''', (
                            str(edit_tanggal_masuk), edit_jam_masuk, str(edit_tanggal_keluar), edit_jam_keluar,
                            edit_nomor_do, edit_nomor_polisi, edit_nama_sopir, edit_nama_barang,
                            edit_po_do, edit_transport, edit_bruto, edit_tara, edit_netto,
                            edit_nama_ditimbang, edit_nama_diterima, edit_nama_diketahui,
                            selected_id_edit
                        ))
                        conn.commit()
                        st.success("✅ Data berhasil diupdate!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Terjadi kesalahan saat mengupdate data: {e}")

    # Fitur Hapus Data per Nomor DO
    st.subheader("🗑️ Hapus Data per Nomor DO")
    do_list = result_df['nomor_do'].sort_values(ascending=False).unique().tolist()
    
    if do_list:
        selected_do_to_delete = st.selectbox(
            "Pilih Nomor DO untuk dihapus:", 
            do_list, 
            key="select_do_to_delete"
        )
        st.warning(f"⚠️ **PERINGATAN:** Menghapus data untuk Nomor DO '{selected_do_to_delete}' akan menghapus entri tersebut.")
        
        if st.button(f"🚨 Hapus Data untuk '{selected_do_to_delete}'", key="delete_do_btn"):
            try:
                c.execute("DELETE FROM surat_jalan WHERE nomor_do = ?", (selected_do_to_delete,))
                conn.commit()
                st.success(f"✅ Data untuk Nomor DO '{selected_do_to_delete}' berhasil dihapus.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Terjadi kesalahan saat menghapus data: {e}")
    else:
        st.info("Tidak ada Nomor DO untuk dihapus.")

    # Preview dan Cetak PDF
    st.header("🖨️ Opsi Ekspor & Cetak")
    
    max_index = len(result_df) - 1
    if max_index < 0:
        st.warning("Tidak ada data untuk diekspor atau dicetak.")
    else:
        selected_index = st.number_input(
            "Pilih nomor baris (dari tabel di atas) untuk ekspor dan cetak:", 
            min_value=0, 
            max_value=max_index, 
            value=0,
            step=1, 
            key="select_row_for_export"
        )
        if 0 <= selected_index <= max_index:
            selected_row = result_df.iloc[int(selected_index)]

            col_preview_pdf, col_print_local, col_download_single, col_download_batch, col_download_split = st.columns(5) 

            # Fungsi untuk menyiapkan data untuk PDF (agar tidak duplikasi kode)
            def prepare_pdf_data(row_data):
                return {
                    **row_data.to_dict(), 
                    'nama_sopir_ttd': row_data['nama_sopir'],
                    'nama_ditimbang_ttd': row_data.get('nama_ditimbang', ''),
                    'nama_diterima_ttd': row_data.get('nama_diterima', ''),
                    'nama_diketahui_ttd': row_data.get('nama_diketahui', '')
                }

            with col_preview_pdf:
                if st.button("👁️ Preview PDF", key="preview_pdf_btn"): 
                    pdf = PDF()
                    pdf.add_page()
                    pdf.add_data(prepare_pdf_data(selected_row))
                    
                    output_path = os.path.join(TEMP_PDF_DIR, f"surat_jalan_{selected_row.name}.pdf")
                    pdf.output(output_path)
                    
                    st.subheader("Tampilan Preview PDF")
                    show_pdf_preview(output_path)
                    st.success("Tampilan PDF berhasil dibuat.")

            with col_print_local:
                if st.button("🖨️ Cetak", key=f"print_local_btn_{selected_row.name}"):
                    output_path_print = os.path.join(TEMP_PDF_DIR, f"surat_jalan_{selected_row.name}.pdf")
                    if not os.path.exists(output_path_print):
                        pdf = PDF()
                        pdf.add_page()
                        pdf.add_data(prepare_pdf_data(selected_row))
                        pdf.output(output_path_print)

                    if print_pdf_to_ready_printer(output_path_print):
                        st.success("Berhasil dikirim ke printer (dari server Streamlit, hanya untuk Windows Lokal)!")
                    else:
                        st.error("Gagal mencetak. Pastikan aplikasi berjalan di Windows, PyWin32 terinstal, dan printer siap.")

            with col_download_single: 
                output_path_download = os.path.join(TEMP_PDF_DIR, f"surat_jalan_{selected_row.name}.pdf")
                if not os.path.exists(output_path_download):
                    pdf = PDF()
                    pdf.add_page()
                    pdf.add_data(prepare_pdf_data(selected_row))
                    pdf.output(output_path_download)

                with open(output_path_download, "rb") as f:
                    st.download_button(
                        label="⬇️ Unduh PDF",
                        data=f.read(),
                        file_name=f"surat_jalan_{selected_row.name}.pdf",
                        mime="application/pdf",
                        key=f"download_single_pdf_{selected_row.name}"
                    )

            with col_download_batch: 
                if st.button("⬇️Semua PDF", key="download_batch_pdf_btn"):
                    pdf = PDF()
                    output_path_batch = os.path.join(TEMP_PDF_DIR, "batch_surat_jalan.pdf")
                    with st.spinner("Membuat PDF Continuous..."):
                        if pdf.generate_batch_pdf(result_df.reset_index(), output_path_batch): 
                            with open(output_path_batch, "rb") as f:
                                st.download_button("Klik untuk Unduh PDF Continuous", f, file_name="batch_surat_jalan.pdf", mime="application/pdf")
                            st.success("✅ PDF Continuous berhasil dibuat dan siap diunduh.")
                        else:
                            st.error("❌ Gagal membuat PDF Continuous.")

            with col_download_split: 
                if st.button("⬇️Unduh/Nopol", key="download_split_pdf_btn"):
                    pdf = PDF()
                    with st.spinner("Membuat PDF terpisah..."):
                        file_paths = pdf.generate_split_pdfs(result_df.reset_index(), by="nomor_polisi")
                    if file_paths:
                        st.success("✅ PDF terpisah berhasil dibuat. Silakan unduh satu per satu di bawah:")
                        for path in file_paths:
                            with open(path, "rb") as f:
                                st.download_button(f"Unduh: {os.path.basename(path)}", f, file_name=os.path.basename(path), mime="application/pdf", key=f"download_split_{os.path.basename(path)}")
                    else:
                        st.warning("⚠️ Tidak ada PDF terpisah yang dibuat.")
        else:
            st.warning("Pilih baris yang valid dari tabel di atas untuk opsi ekspor/cetak.")

else:
    st.info("Tidak ada data riwayat yang ditemukan. Silakan masukkan data baru.")

st.markdown("---")

# Laporan Harian
st.header("📊 Laporan Harian")
tanggal_laporan = st.date_input("Pilih Tanggal Laporan", value=datetime.today().date(), key="tanggal_laporan_input")
laporan_df = pd.read_sql_query("SELECT * FROM surat_jalan WHERE tanggal_input LIKE ?", conn, params=[f"{tanggal_laporan}%"])

# Tombol kirim manual
if st.button("📤 Kirim Laporan ke Telegram", key="send_report_btn"):
    with st.spinner("Menyiapkan laporan..."):
        if not laporan_df.empty:
            total_kendaraan = laporan_df['nomor_polisi'].nunique()
            total_netto = laporan_df['netto'].sum()
            
            telegram_message = f"📊 <b>LAPORAN HARIAN {tanggal_laporan.strftime('%d/%m/%Y')}</b>\n\n"
            telegram_message += f"<b>Total Kendaraan:</b> {total_kendaraan}\n"
            telegram_message += f"<b>Total Netto:</b> {format_angka(total_netto)} kg\n\n"
            telegram_message += "<b>Detail Transaksi:</b>\n"
            
            for _, row in laporan_df.iterrows():
                telegram_message += f"• {row['nomor_do']} | {row['nomor_polisi']} | {row['nama_sopir']} | {format_angka(row['netto'])} kg\n"
            
            telegram_message += f"\n\n<i>Dikirim manual pada: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            
            if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
                if send_telegram_message(telegram_message):
                    st.success("✅ Laporan harian berhasil dikirim ke Telegram!")
                else:
                    st.error("❌ Gagal mengirim laporan ke Telegram.")
            else:
                st.error("❌ Token atau Chat ID Telegram belum dikonfigurasi!")
        else:
            st.warning("Tidak ada data untuk dikirim.")

if not laporan_df.empty:
    total_kendaraan = laporan_df['nomor_polisi'].nunique()
    total_netto = laporan_df['netto'].sum()
    
    st.subheader("Ringkasan Harian")
    col_k, col_n = st.columns(2)
    with col_k:
        st.metric("Total Kendaraan Unik", total_kendaraan)
    with col_n:
        st.metric("Total Netto (kg)", format_angka(total_netto))
    
    st.dataframe(laporan_df.set_index('id'), use_container_width=True)
else:
    st.info("Tidak ada data untuk laporan pada tanggal ini.")

st.markdown("---")
st.caption("Aplikasi Surat Jalan & Slip Penimbangan v1.0 | Dibuat Oleh Ridwan Melba")