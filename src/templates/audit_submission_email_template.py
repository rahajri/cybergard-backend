# backend/src/templates/audit_submission_email_template.py
"""
Templates HTML pour les emails de notification apres soumission d'un audit
Trois types de destinataires :
- Audite (confirmation de soumission)
- Auditeur (notification de revue disponible)
- Chef de projet (mise a jour du statut)
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


# =============================================================================
# EMAIL POUR L'AUDITE (Confirmation de soumission)
# =============================================================================

def get_audite_submission_email_html(
    audite_name: str,
    campaign_name: str,
    client_name: str,
    submission_date: str,
    total_questions: int,
    answered_questions: int,
    framework_name: str
) -> str:
    """
    Template HTML pour l'email de confirmation de soumission envoye a l'Audite

    Args:
        audite_name: Nom de l'audite (Prenom Nom)
        campaign_name: Nom de la campagne
        client_name: Nom du client/organisation
        submission_date: Date et heure de soumission
        total_questions: Nombre total de questions
        answered_questions: Nombre de questions repondues
        framework_name: Nom du referentiel

    Returns:
        str: HTML formate pour l'email de confirmation
    """
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Confirmation de soumission de votre audit</title>
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

        <!-- Section titre avec succes -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <div style="width: 60px; height: 60px; margin: 0 auto 16px; background: linear-gradient(135deg, #16a34a 0%, #15803d 100%); border-radius: 50%; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 24px rgba(22, 163, 74, 0.4);">
                <span style="font-size: 32px;">✅</span>
            </div>
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Soumission confirmee !
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                Votre audit a ete soumis avec succes
            </p>
        </div>

        <!-- Contenu principal -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{audite_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Nous vous confirmons que vos reponses pour la campagne d'audit
                <strong style="color: #ffffff;">"{campaign_name}"</strong> ont ete soumises avec succes.
            </p>

            <!-- Bloc resume de soumission -->
            <div style="background: #374151; border-radius: 6px; padding: 20px; margin: 24px 0; border: 1px solid #4b5563;">
                <h3 style="margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: #ffffff;">
                    📊 Resume de votre soumission
                </h3>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📝 <strong style="color: #ffffff;">Campagne :</strong> {campaign_name}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    🏢 <strong style="color: #ffffff;">Client :</strong> {client_name}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📚 <strong style="color: #ffffff;">Referentiel :</strong> {framework_name}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📅 <strong style="color: #ffffff;">Date de soumission :</strong> {submission_date}
                </div>
                <div style="margin: 0; font-size: 14px; color: #d1d5db;">
                    ✅ <strong style="color: #ffffff;">Questions repondues :</strong> <span style="color: #34d399; font-weight: 600;">{answered_questions}/{total_questions}</span>
                </div>
            </div>

            <!-- Message de suivi -->
            <div style="background: rgba(59, 130, 246, 0.1); border-radius: 6px; padding: 16px; margin: 24px 0; border: 1px solid rgba(59, 130, 246, 0.3);">
                <p style="margin: 0; font-size: 14px; color: #93c5fd; line-height: 1.6;">
                    ℹ️ <strong>Prochaines etapes :</strong><br>
                    Vos reponses vont maintenant etre analysees par l'equipe d'audit. Vous serez informe des prochaines etapes et des eventuels besoins de clarification.
                </p>
            </div>

            <!-- Remerciements -->
            <p style="margin: 24px 0 0 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Merci pour votre participation et votre contribution a cette evaluation de conformite.
                Votre engagement est essentiel pour assurer la securite et la conformite de votre organisation.
            </p>
        </div>

        <!-- Footer -->
        <div style="text-align: center; padding: 24px 30px; background: #1a202c; border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 8px 0; font-size: 14px; color: #d1d5db;">
                Merci pour votre confiance.
            </p>
            <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: white;">
                L'equipe CYBERGARD AI
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


def get_audite_submission_email_subject(campaign_name: str) -> str:
    """Genere l'objet de l'email de confirmation pour l'Audite"""
    return f"Confirmation : Votre audit '{campaign_name}' a ete soumis avec succes"


