# backend/src/templates/campaign_invitation_email_template.py
"""
Templates HTML pour les emails d'invitation aux campagnes (parties prenantes internes)
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


def get_campaign_invitation_email_html(
    recipient_name: str,
    recipient_role: str,
    campaign_name: str,
    client_name: str,
    start_date: str,
    end_date: str,
    framework_name: str,
    campaign_url: str,
    sender_name: str = "L'equipe CYBERGARD AI"
) -> str:
    """
    Template HTML pour l'email d'invitation a une campagne (parties prenantes internes)

    Args:
        recipient_name: Nom complet du destinataire (Prenom Nom)
        recipient_role: Role dans la campagne (Chef de projet / Auditeur interne / Contributeur)
        campaign_name: Nom de la campagne
        client_name: Nom du client/organisation
        start_date: Date de debut de la campagne
        end_date: Date de fin de la campagne
        framework_name: Nom du referentiel (ISO 27001 / RGPD / NIS2)
        campaign_url: URL d'acces a la campagne (lien classique, pas Magic Link)
        sender_name: Nom de l'expediteur

    Returns:
        str: HTML formate pour l'email d'invitation
    """
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Invitation a participer a la campagne d'audit</title>
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
                Invitation a participer a une campagne
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                Campagne d'audit de conformite
            </p>
        </div>

        <!-- Contenu principal -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{recipient_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Vous etes invite a rejoindre la campagne d'audit de conformite
                <strong style="color: #ffffff;">"{campaign_name}"</strong>, organisee par
                <strong style="color: #ffffff;">{client_name}</strong> sur la plateforme CYBERGARD AI.
            </p>

            <p style="margin: 0 0 24px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                En tant que <strong style="color: #fbbf24;">{recipient_role}</strong>, vous etes invite a
                collaborer a la preparation et au suivi de cette evaluation. Votre implication permettra
                d'assurer le bon deroulement de la campagne et la qualite des analyses realisees.
            </p>

            <!-- Bloc informations cles -->
            <div style="background: #374151; border-radius: 6px; padding: 20px; margin: 24px 0; border: 1px solid #4b5563;">
                <h3 style="margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: #ffffff;">
                    📋 Informations cles sur la campagne
                </h3>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📅 <strong style="color: #ffffff;">Debut :</strong> {start_date}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    🏁 <strong style="color: #ffffff;">Fin :</strong> {end_date}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📚 <strong style="color: #ffffff;">Referentiel :</strong> {framework_name}
                </div>
                <div style="margin: 0; font-size: 14px; color: #d1d5db;">
                    👤 <strong style="color: #ffffff;">Votre role :</strong> <span style="color: #fbbf24; font-weight: 600;">{recipient_role}</span>
                </div>
            </div>

            <!-- Bouton CTA principal -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{campaign_url}"
                   style="display: inline-block;
                          padding: 16px 40px;
                          background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 16px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);">
                    Acceder a la campagne
                </a>
            </div>

            <!-- Note importante -->
            <div style="background: rgba(234, 179, 8, 0.1); border-radius: 6px; padding: 16px; margin: 24px 0; border: 1px solid rgba(234, 179, 8, 0.3);">
                <p style="margin: 0; font-size: 14px; color: #fde68a; line-height: 1.6;">
                    ⚠️ <strong>Important :</strong> Vous devez vous connecter avec vos identifiants CYBERGARD AI habituels.
                    Si vous n'avez pas encore active votre compte, veuillez le faire avant d'acceder a la campagne.
                </p>
            </div>

            <!-- A savoir -->
            <div style="background: #374151; border-radius: 6px; padding: 16px; margin: 24px 0; border: 1px solid #4b5563;">
                <h4 style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: #ffffff;">
                    💡 A savoir :
                </h4>
                <ul style="margin: 0; padding-left: 20px; font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <li>✅ Vos actions et commentaires sont enregistres automatiquement.</li>
                    <li>🔄 Vous pouvez revenir a tout moment pour suivre l'avancement ou ajouter vos observations.</li>
                    <li>🔒 Toutes les donnees sont confidentielles et accessibles uniquement aux personnes autorisees.</li>
                    <li>🔔 Vous recevrez des notifications pour les evenements importants de la campagne.</li>
                </ul>
            </div>

            <!-- Lien de secours -->
            <div style="background: #374151; border-radius: 6px; padding: 16px; margin: 24px 0; border: 1px solid #4b5563;">
                <p style="margin: 0 0 8px 0; font-size: 13px; color: #9ca3af;">
                    🔗 <strong>Le bouton ne fonctionne pas ?</strong><br>
                    Copiez ce lien et collez-le dans votre navigateur :
                </p>
                <div style="background: #374151; border: 1px solid #4b5563; border-radius: 4px; padding: 12px; margin-top: 8px;">
                    <code style="font-family: 'Courier New', Courier, monospace; font-size: 12px; color: #93c5fd; word-break: break-all;">
                        {campaign_url}
                    </code>
                </div>
            </div>
        </div>

        <!-- Footer -->
        <div style="text-align: center; padding: 24px 30px; background: #1a202c; border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 8px 0; font-size: 14px; color: #d1d5db;">
                Merci pour votre engagement dans cette campagne.
            </p>
            <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: white;">
                {sender_name}
            </p>
            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                La plateforme intelligente de gestion des audits et plans d'action.
            </p>
        </div>

    </div>

    <!-- Copyright -->
    <div style="text-align: center; padding: 20px;">
        <p style="margin: 0; font-size: 11px; color: rgba(255, 255, 255, 0.5);">
            &copy; 2025 CYBERGARD AI. Tous droits reserves.
        </p>
    </div>

</body>
</html>"""


