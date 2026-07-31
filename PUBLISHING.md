# Haze — Yayınlama Rehberi

GitHub push → Release oluşturma → AUR submit adımlarının tamamı.

---

## İçindekiler

1. [Ön Hazırlık](#1-ön-hazırlık)
2. [GitHub'a İlk Push](#2-githuba-ilk-push)
3. [Yeni Versiyon Release Oluşturma](#3-yeni-versiyon-release-oluşturma)
4. [PKGBUILD Yazımı](#4-pkgbuild-yazımı)
5. [AUR'a Submit / Güncelleme](#5-aura-submit--güncelleme)
6. [Versiyon Güncelleme Özet Akışı](#6-versiyon-güncelleme-özet-akışı)

---

## 1. Ön Hazırlık

### GitHub SSH key

```bash
# Key yoksa oluştur
ssh-keygen -t ed25519 -C "mail@example.com"

# Public key'i kopyala
cat ~/.ssh/id_ed25519.pub
```

GitHub → Settings → SSH and GPG keys → **New SSH key** → yapıştır.

Bağlantıyı test et:

```bash
ssh -T git@github.com
# Hi kullanici-adi! You've successfully authenticated...
```

### AUR SSH key

AUR ayrı bir SSH key kullanır (aynı key'i kullanabilirsin ama ayrı tutmak daha temizdir).

```bash
ssh-keygen -t ed25519 -C "aur" -f ~/.ssh/id_ed25519_aur
cat ~/.ssh/id_ed25519_aur.pub
```

[aur.archlinux.org](https://aur.archlinux.org) → My Account → **SSH Public Key** → yapıştır.

`~/.ssh/config` dosyasına ekle:

```
Host aur.archlinux.org
    IdentityFile ~/.ssh/id_ed25519_aur
    User aur
```

Test:

```bash
ssh -T aur@aur.archlinux.org
# Welcome to the AUR, kullanici-adi! ...
```

---

## 2. GitHub'a İlk Push

### Repo oluşturma

GitHub → **New repository** → isim: `Haze` → Public → **Create** (README/license ekleme, zaten var).

### Yerel repo'yu bağla ve push et

```bash
cd ~/Projects/Anonymity/haze

# Remote ekle
git remote add origin git@github.com:KULLANICI_ADI/Haze.git

# Branch adını main yap (gerekiyorsa)
git branch -M main

# Push
git push -u origin main
```

### İlk tag'i oluştur

Tag olmadan GitHub release ve AUR source URL'si çalışmaz.

```bash
git tag v2.0.0
git push origin v2.0.0
```

---

## 3. Yeni Versiyon Release Oluşturma

Her yeni versiyon için şu adımları izle:

### Adım 1 — Kodu hazırla

```bash
# pyproject.toml içindeki version'ı güncelle
# version = "2.1.0"

# Commit et
git add .
git commit -m "Release v2.1.0: ..."
git push origin main
```

### Adım 2 — Tag oluştur ve push et

```bash
git tag v2.1.0
git push origin v2.1.0
```

### Adım 3 — GitHub Release oluştur

**Web arayüzü ile:**

1. Repo sayfası → **Releases** → **Draft a new release**
2. **Choose a tag** → `v2.1.0` seç
3. Release title: `v2.1.0`
4. Description: değişiklik notlarını yaz
5. **Publish release**

**GitHub CLI ile (daha hızlı):**

```bash
gh release create v2.1.0 \
  --title "v2.1.0" \
  --notes "Değişiklik notları burada"
```

### Adım 4 — sha256sum hesapla

AUR PKGBUILD için sha256sum'a ihtiyaç var. Release tag push'landıktan sonra:

```bash
curl -sL https://github.com/KULLANICI_ADI/Haze/archive/refs/tags/v2.1.0.tar.gz \
  | sha256sum
```

Çıkan değeri PKGBUILD'deki `sha256sums` alanına yaz.

---

## 4. PKGBUILD Yazımı

### Dosya yapısı

AUR için gereken iki dosya:

```
haze-aur/
├── PKGBUILD    ← build tarifi
└── .SRCINFO    ← PKGBUILD'den otomatik üretilir
```

### PKGBUILD anatomisi

```bash
# ── 1. Meta bilgiler ──────────────────────────────────────────────────
# Maintainer: Ad Soyad <mail@example.com>
pkgname=haze                          # paket adı (AUR'daki URL ile aynı olmalı)
pkgver=2.0.0                          # upstream versiyon
pkgrel=1                              # AUR paket revizyonu (sadece PKGBUILD değişince artar)
pkgdesc="Kısa açıklama"
arch=('x86_64')                       # desteklenen mimariler; saf Python ise 'any'
url="https://github.com/..."
license=('GPL-3.0-only')

# ── 2. Bağımlılıklar ──────────────────────────────────────────────────
makedepends=(                         # sadece build sırasında lazım olanlar
    'python-setuptools'
    'python-wheel'
)
depends=(                             # runtime'da lazım olanlar
    'python>=3.11'
    'tor'
    'portaudio'
)

# ── 3. Kaynak ─────────────────────────────────────────────────────────
source=("$pkgname-$pkgver.tar.gz::https://github.com/.../archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('buraya_gercek_sha256_degeri')

# ── 4. Build ──────────────────────────────────────────────────────────
build() {
    cd "Haze-${pkgver}"
    # derleme / paketleme hazırlığı burada yapılır
}

# ── 5. Package ────────────────────────────────────────────────────────
package() {
    # dosyaları $pkgdir altına koy; pacman buradan sisteme kopyalar
    # $pkgdir = paketin sanal kök dizini, örn: $pkgdir/usr/bin/haze
}
```

### Önemli kurallar

| Kural | Açıklama |
|-------|----------|
| `$pkgdir` | Paketin sanal kökü. Tüm dosyalar buraya, `/` görevi görür. |
| `$srcdir` | İndirilen ve açılan kaynak dosyalarının olduğu dizin. |
| `install -Dm755` | Dosyayı kopyala + parent dizinleri oluştur + izin ver. |
| `pkgrel` | Sadece PKGBUILD değiştiğinde (upstream değil) artır. |
| `options=('!strip')` | Binary strip'lemeyi kapat — Python venv'leri için gerekli. |

### Python venv tabanlı paket örüntüsü

Bağımlılıkları sistem Python'una kurmak yerine `/opt/paket/venv` altına bundle'lamak:

```bash
build() {
    cd "Proje-${pkgver}"

    # 1. Bağımsız venv oluştur
    python -m venv "${srcdir}/venv"
    "${srcdir}/venv/bin/pip" install --upgrade pip --quiet
    "${srcdir}/venv/bin/pip" install . --quiet

    # 2. Build-time path'leri hedef path ile değiştir
    #    (venv script'lerinin shebang'ları srcdir'e hardcode olur)
    grep -rlI "${srcdir}/venv" "${srcdir}/venv/bin/" \
        | xargs -r sed -i "s|${srcdir}/venv|/opt/haze/venv|g"
    sed -i "s|${srcdir}/venv|/opt/haze/venv|g" \
        "${srcdir}/venv/pyvenv.cfg"

    # 3. Python'un Unicode easter-egg symlink'ini temizle
    #    (bsdtar bunu paketleyemez, uyarı verir)
    find "${srcdir}/venv/bin/" -name '*𝜋*' -delete
}

package() {
    # Venv'i /opt/haze/venv altına koy
    install -dm755 "${pkgdir}/opt/haze"
    cp -a "${srcdir}/venv" "${pkgdir}/opt/haze/venv"

    # /usr/bin'e wrapper launcher yaz
    install -Dm755 /dev/stdin "${pkgdir}/usr/bin/haze" <<'EOF'
#!/usr/bin/env bash
exec /opt/haze/venv/bin/haze "$@"
EOF
}
```

### sha256sums güncelleme kısayolu

```bash
# PKGBUILD içindeki sha'yı 'SKIP' yapıp makepkg'ye hesaplat:
updpkgsums

# ya da elle:
curl -sL "SOURCE_URL" | sha256sum
# çıktıyı sha256sums=('...') alanına yapıştır
```

### .SRCINFO üretme

`.SRCINFO` elle yazılmaz, PKGBUILD'den üretilir:

```bash
makepkg --printsrcinfo > .SRCINFO
```

**Her PKGBUILD değişikliğinden sonra çalıştır.**

---

## 5. AUR'a Submit / Güncelleme

### İlk kez submit (yeni paket)

AUR'da paket yokken boş bir repo clone'lanır:

```bash
git clone ssh://aur@aur.archlinux.org/haze.git ~/Projects/Anonymity/haze-aur
cd ~/Projects/Anonymity/haze-aur
```

PKGBUILD ve .SRCINFO'yu kopyala:

```bash
cp /path/to/PKGBUILD .
makepkg --printsrcinfo > .SRCINFO
```

Commit ve push:

```bash
git add PKGBUILD .SRCINFO
git commit -m "Initial release v2.0.0"
git push origin master
```

> AUR'da `master` branch kullanılır, `main` değil.

### Mevcut paketi güncelleme

```bash
cd ~/Projects/Anonymity/haze-aur

# PKGBUILD'i düzenle: pkgver, pkgrel, sha256sums

# .SRCINFO yenile
makepkg --printsrcinfo > .SRCINFO

# Yerel test (isteğe bağlı ama önerilir)
makepkg -si

# Push
git add PKGBUILD .SRCINFO
git commit -m "Upgrade to v2.1.0"
git push origin master
```

### Sık yapılan hatalar

| Hata | Çözüm |
|------|-------|
| `.SRCINFO` güncel değil | Her değişiklikten sonra `makepkg --printsrcinfo > .SRCINFO` |
| sha256sum yanlış | `updpkgsums` veya elle hesapla |
| `pkgrel` sıfırlanmadı | Yeni upstream versiyonda `pkgrel=1` olmalı |
| AUR'da `main` push | `git push origin master` kullan |
| SSH key tanınmıyor | `~/.ssh/config`'de `aur.archlinux.org` kaydı var mı kontrol et |

---

## 6. Versiyon Güncelleme Özet Akışı

Yeni bir versiyon çıkardığında tek seferlik yapılacaklar:

```bash
# 1. Kaynak kodu güncelle
#    pyproject.toml → version = "X.Y.Z"
git add . && git commit -m "Release vX.Y.Z: ..."
git push origin main

# 2. Tag oluştur
git tag vX.Y.Z
git push origin vX.Y.Z

# 3. GitHub Release yayınla (web ya da CLI)
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."

# 4. sha256sum hesapla
curl -sL https://github.com/berk-kucuk/Haze/archive/refs/tags/vX.Y.Z.tar.gz | sha256sum

# 5. PKGBUILD güncelle
#    pkgver=X.Y.Z
#    pkgrel=1
#    sha256sums=('yeni_deger')

# 6. .SRCINFO yenile
cd ~/Projects/Anonymity/haze-aur
makepkg --printsrcinfo > .SRCINFO

# 7. AUR'a push
git add PKGBUILD .SRCINFO
git commit -m "Upgrade to vX.Y.Z"
git push origin master
```
