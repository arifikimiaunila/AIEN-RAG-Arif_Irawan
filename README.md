```markdown
# Analytics Agent - RAG Demo / Show

> **Catatan:** Project ini ditujukan untuk **demo / show**, bukan untuk *production*. 
> Token masih bersifat statis, Neon menggunakan *free tier*, dan konfigurasi di bawah ini cukup menggunakan API key demo.

---

## Tahap Awal

### Langkah 1: Buat Akun Neon (Gratis)

1. Buka browser di HP / laptop: [https://neon.tech](https://neon.tech)
2. Klik **Sign Up** $\rightarrow$ pilih **Continue with GitHub / Google** agar lebih cepat (gunakan email kampus/utama).
3. **Jangan** masukkan kartu kredit, pilih **Free Plan**.

### Langkah 2: Buat Project Baru

1. Di dashboard Neon, klik **New Project**.
2. Isi parameter berikut:
   * **Project Name:** `AIEN-RAG-Arif_Irawan`
   * **Region:** `ap-southeast-1` (Singapore — paling dekat dari Indonesia & paling cepat)
   * **Postgres Version:** Biarkan *default* terbaru (`16` / `17`)
   * **Database Name:** `neondb`
3. Klik **Create Project**.
4. Setelah dibuat, langsung salin (*copy*) **Connection String** yang muncul. Contoh:

   ```bash
   postgresql://neondb_owner:xxxxxxxx@ep-xxx-ap-southeast-1.aws.neon.tech/neondb?sslmode=require

```

> **Catatan:** Simpan connection string ini. User dan password sudah terkandung di dalamnya, sehingga pada AI Agent tidak perlu melakukan pengaturan user/password secara terpisah. Cukup isikan ke variabel `RAG_DATABASE_URL` di file `.env`.

### Langkah 3: Clone Project

Buka terminal / command prompt, lalu jalankan:

```bash
git clone [https://github.com/arifikimiaunila/AIEN-RAG-Arif_Irawan.git](https://github.com/arifikimiaunila/AIEN-RAG-Arif_Irawan.git)
cd AIEN-RAG-Arif_Irawan

```

### Langkah 4: Siapkan File `.env`

Ubah nama `.env.example` menjadi `.env` dan masukkan API Key OpenAI Anda.

* **Linux / macOS:**
```bash
cp .env.example .env

```


* **Windows (PowerShell):**
```powershell
Copy-Item .env.example .env

```

Buka file `.env` yang baru dibuat, lalu sesuaikan isinya:

```env
# --- Neon ---
# Connection string dari Langkah 2 (sudah mencakup user, password, host, & database)
RAG_DATABASE_URL=postgresql://neondb_owner:xxxxxxxx@ep-xxx-ap-southeast-1.aws.neon.tech/neondb?sslmode=require

RAG_DATABASE_URL milik anda  perlu dimasukkan juga ke file connect_to_db.py, send_to_pg.py, dan db_set.py.

# --- Provider Model (OpenAI) ---
OPENAI_API_KEY=sk-isi-key-anda-di-sini
LLM_MODEL=gpt-6-luna

```

> **Informasi:** Tabel `gold.*` dan data awal tidak perlu dibuat secara manual. Skrip SQL akan terinstal secara otomatis saat perintah `docker compose up -d --build` dijalankan.

---

## Cara Menjalankan

Pilih instruksi sesuai dengan sistem operasi yang Anda gunakan:

### 1. Linux (Ubuntu)

```bash
# 1. Update paket & install dependencies
sudo apt update
sudo apt install -y python3-venv python3-pip

# 2. Masuk ke folder project
cd AIEN-RAG-Arif_Irawan

# 3. Buat dan aktifkan virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Jalankan container via Docker Compose
sudo docker compose up -d --build

```

* **Akses Browser:** Buka [http://localhost:8501/](http://localhost:8501/)

### 2. macOS

```bash
# 1. Install Homebrew (jika belum ada)
/bin/bash -c "$(curl -fsSL [https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh](https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh))"

# 2. Install Python 3.12 & Docker Desktop
brew install python@3.12
brew install --cask docker

# 3. Buka Docker Desktop (tunggu hingga statusnya Running / icon tidak berputar lagi)
open -a Docker

# 4. Masuk ke folder project & aktifkan venv
cd AIEN-RAG-Arif_Irawan
python3.12 -m venv .venv
source .venv/bin/activate

# 5. Jalankan Docker Compose (tanpa sudo)
docker compose up -d --build

```

* **Akses Browser:** Buka [http://localhost:8501/](http://localhost:8501/)

### 3. Windows (PowerShell)

```powershell
# 1. Install Python 3.12 & Docker Desktop (jika belum ada)
winget install Python.Python.3.12
winget install Docker.DockerDesktop

# Tutup PowerShell, buka PowerShell baru, lalu jalankan Docker Desktop.
# Tunggu hingga status Docker Desktop menunjukkan "Running".

# 2. Masuk ke folder project
cd AIEN-RAG-Arif_Irawan

# 3. Buat venv menggunakan Python 3.12
py -3.12 -m venv .venv

# 4. Izinkan script venv berjalan (hanya dilakukan sekali jika muncul error execution policy)
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 5. Aktivasi venv
.\.venv\Scripts\Activate.ps1

# 6. Jalankan Docker Compose
docker compose up -d --build

```

* **Akses Browser:** Buka [http://localhost:8501/](http://localhost:8501/)

---

## Keterbatasan Sistem (Demo / Show Only)

1. **Autentikasi Masih Demo:** Token bersifat statis, belum menggunakan standar OAuth / JWT production.
2. **Validasi SQL Sederhana:** Menggunakan pengecekan berbasis *prompt* + pencocokan *string* (Hanya mengizinkan query `SELECT`, maksimal 1 statement, serta menolak perintah `INSERT`, `UPDATE`, `DELETE`, atau `DROP`).
3. **Akses Role Gold Khusus Read-Only:** Koneksi ke Neon Gold terbatas hanya untuk membaca (`SELECT`) tabel `gold.shipment_fact`, `gold.carrier_daily`, dan `gold.city_daily`.
4. **Proteksi Endpoint Terbatas:** Endpoint `/healthz` dan `/ask-rag` belum dikunci secara ketat. **Jangan di-expose ke internet publik.**
5. **Potensi Kesalahan LLM:** SQL yang dihasilkan oleh LLM tidak langsung dieksekusi begitu saja; harus lolos lapisan pengaman (*guard check*) terlebih dahulu.
6. **Penanganan Input:** Input dari pengguna, data dari database, maupun output dari LLM seluruhnya diperlakukan sebagai *untrusted input*.
7. **Peruntukan Data Demo:** Menggunakan Neon *free tier* dengan data sampel sederhana, bukan data transaksi perbankan atau finansial riil.

```

```
