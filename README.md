# Vantrue GPS Extractor & Cloud Sync

Tool automatizat pentru extragerea metadatelor GPS, generarea traseelor GPX/manifest JSON și sincronizarea clipurilor video Vantrue direct în Cloud (Google Drive via rclone) cu optimizări avansate de performanță:
- **Zero SSD Write**: Prefetch asincron direct în RAM (`/dev/shm`) și încărcare direct în cloud pentru a proteja durata de viață a SSD-ului.
- **Background Prefetching Pipeline**: Clipurile următoare sunt citite și prelucrate în RAM în timp ce clipul curent se încarcă în cloud.
- **Checkpoint & Resume**: Reia automat transferurile întrerupte fără a reîncărca fișierele deja trimise.
- **Interfață TUI interactivă**: Selectare flexibilă a călătoriilor (trips) și gestionare automată a structurii pe luni/călătorii.

---

## ⚡ Configurare Google Drive (Evitare Rate Limiting / 403 Quota Exceeded)

Pentru a atinge viteze maxime de upload (fără limitări de apeluri API pe minut de la Google) și a evita pauzele lungi între clipuri, se recomandă folosirea propriului **Google Client ID & Secret** în `rclone`.

### 1. Creare Proiect & Activare API în Google Cloud Console
1. Accesează [Google Cloud Console](https://console.cloud.google.com/).
2. Creează un proiect nou (ex: `Vantrue-Sync`).
3. Mergi la **APIs & Services** -> **Enabled APIs & Services** -> apasă pe **+ Enable APIs and Services**.
4. Caută **Google Drive API** și apasă **Enable**.

### 2. Configurare OAuth Consent Screen & Test Users
1. În meniul din stânga, mergi la **APIs & Services** -> **OAuth consent screen** (sau **Google Auth Platform** -> **Audience** în noile interfețe Google Cloud).
2. Selectează **External** și apasă **Create**.
3. Completează numele aplicației (ex: `Vantrue Rclone`) și adresa ta de email la câmpurile obligatorii, apoi apasă **Save and Continue**.
4. La pasul **Scopes**, poți trece peste cu **Save and Continue**.
5. La pasul **Test users** (în interfața nouă: **Google Auth Platform** -> **Audience** -> **Test users**):
   - Apasă pe **+ Add Users**.
   - Adaugă adresa ta de Gmail (contul pe care îl vei folosi pentru Google Drive).
   - Apasă **Save**.

### 3. Generare Credentials (OAuth Client ID)
1. Mergi la **APIs & Services** -> **Credentials**.
2. Apasă pe **+ Create Credentials** -> **OAuth client ID**.
3. La **Application type**, alege **Desktop app** (evită *Web application* pentru a nu necesita configurare manuală de redirect URIs).
4. Setează un nume (ex: `Rclone Desktop`) și apasă **Create**.
5. Copiază valorile generate:
   - `Client ID`
   - `Client Secret`

### 4. Integrare în Rclone
Configurează sau editează remote-ul Google Drive în rclone:
```bash
rclone config
```
- Selectează remote-ul existent sau creează unul nou (`drive`).
- Când ești întrebat de `client_id`, lipește Client ID-ul tău generat.
- Când ești întrebat de `client_secret`, lipește Client Secret-ul tău generat.
- La `scope` alege `1` (Full access: `drive`).
- Urmează instrucțiunile din browser pentru autentificare (dacă apare ecranul *"Google hasn't verified this app"*, apasă pe **Advanced** -> **Go to application (unsafe)** și permite accesul).

---

## 🚀 Utilizare

### Cerințe de sistem
- Python 3.8+
- `rclone`
- `exiftool`

### Rulare Script
```bash
# Pornire ghidată (detectează automat cardul SD / USB și remote-urile rclone configurate)
python vantrue_sync.py

# Rulare directă cu parametri
python vantrue_sync.py --usb /cale/catre/sdcard --remote Google_Drive_Remote:FolderDestinatie --mode ram
```

### Argumente CLI disponibile
- `--usb`: Calea către rădăcina cardului SD Vantrue.
- `--remote`: Remote-ul rclone și calea destinație (ex: `my_drive:Dashcam`).
- `--mode`: Modul de operare: `ram` (Zero SSD Write cu prefetch în RAM) sau `direct` (streaming direct de pe SD).
- `--dry-run`: Simulează procesul fără a încărca fișiere.
- `--clear-checkpoint`: Resetează istoricul transferurilor pentru a reîncepe sincronizarea de la zero.
