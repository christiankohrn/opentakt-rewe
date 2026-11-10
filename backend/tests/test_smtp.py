from app.config import get_settings
from app.smtp_datei import smtp_speichern


def test_passwort_wird_nur_geschrieben(tmp_path, monkeypatch):
    datei = tmp_path / "buchhaltung.env"
    datei.write_text("BUCHHALTUNG_PASSWORD=bleibt\nSMTP_HOST=alt\nSMTP_PASSWORD=geheim\n", encoding="utf-8")
    monkeypatch.setenv("BUCHHALTUNG_ENV_DATEI", str(datei))
    settings = get_settings()
    vorher = (
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_user,
        settings.smtp_password,
        settings.smtp_from,
        settings.smtp_tls,
    )
    try:
        ohne = smtp_speichern("mail.example", 587, "konto", "a@b.example", True, "")
        text = datei.read_text(encoding="utf-8")
        assert "BUCHHALTUNG_PASSWORD=bleibt\n" in text
        assert "SMTP_PASSWORD=geheim\n" in text
        assert "SMTP_HOST=mail.example\n" in text
        assert "passwort" not in ohne
        assert "geheim" not in str(ohne)
        mit = smtp_speichern("mail.example", 587, "konto", "a@b.example", True, "neues-test-passwort")
        text = datei.read_text(encoding="utf-8")
        assert "SMTP_PASSWORD=neues-test-passwort\n" in text
        assert "SMTP_PASSWORD=geheim" not in text
        assert "BUCHHALTUNG_PASSWORD=bleibt\n" in text
        assert "passwort" not in mit
        assert mit["passwort_gesetzt"] is True
    finally:
        (
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_user,
            settings.smtp_password,
            settings.smtp_from,
            settings.smtp_tls,
        ) = vorher
