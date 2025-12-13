"""
Template d'email pour la relance de campagne d'audit
"""
from pathlib import Path


def _load_logo_base64():
    """Charge le logo depuis logo.txt et retourne la data URI complete"""
    logo_path = Path(__file__).parent.parent.parent.parent / "frontend" / "public" / "logo.txt"
    try:
        with open(logo_path, 'r') as f:
            base64_data = f.read().strip()
        return f"data:image/png;base64,{base64_data}"
    except Exception:
        return None


LOGO_DATA_URI = _load_logo_base64()

def get_campaign_reminder_email_html(
    audite_firstname: str,
    audite_lastname: str,
    referentiel_name: str,
    entity_name: str,
    magic_link: str,
    expiration_date: str
) -> str:
    """
    Génère le HTML de l'email de relance de campagne
    """
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relance – Accédez à votre audit</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                {'<img src="' + LOGO_DATA_URI + '" alt="CYBERGARD AI Logo" style="width: 100%; height: 100%; object-fit: contain;" />' if LOGO_DATA_URI else '<svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><path d="M9 12l2 2 4-4"></path></svg>'}
            </div>
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                🔄 Relance – Participation à votre audit
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                {referentiel_name}
            </p>
        </div>

        <!-- Contenu principal -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{audite_firstname} {audite_lastname}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Vous avez été invité à participer à l'audit de conformité <strong style="color: #ffffff;">{referentiel_name}</strong> pour l'entité <strong style="color: #ffffff;">{entity_name}</strong>.
            </p>

            <!-- Reminder box -->
            <div style="background: rgba(234, 179, 8, 0.1); border-radius: 6px; padding: 16px; margin: 24px 0; border: 1px solid rgba(234, 179, 8, 0.3);">
                <p style="margin: 0 0 8px 0; font-size: 15px; font-weight: 600; color: #fde68a;">
                    📊 Nous constatons que votre audit n'a pas encore été complété.
                </p>
                <p style="margin: 0; font-size: 14px; color: #fde68a; line-height: 1.6;">
                    Vous pouvez reprendre à tout moment votre questionnaire via le bouton ci-dessous :
                </p>
            </div>

            <!-- Bouton CTA principal -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{magic_link}"
                   style="display: inline-block;
                          padding: 16px 40px;
                          background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 16px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);">
                    🔄 Accéder à mon audit
                </a>
            </div>

            <!-- Info box stylée -->
            <div style="background: #374151; border-radius: 6px; padding: 20px; margin: 24px 0; border: 1px solid #4b5563;">
                <h3 style="margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: #ffffff;">
                    📌 Informations utiles
                </h3>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    ✓ <strong style="color: #ffffff;">Lien personnel</strong> : Ce lien est strictement personnel, unique et réservé à votre usage.
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    ✓ <strong style="color: #ffffff;">Validité du lien</strong> : Votre lien reste actif jusqu'au {expiration_date}.
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    ✓ <strong style="color: #ffffff;">Audit en plusieurs fois</strong> : Vous pouvez compléter votre audit progressivement, autant de fois que nécessaire.
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    ✓ <strong style="color: #ffffff;">Sauvegarde automatique</strong> : Vos réponses sont enregistrées en temps réel.
                </div>
                <div style="margin: 0; font-size: 14px; color: #d1d5db;">
                    ✓ <strong style="color: #ffffff;">Confidentialité</strong> : Vos données restent protégées et confidentielles.
                </div>
            </div>

            <!-- Lien de secours -->
            <div style="background: #374151; border-radius: 6px; padding: 16px; margin: 24px 0; border: 1px solid #4b5563;">
                <p style="margin: 0 0 8px 0; font-size: 13px; color: #9ca3af;">
                    🔗 <strong>Le bouton ne fonctionne pas ?</strong><br>
                    Copiez ce lien et collez-le dans votre navigateur :
                </p>
                <div style="background: #374151; border: 1px solid #4b5563; border-radius: 4px; padding: 12px; margin-top: 8px;">
                    <code style="font-family: 'Courier New', Courier, monospace; font-size: 12px; color: #93c5fd; word-break: break-all;">
                        {magic_link}
                    </code>
                </div>
            </div>

            <!-- Section aide -->
            <p style="margin: 24px 0 0 0; font-size: 14px; color: #d1d5db; line-height: 1.6;">
                <strong style="color: #ffffff;">Besoin d'aide ?</strong><br>
                Notre équipe support reste à votre disposition pour toute question concernant cet audit.
            </p>
            <p style="margin: 8px 0 0 0; font-size: 14px; color: #d1d5db;">
                📧 Email : <a href="mailto:support@cybergard.ai" style="color: #93c5fd; text-decoration: none;">support@cybergard.ai</a>
            </p>
        </div>

        <!-- Footer -->
        <div style="text-align: center; padding: 24px 30px; background: #1a202c; border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 8px 0; font-size: 14px; color: #d1d5db;">
                Merci pour votre engagement dans cette campagne.
            </p>
            <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: white;">
                L'équipe CYBERGARD AI
            </p>
            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                La plateforme intelligente de gestion des audits et plans d'action.
            </p>
        </div>

    </div>

    <!-- Copyright -->
    <div style="text-align: center; padding: 20px;">
        <p style="margin: 0; font-size: 11px; color: rgba(255, 255, 255, 0.5);">
            &copy; 2025 CYBERGARD AI. Tous droits réservés.
        </p>
    </div>

</body>
</html>"""


def get_campaign_reminder_email_text(
    audite_firstname: str,
    audite_lastname: str,
    referentiel_name: str,
    entity_name: str,
    magic_link: str,
    expiration_date: str
) -> str:
    """
    Génère la version texte de l'email de relance de campagne
    """
    return f"""CYBERGARD AI - Relance d'audit

Relance – Participation à votre audit
{referentiel_name}

Bonjour {audite_firstname} {audite_lastname},

Vous avez été invité à participer à l'audit de conformité {referentiel_name} pour l'entité {entity_name}.

📊 Nous constatons que votre audit n'a pas encore été complété.

Vous pouvez reprendre à tout moment votre questionnaire via ce lien :
{magic_link}

📌 Informations utiles

✓ Lien personnel : Ce lien est strictement personnel, unique et réservé à votre usage.
✓ Validité du lien : Votre lien reste actif jusqu'au {expiration_date}.
✓ Audit en plusieurs fois : Vous pouvez compléter votre audit progressivement, autant de fois que nécessaire.
✓ Sauvegarde automatique : Vos réponses sont enregistrées en temps réel.
✓ Confidentialité : Vos données restent protégées et confidentielles.

Besoin d'aide ?
Notre équipe support reste à votre disposition pour toute question concernant cet audit.

📧 Email : support@cybergard.ai

---
Cet email a été envoyé par CYBERGARD AI
Plateforme d'audit cybersécurité multi-référentiels
© 2025 CYBERGARD AI. Tous droits réservés.
"""


def get_campaign_reminder_email_subject(referentiel_name: str) -> str:
    """
    Génère le sujet de l'email de relance
    """
    return f"🔄 Relance – Accédez à votre audit {referentiel_name}"
