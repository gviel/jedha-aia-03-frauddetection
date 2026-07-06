import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from config import ALERT_EMAIL, FRAUD_THRESHOLD, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER


def send_fraud_alert_email(**context):
    """Envoie un email d'alerte fraude (SMTP configuré via Variables Airflow)."""
    ti     = context["ti"]
    result = json.loads(ti.xcom_pull(task_ids="fraud_detect", key="fraud_result"))

    score     = result["fraud_score"]
    trans_num = result["trans_num"]
    amt       = result.get("amt", "?")
    merchant  = result.get("merchant", "?")
    category  = result.get("category", "?")

    subject = f"[ALERTE FRAUDE] {trans_num} — score {score:.2%}"
    body = (
        f"ALERTE DE FRAUDE DÉTECTÉE\n\n"
        f"Transaction  : {trans_num}\n"
        f"Montant      : {amt} USD\n"
        f"Marchand     : {merchant}\n"
        f"Catégorie    : {category}\n"
        f"Score fraude : {score:.4f} ({score:.2%})\n"
        f"Seuil        : {FRAUD_THRESHOLD}\n"
        f"Détection    : {datetime.utcnow().isoformat()} UTC\n"
    )
    print(subject)
    print(body)

    if ALERT_EMAIL and SMTP_USER:
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"]    = SMTP_USER
            msg["To"]      = ALERT_EMAIL
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as srv:
                srv.starttls()
                srv.login(SMTP_USER, SMTP_PASSWORD)
                srv.sendmail(SMTP_USER, [ALERT_EMAIL], msg.as_string())
            print(f"[fraud_alert] Email envoyé à {ALERT_EMAIL}")
        except Exception as exc:
            print(f"[fraud_alert] WARN email : {exc}")
    else:
        print("[fraud_alert] Email non configuré (SMTP_USER ou FRAUD_ALERT_EMAIL manquant).")
