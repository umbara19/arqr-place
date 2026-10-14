# ARQR Place · Tiffany & Co.

Taruh animasi 3D 6 produk **Tiffany & Co.** di ruanganmu (lantai, meja, atau pojok ruangan)
lewat kamera HP. **Tanpa QR, tanpa install aplikasi.**

**Website:** https://umbara19.github.io/arqr-place/

| HP | Teknologi AR | File |
|---|---|---|
| iPhone / iPad | AR Quick Look (bawaan iOS) | `models/*.usdz` |
| Android | Scene Viewer / WebXR | `models/*.glb` |
| Laptop | Pratinjau 3D (putar & zoom) + QR untuk membuka di HP | `models/*.glb` |

Versi scan-QR (MindAR) tetap ada di https://umbara19.github.io/arqr-brands/.

## Cara kerja
1. Model diekspor dari project Unity (`ARQR → WebAR → Export GLB`) lalu disalin ke `source/`.
2. `tools/bake.html` merekam animasi idle tiap produk (loop 8 detik, 30 fps) menjadi GLB beranimasi di `models/`.
3. `tools/glb_to_usdz.py` mengubah GLB beranimasi menjadi USDZ untuk iPhone (butuh `pip install usd-core numpy`).
4. `tools/thumbs.html` membuat thumbnail di `img/`.

Jalankan alat-alat di atas lewat `python Tools/place_server.py` (folder project Unity), lalu buka `http://localhost:8081/tools/...`.

Model 3D-nya adalah prototipe bergaya untuk tugas kuliah, bukan model resmi brand.