def get_audite_submission_email_text(
    audite_name: str,
    campaign_name: str,
    client_name: str,
    submission_date: str,
    total_questions: int,
    answered_questions: int,
    framework_name: str
) -> str:
    """Version texte brut de l'email de confirmation"""
    return f"""Bonjour {audite_name},

CONFIRMATION DE SOUMISSION
===========================

Nous vous confirmons que vos reponses pour la campagne d'audit "{campaign_name}" ont ete soumises avec succes.

RESUME DE VOTRE SOUMISSION
---------------------------
Campagne : {campaign_name}
Client : {client_name}
Referentiel : {framework_name}
Date de soumission : {submission_date}
Questions repondues : {answered_questions}/{total_questions}

PROCHAINES ETAPES
-----------------
Vos reponses vont maintenant etre analysees par l'equipe d'audit. Vous serez informe des prochaines etapes et des eventuels besoins de clarification.

Merci pour votre participation et votre contribution a cette evaluation de conformite. Votre engagement est essentiel pour assurer la securite et la conformite de votre organisation.

Merci pour votre confiance.
L'equipe CYBERGARD AI
La plateforme intelligente de gestion des audits et plans d'action.

---
CYBERGARD AI - 2025
"""


# =============================================================================
# EMAIL POUR L'AUDITEUR (Notification de revue disponible)
# =============================================================================

