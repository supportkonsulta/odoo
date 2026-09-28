"""Penyeragaman potongan payload dari server Presenly SaaS.

Server mengirim relasi sebagai objek bersarang dengan bentuk yang sedikit
berbeda-beda: pegawai selalu `{id, nopeg, name}`, shift `{id, name}`, proyek
`{id, code, name}`. Helper di sini menyeragamkannya sekali, supaya setiap model
cermin tidak mengulang pemeriksaan tipe dan penanganan nilai kosong.
"""


def parse_date(value):
    """Tanggal dari API berbentuk `YYYY-MM-DD`.

    Kalau server mengirim ISO lengkap dengan jam, jamnya dibuang: kolomnya
    `fields.Date`, jadi menyimpan waktunya hanya akan menyesatkan.
    """
    if not value:
        return False
    teks = str(value).strip()
    return teks[:10] if len(teks) >= 10 else teks


def person_ref(ref):
    """Pegawai atau penyetuju: `{id, nopeg, name}`."""
    if not isinstance(ref, dict):
        return {}
    return {
        'id': int(ref.get('id') or 0),
        'nopeg': ref.get('nopeg') or False,
        'name': ref.get('name') or False,
    }


def named_ref(ref, key='name'):
    """Objek bernama (shift, tipe cuti, lokasi, proyek).

    `key` dipakai untuk proyek, yang mengirim namanya sebagai `name` tetapi
    kodenya sebagai `code`.
    """
    if not isinstance(ref, dict):
        return {}
    return {
        'id': int(ref.get('id') or 0),
        'name': ref.get(key) or False,
    }
