from fpdf import FPDF
import pandas as pd
import os

def format_angka(value):
    """Format angka dengan titik sebagai pemisah ribuan"""
    return f"{int(value):,}".replace(",", ".")

class PDF(FPDF):
    def __init__(self):
        super().__init__(orientation="L", unit="mm", format=(279.4, 241.3))  # Kertas 11 x 9.5 inci
        self.set_margins(left=12.7, top=10, right=12.7)

        font_dir = "fonts"
        if not os.path.exists(font_dir):
            os.makedirs(font_dir)

        try:
            self.add_font("Calibri", "", os.path.join(font_dir, "calibri.ttf"))
            self.add_font("Calibri", "B", os.path.join(font_dir, "calibrib.ttf"))
        except Exception as e:
            print(f"Gagal memuat font Calibri: {e}. Pastikan file .ttf ada di folder 'fonts'.")
            self.add_font("Courier", "", "font/courier.ttf")
            self.add_font("Courier", "B", "font/courierbd.ttf")

    def header(self):
        self.set_font("Calibri", "B", 12)
        self.cell(0, 7, "SURAT JALAN", ln=True, align="C")
        self.set_font("Calibri", "B", 12)
        self.cell(0, 7, "BUKTI SLIP PENIMBANGAN", ln=True, align="C")
        self.ln(2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def add_data(self, row):
        self.set_font("Calibri", "", 12)
        self.ln(4)

        x_kiri_label = 15
        x_kiri_colon = 60
        x_kiri_val = 65
        x_kanan_label_start = 150

        def row_both(label_left, val_left, label_right=None, val_right=None):
            # Kolom kiri
            self.set_x(x_kiri_label)
            self.cell(x_kiri_colon - x_kiri_label, 6, label_left, border=0)
            self.cell(x_kiri_val - x_kiri_colon, 6, ":", border=0)
            self.cell(60, 6, str(val_left), border=0)

            # Kolom kanan: Penyesuaian untuk jarak titik dua
            if label_right:
                self.set_x(x_kanan_label_start)
                label_cell_width = 30 
                self.cell(label_cell_width, 6, label_right, align="R", border=0)
                
                # UBAH INI: Menggunakan lebar 3mm untuk ": "
                self.cell(3, 6, ": ", border=0) # Lebih dekat lagi
                
                self.cell(35, 6, format_angka(val_right), align="R", border=0)
            self.ln(6)

        # Cetak sesuai format
        row_both("TANGGAL MASUK / JAM", f"{row['tanggal_masuk']}   {row['jam_masuk']}")
        row_both("TANGGAL KELUAR / JAM", f"{row['tanggal_keluar']}   {row['jam_keluar']}",
                 "Timbangan I / Bruto", row['bruto'])
        row_both("NOMOR DO / SLIP", row['nomor_do'],
                 "Timbangan II / Tara", row['tara'])
        row_both("NOMOR POLISI", row['nomor_polisi'],
                 "Netto", row['netto'])
        row_both("NAMA SOPIR", row['nama_sopir'])
        row_both("NAMA BARANG", row['nama_barang'])
        row_both("PO / DO", row['po_do'])
        row_both("TRANSPORT", row['transport'])

        self.ln(4)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(10)

        # Tanda tangan
        self.set_font("Calibri", "", 12)
        ttd_labels = ["Ditimbang,", "Sopir,", "Diterima,", "Diketahui,"]
        ttd_width = (self.w - self.l_margin - self.r_margin) / 4

        for label in ttd_labels:
            self.cell(ttd_width, 6, label, align="C")
        self.ln(20)

        self.cell(ttd_width, 6, f"({row.get('nama_ditimbang_ttd', ''):^15})", align="C")
        self.cell(ttd_width, 6, f"({row.get('nama_sopir_ttd', ''):^15})", align="C")
        self.cell(ttd_width, 6, f"({row.get('nama_diterima_ttd', ''):^15})", align="C")
        self.cell(ttd_width, 6, f"({row.get('nama_diketahui_ttd', ''):^15})", align="C")
        self.ln(10)

    def generate_batch_pdf(self, dataframe, output_path):
        try:
            for _, row in dataframe.iterrows():
                data_for_pdf = {
                    **row.to_dict(),
                    'nama_sopir_ttd': row['nama_sopir'],
                    'nama_ditimbang_ttd': row.get('nama_ditimbang', ''),
                    'nama_diterima_ttd': row.get('nama_diterima', ''),
                    'nama_diketahui_ttd': row.get('nama_diketahui', '')
                }
                self.add_page()
                self.add_data(data_for_pdf)
            self.output(output_path)
            return True
        except Exception as e:
            print(f"Error generating batch PDF: {str(e)}")
            return False

    def generate_split_pdfs(self, dataframe, by="nomor_polisi"):
        file_paths = []
        for group_name, group_df in dataframe.groupby(by):
            temp_pdf = PDF()
            output_path = os.path.join("temp_pdf", f"surat_jalan_{group_name.replace(' ', '_')}.pdf")
            try:
                for _, row in group_df.iterrows():
                    data_for_pdf = {
                        **row.to_dict(),
                        'nama_sopir_ttd': row['nama_sopir'],
                        'nama_ditimbang_ttd': row.get('nama_ditimbang', ''),
                        'nama_diterima_ttd': row.get('nama_diterima', ''),
                        'nama_diketahui_ttd': row.get('nama_diketahui', '')
                    }
                    temp_pdf.add_page()
                    temp_pdf.add_data(data_for_pdf)
                temp_pdf.output(output_path)
                file_paths.append(output_path)
            except Exception as e:
                print(f"Error generating split PDF for {group_name}: {str(e)}")
        return file_paths