def get_campaign_invitation_email_subject(campaign_name: str, client_name: str) -> str:
    """
    Genere l'objet de l'email d'invitation a la campagne

    Args:
        campaign_name: Nom de la campagne
        client_name: Nom du client

    Returns:
        str: Objet de l'email
    """
    return f"Invitation a participer a la campagne d'audit de {client_name}"


def get_campaign_invitation_email_text(
    recipient_name: str,
    recipient_role: str,
    campaign_name: str,
    client_name: str,
    start_date: str,
    end_date: str,
    framework_name: str,
    campaign_url: str,
    sender_name: str = "L'equipe CYBERGARD AI"
) -> str:
    """
    Version texte brut de l'email d'invitation (fallback pour clients email sans HTML)

    Returns:
        str: Texte brut de l'email
    """
    return f"""Bonjour {recipient_name},

Vous etes invite a rejoindre la campagne d'audit de conformite "{campaign_name}", organisee par {client_name} sur la plateforme CYBERGARD AI.

En tant que {recipient_role}, vous etes invite a collaborer a la preparation et au suivi de cette evaluation.
Votre implication permettra d'assurer le bon deroulement de la campagne et la qualite des analyses realisees.

INFORMATIONS CLES SUR LA CAMPAGNE
----------------------------------
Debut : {start_date}
Fin : {end_date}
Referentiel : {framework_name}

ACCEDER A MON ESPACE D'AUDIT
-----------------------------
Cliquez sur le lien ci-dessous pour acceder a votre espace securise :
{campaign_url}

Important : Vous devez vous connecter avec vos identifiants CYBERGARD AI habituels.

A SAVOIR :
- Vos actions et commentaires sont enregistres automatiquement.
- Vous pouvez revenir a tout moment pour suivre l'avancement ou ajouter vos observations.
- Toutes les donnees sont confidentielles et accessibles uniquement aux personnes autorisees.
- Vous recevrez des notifications pour les evenements importants de la campagne.

Merci pour votre engagement dans cette campagne.
{sender_name}
La plateforme intelligente de gestion des audits et plans d'action.

---
CYBERGARD AI - 2025
"""
