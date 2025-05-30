# 🚛 Aplikasi Surat Jalan & Slip Penimbangan

Aplikasi berbasis [Streamlit](https://streamlit.io/) untuk mencatat dan mengelola **Surat Jalan** dan **Slip Penimbangan** dengan fitur cetak PDF, laporan harian otomatis, dan notifikasi Telegram.

---

## ✨ Fitur Utama

- 📥 Input & edit data surat jalan
- 📑 Ekspor PDF individual, batch, atau per-nomor polisi
- 🖨️ Cetak langsung ke printer lokal (khusus Windows)
- 🔁 Backup otomatis database SQLite
- 📊 Laporan harian otomatis/manual via Telegram
- 🔍 Pencarian riwayat berdasarkan Nomor Polisi / DO

---

## 📦 Struktur Proyek

.
├── app.py
├── utils/
│   └── pdf_generator.py
├── temp_pdf/              # Output PDF sementara
├── backup/                # Backup database otomatis
├── surat_jalan.db         # Database SQLite
└── .streamlit/
    └── secrets.toml       # Konfigurasi rahasia



https://github.com/otoh47/ONE_SISTEM.git