def get_auditeur_submission_email_html(
    auditeur_name: str,
    audite_name: str,
    campaign_name: str,
    client_name: str,
    submission_date: str,
    total_questions: int,
    answered_questions: int,
    framework_name: str,
    review_url: str
) -> str:
    """
    Template HTML pour l'email de notification envoye a l'Auditeur

    Args:
        auditeur_name: Nom de l'auditeur (Prenom Nom)
        audite_name: Nom de l'audite qui a soumis
        campaign_name: Nom de la campagne
        client_name: Nom du client/organisation
        submission_date: Date et heure de soumission
        total_questions: Nombre total de questions
        answered_questions: Nombre de questions repondues
        framework_name: Nom du referentiel
        review_url: URL pour acceder a la revue

    Returns:
        str: HTML formate pour l'email de notification
    """
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nouvelle soumission a evaluer</title>
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

        <!-- Section titre avec notification -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <div style="width: 60px; height: 60px; margin: 0 auto 16px; background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); border-radius: 50%; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 24px rgba(245, 158, 11, 0.4);">
                <span style="font-size: 32px;">🔔</span>
            </div>
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Nouvelle soumission a evaluer
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                Un audit vous attend pour revue
            </p>
        </div>

        <!-- Contenu principal -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{auditeur_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                <strong style="color: #fbbf24;">{audite_name}</strong> a soumis ses reponses pour la campagne d'audit
                <strong style="color: #ffffff;">"{campaign_name}"</strong>. Les donnees sont maintenant disponibles pour votre evaluation.
            </p>

            <!-- Bloc informations de la soumission -->
            <div style="background: #374151; border-radius: 6px; padding: 20px; margin: 24px 0; border: 1px solid #4b5563;">
                <h3 style="margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: #ffffff;">
                    📋 Details de la soumission
                </h3>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    👤 <strong style="color: #ffffff;">Soumis par :</strong> <span style="color: #fbbf24;">{audite_name}</span>
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📝 <strong style="color: #ffffff;">Campagne :</strong> {campaign_name}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    🏢 <strong style="color: #ffffff;">Client :</strong> {client_name}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📚 <strong style="color: #ffffff;">Referentiel :</strong> {framework_name}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📅 <strong style="color: #ffffff;">Date de soumission :</strong> {submission_date}
                </div>
                <div style="margin: 0; font-size: 14px; color: #d1d5db;">
                    ✅ <strong style="color: #ffffff;">Questions completees :</strong> <span style="color: #34d399; font-weight: 600;">{answered_questions}/{total_questions}</span>
                </div>
            </div>

            <!-- Bouton CTA principal -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{review_url}"
                   style="display: inline-block;
                          padding: 16px 40px;
                          background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 16px;
                          box-shadow: 0 4px 12px rgba(245, 158, 11, 0.3);">
                    Commencer l'evaluation
                </a>
            </div>

            <!-- Actions attendues -->
            <div style="background: #374151; border-radius: 6px; padding: 16px; margin: 24px 0; border: 1px solid #4b5563;">
                <h4 style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: #ffffff;">
                    📝 Actions attendues :
                </h4>
                <ul style="margin: 0; padding-left: 20px; font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <li>🔍 Examiner les reponses fournies par l'audite</li>
                    <li>✅ Valider ou demander des clarifications si necessaire</li>
                    <li>📊 Evaluer le niveau de conformite pour chaque domaine</li>
                    <li>📋 Documenter vos observations et recommandations</li>
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
                        {review_url}
                    </code>
                </div>
            </div>
        </div>

        <!-- Footer -->
        <div style="text-align: center; padding: 24px 30px; background: #1a202c; border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 8px 0; font-size: 14px; color: #d1d5db;">
                Merci pour votre implication.
            </p>
            <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: white;">
                L'equipe CYBERGARD AI
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


def get_auditeur_submission_email_subject(campaign_name: str, audite_name: str) -> str:
    """Genere l'objet de l'email de notification pour l'Auditeur"""
    return f"Action requise : {audite_name} a soumis son audit pour '{campaign_name}'"


def get_auditeur_submission_email_text(
    auditeur_name: str,
    audite_name: str,
    campaign_name: str,
    client_name: str,
    submission_date: str,
    total_questions: int,
    answered_questions: int,
    framework_name: str,
    review_url: str
) -> str:
    """Version texte brut de l'email de notification pour l'Auditeur"""
    return f"""Bonjour {auditeur_name},

NOUVELLE SOUMISSION A EVALUER
==============================

{audite_name} a soumis ses reponses pour la campagne d'audit "{campaign_name}". Les donnees sont maintenant disponibles pour votre evaluation.

DETAILS DE LA SOUMISSION
-------------------------
Soumis par : {audite_name}
Campagne : {campaign_name}
Client : {client_name}
Referentiel : {framework_name}
Date de soumission : {submission_date}
Questions completees : {answered_questions}/{total_questions}

COMMENCER L'EVALUATION
-----------------------
Cliquez sur le lien ci-dessous pour acceder aux reponses :
{review_url}

ACTIONS ATTENDUES
-----------------
- Examiner les reponses fournies par l'audite
- Valider ou demander des clarifications si necessaire
- Evaluer le niveau de conformite pour chaque domaine
- Documenter vos observations et recommandations

Merci pour votre implication.
L'equipe CYBERGARD AI
La plateforme intelligente de gestion des audits et plans d'action.

---
CYBERGARD AI - 2025
"""


# =============================================================================
# EMAIL POUR LE CHEF DE PROJET (Mise a jour du statut)
# =============================================================================

def get_chef_projet_submission_email_html(
    chef_projet_name: str,
    audite_name: str,
    campaign_name: str,
    client_name: str,
    submission_date: str,
    total_questions: int,
    answered_questions: int,
    framework_name: str,
    campaign_url: str,
    total_audites: int = 1,
    submitted_audites: int = 1
) -> str:
    """
    Template HTML pour l'email de notification envoye au Chef de projet

    Args:
        chef_projet_name: Nom du chef de projet (Prenom Nom)
        audite_name: Nom de l'audite qui a soumis
        campaign_name: Nom de la campagne
        client_name: Nom du client/organisation
        submission_date: Date et heure de soumission
        total_questions: Nombre total de questions
        answered_questions: Nombre de questions repondues
        framework_name: Nom du referentiel
        campaign_url: URL pour acceder au dashboard de la campagne
        total_audites: Nombre total d'audites dans la campagne
        submitted_audites: Nombre d'audites ayant soumis

    Returns:
        str: HTML formate pour l'email de notification
    """
    progress_percentage = int((submitted_audites / total_audites) * 100) if total_audites > 0 else 0

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mise a jour de la campagne d'audit</title>
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

        <!-- Section titre avec info -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <div style="width: 60px; height: 60px; margin: 0 auto 16px; background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); border-radius: 50%; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 24px rgba(59, 130, 246, 0.4);">
                <span style="font-size: 32px;">📊</span>
            </div>
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Mise a jour de la campagne
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                Nouvelle soumission recue
            </p>
        </div>

        <!-- Contenu principal -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{chef_projet_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Nous vous informons que <strong style="color: #fbbf24;">{audite_name}</strong> a soumis ses reponses
                pour la campagne d'audit <strong style="color: #ffffff;">"{campaign_name}"</strong>.
            </p>

            <!-- Bloc progression globale -->
            <div style="background: #374151; border-radius: 6px; padding: 20px; margin: 24px 0; border: 1px solid #4b5563;">
                <h3 style="margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: #ffffff;">
                    📈 Progression de la campagne
                </h3>
                <div style="margin: 0 0 16px 0;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-size: 14px; color: #d1d5db;">Audites ayant soumis</span>
                        <span style="font-size: 14px; color: #34d399; font-weight: 600;">{submitted_audites}/{total_audites}</span>
                    </div>
                    <div style="background: #4b5563; border-radius: 4px; height: 8px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, #10b981 0%, #059669 100%); height: 100%; width: {progress_percentage}%; transition: width 0.3s ease;"></div>
                    </div>
                    <div style="text-align: right; margin-top: 4px;">
                        <span style="font-size: 12px; color: #9ca3af;">{progress_percentage}% complete</span>
                    </div>
                </div>
            </div>

            <!-- Bloc details de la soumission -->
            <div style="background: #374151; border-radius: 6px; padding: 20px; margin: 24px 0; border: 1px solid #4b5563;">
                <h3 style="margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: #ffffff;">
                    📋 Details de cette soumission
                </h3>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    👤 <strong style="color: #ffffff;">Audite :</strong> <span style="color: #fbbf24;">{audite_name}</span>
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    🏢 <strong style="color: #ffffff;">Client :</strong> {client_name}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📚 <strong style="color: #ffffff;">Referentiel :</strong> {framework_name}
                </div>
                <div style="margin: 0 0 10px 0; font-size: 14px; color: #d1d5db;">
                    📅 <strong style="color: #ffffff;">Date de soumission :</strong> {submission_date}
                </div>
                <div style="margin: 0; font-size: 14px; color: #d1d5db;">
                    ✅ <strong style="color: #ffffff;">Questions repondues :</strong> <span style="color: #34d399; font-weight: 600;">{answered_questions}/{total_questions}</span>
                </div>
            </div>

            <!-- Bouton CTA principal -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{campaign_url}"
                   style="display: inline-block;
                          padding: 16px 40px;
                          background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 16px;
                          box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);">
                    Voir le tableau de bord
                </a>
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
                Bonne gestion de votre campagne.
            </p>
            <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: white;">
                L'equipe CYBERGARD AI
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


def get_chef_projet_submission_email_subject(campaign_name: str, audite_name: str) -> str:
    """Genere l'objet de l'email de notification pour le Chef de projet"""
    return f"Campagne '{campaign_name}' : {audite_name} a soumis son audit"


def get_chef_projet_submission_email_text(
    chef_projet_name: str,
    audite_name: str,
    campaign_name: str,
    client_name: str,
    submission_date: str,
    total_questions: int,
    answered_questions: int,
    framework_name: str,
    campaign_url: str,
    total_audites: int = 1,
    submitted_audites: int = 1
) -> str:
    """Version texte brut de l'email de notification pour le Chef de projet"""
    progress_percentage = int((submitted_audites / total_audites) * 100) if total_audites > 0 else 0

    return f"""Bonjour {chef_projet_name},

MISE A JOUR DE LA CAMPAGNE
============================

Nous vous informons que {audite_name} a soumis ses reponses pour la campagne d'audit "{campaign_name}".

PROGRESSION DE LA CAMPAGNE
---------------------------
Audites ayant soumis : {submitted_audites}/{total_audites} ({progress_percentage}% complete)

DETAILS DE CETTE SOUMISSION
----------------------------
Audite : {audite_name}
Client : {client_name}
Referentiel : {framework_name}
Date de soumission : {submission_date}
Questions repondues : {answered_questions}/{total_questions}

VOIR LE TABLEAU DE BORD
------------------------
Cliquez sur le lien ci-dessous pour acceder au tableau de bord de la campagne :
{campaign_url}

Bonne gestion de votre campagne.
L'equipe CYBERGARD AI
La plateforme intelligente de gestion des audits et plans d'action.

---
CYBERGARD AI - 2025
"""
