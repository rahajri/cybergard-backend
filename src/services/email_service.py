# backend/src/services/email_service.py
"""
Service d'envoi d'emails avec support Mailtrap
Utilise les templates séparés et les variables d'environnement
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import os
from dotenv import load_dotenv

# Import des templates
from src.templates.activation_email_template import (
    get_activation_email_html,
    get_activation_email_text,
    get_auditee_activation_email_html,
    get_auditee_activation_email_text,
    get_password_reset_email_html,
    get_password_reset_email_text,
    get_welcome_email_html,
    get_magic_link_email_html,
    get_magic_link_email_text,
    get_client_admin_creation_email_html,
    get_client_admin_creation_email_text,
    get_activation_confirmation_email_html,
    get_activation_confirmation_email_text
)
from src.templates.campaign_invitation_email_template import (
    get_campaign_invitation_email_html,
    get_campaign_invitation_email_text,
    get_campaign_invitation_email_subject
)
from src.templates.audit_submission_email_template import (
    get_audite_submission_email_html,
    get_audite_submission_email_text,
    get_audite_submission_email_subject,
    get_auditeur_submission_email_html,
    get_auditeur_submission_email_text,
    get_auditeur_submission_email_subject,
    get_chef_projet_submission_email_html,
    get_chef_projet_submission_email_text,
    get_chef_projet_submission_email_subject
)
from src.templates.campaign_reminder_email_template import (
    get_campaign_reminder_email_html,
    get_campaign_reminder_email_text,
    get_campaign_reminder_email_subject
)
from src.templates.discussion_notification_email_template import (
    get_discussion_new_message_email_html,
    get_discussion_new_message_email_text,
    get_discussion_new_message_email_subject,
    get_discussion_mention_email_html,
    get_discussion_mention_email_text,
    get_discussion_mention_email_subject
)

# Charger les variables d'environnement
load_dotenv()

logger = logging.getLogger(__name__)

# Configuration depuis .env
# Support des deux formats : MAIL_* (générique) et MAILTRAP_* (legacy)
SMTP_HOST = os.getenv("MAIL_SERVER") or os.getenv("MAILTRAP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("MAIL_PORT") or os.getenv("MAILTRAP_PORT", "2525"))
SMTP_USERNAME = os.getenv("MAILTRAP_USERNAME", "")
SMTP_PASSWORD = os.getenv("MAILTRAP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
FROM_EMAIL = os.getenv("MAIL_FROM") or os.getenv("FROM_EMAIL", "noreply@vision-agile.fr")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Détecter si on utilise Mailpit (dev local) ou Mailtrap (production)
IS_LOCAL_SMTP = SMTP_HOST == "localhost" or SMTP_HOST == "127.0.0.1"

# Compatibilité avec l'ancien code
MAILTRAP_HOST = SMTP_HOST
MAILTRAP_PORT = SMTP_PORT
MAILTRAP_USERNAME = SMTP_USERNAME
MAILTRAP_PASSWORD = SMTP_PASSWORD


def _create_smtp_connection():
    """
    Crée et authentifie une connexion SMTP.
    En mode local (Mailpit), pas d'authentification requise.
    En mode production (Mailtrap), authentification nécessaire.
    """
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
    # Active debug uniquement en mode local pour diagnostiquer les problèmes
    server.set_debuglevel(1 if IS_LOCAL_SMTP else 0)

    # Authentification uniquement si pas en mode local
    if not IS_LOCAL_SMTP:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        logger.debug(f"📧 Connexion SMTP authentifiée à {SMTP_HOST}:{SMTP_PORT}")
    else:
        logger.debug(f"📧 Connexion SMTP locale (sans auth) à {SMTP_HOST}:{SMTP_PORT}")

    return server


def send_activation_email(
    to_email: str,
    user_name: str,
    activation_url: str,
    organization_name: str = "Vision Agile"
):
    """
    Envoie un email d'activation de compte
    
    Args:
        to_email: Email du destinataire
        user_name: Nom complet de l'utilisateur
        activation_url: URL d'activation du compte
        organization_name: Nom de l'organisation
    """
    
    # Vérifier que les credentials sont configurés (sauf pour SMTP local comme Mailpit)
    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ MAILTRAP_USERNAME ou MAILTRAP_PASSWORD non configurés dans .env")
        raise ValueError("Configuration Mailtrap manquante dans .env")
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Activez votre compte {organization_name}"
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email
        
        # Utiliser les templates séparés
        text = get_activation_email_text(user_name, activation_url, organization_name)
        html = get_activation_email_html(user_name, activation_url, organization_name)
        
        # Attacher les deux versions
        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)
        
        # Envoyer via SMTP
        logger.info(f"📧 Connexion au serveur SMTP ({SMTP_HOST}:{SMTP_PORT})...")

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email d'activation envoyé avec succès à {to_email}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        logger.error(f"❌ Erreur d'authentification SMTP - Vérifiez MAILTRAP_USERNAME et MAILTRAP_PASSWORD dans .env")
        raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email à {to_email}: {e}")
        raise


def send_password_reset_email(
    to_email: str,
    user_name: str,
    reset_url: str,
    organization_name: str = "Vision Agile"
):
    """
    Envoie un email de réinitialisation de mot de passe
    
    Args:
        to_email: Email du destinataire
        user_name: Nom complet de l'utilisateur
        reset_url: URL de réinitialisation du mot de passe
        organization_name: Nom de l'organisation
    """
    
    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Réinitialisation de votre mot de passe - {organization_name}"
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email
        
        # Utiliser les templates séparés
        text = get_password_reset_email_text(user_name, reset_url, organization_name)
        html = get_password_reset_email_html(user_name, reset_url, organization_name)
        
        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)
        
        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email de réinitialisation envoyé à {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur envoi email à {to_email}: {e}")
        raise


def send_activation_email_by_role(
    to_email: str,
    user_name: str,
    activation_url: str,
    role_code: str,
    organization_name: str = "CYBERGARD AI",
    entity_name: str = None
):
    """
    Envoie un email d'activation adapté selon le rôle de l'utilisateur

    Args:
        to_email: Email du destinataire
        user_name: Nom complet de l'utilisateur
        activation_url: URL d'activation du compte
        role_code: Code du rôle (ADMIN, RSSI, CHEF_PROJET, AUDITEUR, etc.)
        organization_name: Nom de l'organisation
        entity_name: Nom de l'entité (pour les audités uniquement)
    """

    # Vérifier que les credentials sont configurés (sauf pour SMTP local comme Mailpit)
    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ MAILTRAP_USERNAME ou MAILTRAP_PASSWORD non configurés dans .env")
        raise ValueError("Configuration Mailtrap manquante dans .env")

    try:
        # ✅ Liste complète des rôles d'utilisateurs internes (table users)
        # Ces utilisateurs reçoivent l'email d'activation avec thème CYBERGARD AI
        INTERNAL_USER_ROLES = [
            'ADMIN', 'MANAGER', 'SUPERADMIN',
            'RSSI', 'RSSI_EXTERNE',
            'DIR_CONFORMITE_DPO', 'DPO_EXTERNE',
            'CHEF_PROJET', 'AUDITEUR',
            'AUDITE_RESP', 'AUDITE_CONTRIB'
        ]

        # Déterminer quel template utiliser selon le rôle
        is_internal_user = role_code.upper() in INTERNAL_USER_ROLES

        if is_internal_user:
            # Email pour utilisateur interne (table users) - Thème CYBERGARD AI
            subject = f"Activez votre compte {organization_name}"
            text = get_activation_email_text(user_name, activation_url, organization_name)
            html = get_activation_email_html(user_name, activation_url, organization_name)
            logger.info(f"📧 Envoi email activation UTILISATEUR INTERNE ({role_code}) à {to_email}")
        else:
            # Email pour audité (table entity_member) - Thème vert audit
            entity_display = entity_name if entity_name else organization_name
            subject = f"🔐 Invitation à participer à votre audit de conformité – {entity_display}"
            text = get_auditee_activation_email_text(user_name, activation_url, organization_name, entity_name)
            html = get_auditee_activation_email_html(user_name, activation_url, organization_name, entity_name)
            logger.info(f"📧 Envoi email activation AUDITÉ ({role_code}) à {to_email} - Entité: {entity_display}")

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Attacher les deux versions
        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        # Envoyer via SMTP
        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email d'activation envoyé avec succès à {to_email}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(f"❌ Erreur d'authentification SMTP - Vérifiez MAILTRAP_USERNAME et MAILTRAP_PASSWORD dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII (accents). "
                        f"Veuillez utiliser une adresse email sans accents (ex: audite@maroc.ma au lieu de audité@maroc.ma)")
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email à {to_email}: {e}")
        raise


def send_welcome_email(
    to_email: str,
    user_name: str,
    organization_name: str = "Vision Agile"
):
    """
    Envoie un email de bienvenue après activation du compte

    Args:
        to_email: Email du destinataire
        user_name: Nom complet de l'utilisateur
        organization_name: Nom de l'organisation
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Bienvenue dans {organization_name} !"
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Utiliser le template de bienvenue
        html = get_welcome_email_html(user_name, organization_name)

        part = MIMEText(html, 'html', 'utf-8')
        msg.attach(part)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email de bienvenue envoyé à {to_email}")
        return True

    except Exception as e:
        logger.error(f"❌ Erreur envoi email à {to_email}: {e}")
        raise


def send_activation_confirmation_email(
    to_email: str,
    user_name: str,
    login_url: str,
    organization_name: str = "CYBERGARD AI"
):
    """
    Envoie un email de confirmation après l'activation d'un compte
    Réutilisable pour tous les nouveaux collaborateurs du tenant

    Args:
        to_email: Email du destinataire
        user_name: Nom complet de l'utilisateur
        login_url: URL de la page de connexion
        organization_name: Nom de l'organisation/tenant
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"✅ Compte activé avec succès - {organization_name}"
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Utiliser les templates de confirmation d'activation
        text = get_activation_confirmation_email_text(user_name, login_url, organization_name)
        html = get_activation_confirmation_email_html(user_name, login_url, organization_name)

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email de confirmation d'activation envoyé à {to_email} - Organisation: {organization_name}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email de confirmation d'activation à {to_email}: {e}")
        raise


def send_magic_link_email(
    to_email: str,
    user_name: str,
    magic_link: str,
    campaign_name: str,
    entity_name: str,
    organization_name: str = "CYBERGARD AI",
    expiry_days: int = 7,
    max_uses: int = 10
):
    """
    Envoie un email avec lien magique pour accès direct à l'audit

    Args:
        to_email: Email du destinataire (audité)
        user_name: Nom complet de l'utilisateur
        magic_link: URL complète du lien magique avec token
        campaign_name: Nom de la campagne d'audit
        entity_name: Nom de l'entité auditée
        organization_name: Nom de l'organisation qui réalise l'audit (CYBERGARD AI par défaut)
        expiry_days: Nombre de jours de validité du lien
        max_uses: Nombre maximal d'utilisations du lien
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"🔐 Accédez à votre audit de conformité – {campaign_name}"
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Utiliser les templates de lien magique (le logo est intégré en base64)
        text = get_magic_link_email_text(
            user_name=user_name,
            magic_link=magic_link,
            campaign_name=campaign_name,
            entity_name=entity_name,
            organization_name=organization_name,
            expiry_days=expiry_days,
            max_uses=max_uses
        )
        html = get_magic_link_email_html(
            user_name=user_name,
            magic_link=magic_link,
            campaign_name=campaign_name,
            entity_name=entity_name,
            organization_name=organization_name,
            expiry_days=expiry_days,
            max_uses=max_uses
        )

        # Attacher les deux versions
        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        # Envoyer via SMTP
        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(
            f"✅ Lien magique envoyé à {to_email} - "
            f"Campagne: {campaign_name}, Validité: {expiry_days} jours, Max: {max_uses} utilisations"
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi lien magique à {to_email}: {e}")
        raise

def send_contributor_mention_email(
    to_email: str,
    user_name: str,
    magic_link: str,
    mentioned_by_name: str,
    question_text: str,
    campaign_name: str,
    entity_name: str,
    organization_name: str = "CYBERGARD AI",
    expiry_days: int = 7
):
    """
    Envoie un email à un contributeur mentionné dans un commentaire avec Magic Link

    Args:
        to_email: Email du contributeur mentionné
        user_name: Nom complet du contributeur
        magic_link: URL complète du lien magique avec token
        mentioned_by_name: Nom de la personne qui a mentionné le contributeur (AUDITE_RESP)
        question_text: Extrait du commentaire/question
        campaign_name: Nom de la campagne d'audit
        entity_name: Nom de l'entité auditée
        organization_name: Nom de l'organisation (CYBERGARD AI par défaut)
        expiry_days: Nombre de jours de validité du lien
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Vous êtes invité à contribuer à l'audit de conformité {campaign_name}"
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Template text simple
        text = f"""
Bonjour {user_name},

Vous avez été désigné par {mentioned_by_name} pour apporter votre contribution à une question spécifique dans le cadre de l'audit de conformité {campaign_name}.

Cet audit est organisé par {organization_name} pour l'entité {entity_name}.

Cliquez sur le lien ci-dessous pour accéder directement à la question qui vous a été attribuée.
Aucun mot de passe n'est nécessaire.

🔗 Accéder à la question : {magic_link}

🕒 DURÉE DE VALIDITÉ DU LIEN
Ce lien est strictement personnel et restera valide pendant {expiry_days} jours.
Vous pouvez l'utiliser à tout moment pour compléter votre réponse.

📋 INFORMATIONS IMPORTANTES

• Lien personnel : ne partagez pas ce lien, il est unique et rattaché à votre adresse e-mail.
• Sauvegarde automatique : vos réponses sont enregistrées à chaque modification.
• Reprise possible : vous pouvez revenir sur ce lien pour ajuster votre réponse tant que la campagne est ouverte.
• Confidentialité : vos contributions sont strictement confidentielles et visibles uniquement par l'auditeur responsable.

💡 LE BOUTON NE FONCTIONNE PAS ?
Copiez et collez ce lien dans votre navigateur :
{magic_link}

Merci pour votre collaboration,
L'équipe {organization_name}
Plateforme de gestion des audits et plans d'action
"""
        
        # Template HTML
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Invitation à contribuer à l'audit</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <!-- Logo CYBERGARD AI -->
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                    <path d="M9 12l2 2 4-4"></path>
                </svg>
            </div>

            <!-- Titre marque -->
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Invitation à contribuer
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                {campaign_name}
            </p>
        </div>

        <!-- Contenu -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{user_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Vous avez été désigné par <strong style="color: #ffffff;">{mentioned_by_name}</strong> pour apporter votre contribution à une question spécifique dans le cadre de l'<strong style="color: #ffffff;">audit de conformité {campaign_name}</strong>.
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Cet audit est organisé par <strong style="color: #ffffff;">{organization_name}</strong> pour l'entité <strong style="color: #ffffff;">{entity_name}</strong>.
            </p>

            <p style="margin: 0 0 32px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Cliquez sur le bouton ci-dessous pour accéder directement à la question qui vous a été attribuée. Aucun mot de passe n'est nécessaire.
            </p>

            <!-- Bouton CTA -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{magic_link}"
                   style="display: inline-block;
                          padding: 14px 32px;
                          background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 15px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);">
                    🔗 Accéder à la question
                </a>
            </div>

            <!-- Info temporelle -->
            <div style="background: rgba(59, 130, 246, 0.05);
                        border: 1px solid rgba(59, 130, 246, 0.2);
                        padding: 16px;
                        margin: 24px 0;
                        border-radius: 6px;
                        text-align: center;">
                <p style="margin: 0; font-size: 13px; color: #93c5fd; line-height: 1.6;">
                    🕒 Ce lien est <strong>strictement personnel</strong> et restera valide pendant <strong>{expiry_days} jours</strong>.<br>
                    Vous pouvez l'utiliser à tout moment pour compléter votre réponse.
                </p>
            </div>

            <!-- Info box stylée -->
            <div style="background: #374151;
                        border: 1px solid #4b5563;
                        border-radius: 6px;
                        padding: 20px;
                        margin: 32px 0;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #ffffff;">
                    📋 Informations importantes
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        🔒 <strong style="color: #ffffff;">Lien personnel</strong> : Ne partagez pas ce lien, il est unique et rattaché à votre adresse e-mail.
                    </div>
                    <div style="margin-bottom: 8px;">
                        💾 <strong style="color: #ffffff;">Sauvegarde automatique</strong> : Vos réponses sont enregistrées à chaque modification.
                    </div>
                    <div style="margin-bottom: 8px;">
                        🔄 <strong style="color: #ffffff;">Reprise possible</strong> : Vous pouvez revenir sur ce lien pour ajuster votre réponse tant que la campagne est ouverte.
                    </div>
                    <div>
                        🔐 <strong style="color: #ffffff;">Confidentialité</strong> : Vos contributions sont strictement confidentielles et visibles uniquement par l'auditeur responsable.
                    </div>
                </div>
            </div>

            <!-- Lien de secours -->
            <div style="margin: 24px 0 0 0; padding: 16px; background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 6px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: #fbbf24;">
                    💡 Le bouton ne fonctionne pas ?
                </p>
                <p style="margin: 0 0 8px 0; font-size: 13px; color: #fcd34d;">
                    Copiez et collez ce lien dans votre navigateur :
                </p>
                <code style="background: #374151;
                             padding: 12px;
                             display: block;
                             word-break: break-all;
                             border-radius: 6px;
                             font-size: 12px;
                             color: #93c5fd;
                             border: 1px solid #4b5563;">
                    {magic_link}
                </code>
            </div>
        </div>

        <!-- Footer -->
        <div style="background: #1a202c;
                    padding: 24px 30px;
                    text-align: center;
                    border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 12px 0; color: #d1d5db; font-size: 14px; font-weight: 500;">
                Merci pour votre collaboration,
            </p>
            <p style="margin: 0 0 8px 0; color: #ffffff; font-size: 14px; font-weight: 600;">
                L'équipe {organization_name}
            </p>
            <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                Plateforme de gestion des audits et plans d'action
            </p>
        </div>
    </div>

</body>
</html>
"""
        
        # Attacher les deux versions
        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)
        
        # Envoyer via SMTP
        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        
        logger.info(
            f"✅ Email de mention envoyé à {to_email} - "
            f"Mentionné par: {mentioned_by_name}, Campagne: {campaign_name}"
        )
        return True
    
    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email de mention à {to_email}: {e}")
        raise


def send_auditor_message_notification_email(
    to_email: str,
    auditor_name: str,
    magic_link: str,
    contributor_name: str,
    campaign_name: str,
    client_name: str,
    campaign_start_date: str = None,
    campaign_end_date: str = None,
    organization_name: str = "CYBERGARD AI"
):
    """
    Envoie un email à un auditeur pour le notifier qu'un audité a envoyé un message

    Args:
        to_email: Email de l'auditeur
        auditor_name: Nom complet de l'auditeur
        magic_link: URL complète du lien magique avec token
        contributor_name: Nom de l'audité qui a envoyé le message
        campaign_name: Nom de la campagne d'audit
        client_name: Nom du client/tenant
        campaign_start_date: Date de début (optionnel)
        campaign_end_date: Date de fin (optionnel)
        organization_name: Nom de l'organisation
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Nouveau message reçu concernant la campagne d'audit \"{campaign_name}\""
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Période d'audit
        period_text = ""
        if campaign_start_date and campaign_end_date:
            period_text = f"du {campaign_start_date} au {campaign_end_date}"
        elif campaign_start_date:
            period_text = f"à partir du {campaign_start_date}"
        else:
            period_text = "Non définie"

        # Template text simple
        text = f"""
Bonjour {auditor_name},

Vous avez reçu un nouveau message d'un audité dans le cadre de la campagne "{campaign_name}" menée pour {client_name}.

Ce message concerne une question ou un point de contrôle sur lequel une réponse ou un commentaire a été apporté.
Nous vous invitons à le consulter afin de valider la réponse ou formuler un retour complémentaire si nécessaire.

📅 INFORMATIONS SUR LA CAMPAGNE

• Nom de la campagne : {campaign_name}
• Client : {client_name}
• Période d'audit : {period_text}
• Statut actuel : En cours de revue

🔗 Consulter le message de l'audité :
{magic_link}

(Ce lien est personnel et vous permet d'accéder directement au fil d'échanges lié à la question concernée.)

💡 À SAVOIR

• Vous pouvez répondre directement via la plateforme pour centraliser les échanges.
• L'audité sera notifié automatiquement en cas de retour ou de demande de précision.
• Toutes les communications sont archivées dans le journal de campagne.

Merci pour votre suivi et votre engagement dans le processus d'audit.

L'équipe {organization_name}
La plateforme intelligente de gestion des audits et plans d'action.
"""

        # Template HTML (même style rouge que contributeur)
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nouveau message d'audité</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <!-- Logo CYBERGARD AI -->
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                    <path d="M9 12l2 2 4-4"></path>
                </svg>
            </div>

            <!-- Titre marque -->
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Nouveau message reçu
            </h2>
            <p style="margin: 0; font-size: 15px; color: #9ca3af;">
                Campagne: {campaign_name}
            </p>
        </div>

        <!-- Contenu principal -->
        <div style="padding: 0 30px 32px;">
            <p style="margin: 0 0 16px 0; font-size: 15px; line-height: 1.6; color: #d1d5db;">
                Bonjour <strong style="color: #ffffff;">{auditor_name}</strong>,
            </p>

            <p style="margin: 0 0 16px 0; font-size: 15px; line-height: 1.6; color: #d1d5db;">
                Vous avez reçu un nouveau message d'un audité dans le cadre de la campagne "<strong style="color: #ffffff;">{campaign_name}</strong>" menée pour <strong style="color: #ffffff;">{client_name}</strong>.
            </p>

            <p style="margin: 0 0 24px 0; font-size: 15px; line-height: 1.6; color: #d1d5db;">
                Ce message concerne une question ou un point de contrôle sur lequel une réponse ou un commentaire a été apporté.
                Nous vous invitons à le consulter afin de valider la réponse ou formuler un retour complémentaire si nécessaire.
            </p>

            <!-- Informations campagne -->
            <div style="margin: 24px 0; padding: 20px; background: rgba(220, 38, 38, 0.1); border: 1px solid rgba(220, 38, 38, 0.3); border-radius: 6px;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: #f87171;">
                    📅 Informations sur la campagne
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 6px;">
                        <strong style="color: #ffffff;">Nom de la campagne :</strong> {campaign_name}
                    </div>
                    <div style="margin-bottom: 6px;">
                        <strong style="color: #ffffff;">Client :</strong> {client_name}
                    </div>
                    <div style="margin-bottom: 6px;">
                        <strong style="color: #ffffff;">Période d'audit :</strong> {period_text}
                    </div>
                    <div>
                        <strong style="color: #ffffff;">Statut actuel :</strong> En cours de revue
                    </div>
                </div>
            </div>

            <!-- Bouton CTA -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{magic_link}" style="display: inline-block; padding: 14px 32px; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); color: white; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 15px; box-shadow: 0 4px 12px rgba(220, 38, 38, 0.4); transition: transform 0.2s;">
                    🔗 Consulter le message de l'audité
                </a>
            </div>

            <!-- À savoir -->
            <div style="margin: 24px 0; padding: 20px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 6px;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: #34d399;">
                    💡 À savoir
                </p>
                <div style="font-size: 13px; color: #d1d5db; line-height: 1.7;">
                    <div style="margin-bottom: 8px;">
                        • Vous pouvez répondre directement via la plateforme pour centraliser les échanges.
                    </div>
                    <div style="margin-bottom: 8px;">
                        • L'audité sera notifié automatiquement en cas de retour ou de demande de précision.
                    </div>
                    <div>
                        • Toutes les communications sont archivées dans le journal de campagne.
                    </div>
                </div>
            </div>

            <!-- Lien de secours -->
            <div style="margin: 24px 0 0 0; padding: 16px; background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 6px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: #fbbf24;">
                    💡 Le bouton ne fonctionne pas ?
                </p>
                <p style="margin: 0; font-size: 12px; color: #fcd34d; word-break: break-all;">
                    {magic_link}
                </p>
            </div>
        </div>

        <!-- Footer -->
        <div style="text-align: center; padding: 24px 30px; background: #1a202c; border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 8px 0; font-size: 13px; color: #9ca3af;">
                Merci pour votre suivi et votre engagement dans le processus d'audit.
            </p>
            <p style="margin: 0; font-size: 12px; color: #6b7280;">
                L'équipe {organization_name}<br>
                La plateforme intelligente de gestion des audits et plans d'action.
            </p>
        </div>
    </div>

</body>
</html>
"""

        # Attacher les parties text et HTML
        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        # Envoyer l'email
        connection = _create_smtp_connection()
        connection.send_message(msg)
        connection.quit()

        logger.info(f"✅ Email de notification auditeur envoyé avec succès à {to_email}")
        return True

    except Exception as e:
        logger.error(f"❌ Erreur lors de l'envoi de l'email de notification auditeur: {e}")
        raise


def send_client_admin_creation_email(
    to_email: str,
    user_name: str,
    organization_name: str,
    activation_url: str,
    temp_password: str = None
):
    """
    Envoie un email au nouvel administrateur lors de la création d'un client/organisation

    Args:
        to_email: Email de l'administrateur
        user_name: Nom complet de l'utilisateur admin
        organization_name: Nom de l'organisation créée
        activation_url: URL d'activation du compte
        temp_password: Mot de passe temporaire (optionnel)
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Bienvenue sur CYBERGARD AI - Votre organisation {organization_name} a été créée"
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Utiliser les templates de création client admin
        text = get_client_admin_creation_email_text(user_name, organization_name, activation_url, temp_password)
        html = get_client_admin_creation_email_html(user_name, organization_name, activation_url, temp_password)

        # Attacher les deux versions
        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        # Envoyer via SMTP
        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(
            f"✅ Email de création client admin envoyé à {to_email} - "
            f"Organisation: {organization_name}"
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email de création client admin à {to_email}: {e}")
        raise


def send_campaign_invitation_email(
    to_email: str,
    recipient_name: str,
    recipient_role: str,
    campaign_name: str,
    client_name: str,
    start_date: str,
    end_date: str,
    framework_name: str,
    campaign_url: str,
    sender_name: str = "L'equipe CYBERGARD AI"
):
    """
    Envoie un email d'invitation à une campagne pour les parties prenantes internes.

    Args:
        to_email: Email du destinataire
        recipient_name: Nom complet du destinataire
        recipient_role: Rôle dans la campagne (Chef de projet / Auditeur interne / Contributeur)
        campaign_name: Nom de la campagne
        client_name: Nom du client/organisation
        start_date: Date de début de la campagne
        end_date: Date de fin de la campagne
        framework_name: Nom du référentiel
        campaign_url: URL d'accès à la campagne
        sender_name: Nom de l'expéditeur
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_campaign_invitation_email_subject(campaign_name, client_name)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Utiliser les templates d'invitation de campagne
        text = get_campaign_invitation_email_text(
            recipient_name=recipient_name,
            recipient_role=recipient_role,
            campaign_name=campaign_name,
            client_name=client_name,
            start_date=start_date,
            end_date=end_date,
            framework_name=framework_name,
            campaign_url=campaign_url,
            sender_name=sender_name
        )
        html = get_campaign_invitation_email_html(
            recipient_name=recipient_name,
            recipient_role=recipient_role,
            campaign_name=campaign_name,
            client_name=client_name,
            start_date=start_date,
            end_date=end_date,
            framework_name=framework_name,
            campaign_url=campaign_url,
            sender_name=sender_name
        )

        # Attacher les deux versions
        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        # Envoyer via SMTP
        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(
            f"✅ Invitation campagne envoyée à {to_email} - "
            f"Campagne: {campaign_name}, Rôle: {recipient_role}"
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi invitation campagne à {to_email}: {e}")
        raise


def send_audite_submission_email(
    to_email: str,
    audite_name: str,
    campaign_name: str,
    client_name: str,
    submission_date: str,
    total_questions: int,
    answered_questions: int,
    framework_name: str
):
    """
    Envoie un email de confirmation de soumission à l'Audité

    Args:
        to_email: Email de l'audité
        audite_name: Nom complet de l'audité
        campaign_name: Nom de la campagne
        client_name: Nom du client/organisation
        submission_date: Date et heure de soumission
        total_questions: Nombre total de questions
        answered_questions: Nombre de questions répondues
        framework_name: Nom du référentiel
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_audite_submission_email_subject(campaign_name)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        text = get_audite_submission_email_text(
            audite_name=audite_name,
            campaign_name=campaign_name,
            client_name=client_name,
            submission_date=submission_date,
            total_questions=total_questions,
            answered_questions=answered_questions,
            framework_name=framework_name
        )
        html = get_audite_submission_email_html(
            audite_name=audite_name,
            campaign_name=campaign_name,
            client_name=client_name,
            submission_date=submission_date,
            total_questions=total_questions,
            answered_questions=answered_questions,
            framework_name=framework_name
        )

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email de confirmation soumission envoyé à l'audité {to_email}")
        return True

    except Exception as e:
        logger.error(f"❌ Erreur envoi email confirmation soumission à {to_email}: {e}")
        raise


def send_auditeur_submission_email(
    to_email: str,
    auditeur_name: str,
    audite_name: str,
    campaign_name: str,
    client_name: str,
    submission_date: str,
    total_questions: int,
    answered_questions: int,
    framework_name: str,
    review_url: str
):
    """
    Envoie un email de notification à l'Auditeur qu'une soumission est disponible pour revue

    Args:
        to_email: Email de l'auditeur
        auditeur_name: Nom complet de l'auditeur
        audite_name: Nom de l'audité qui a soumis
        campaign_name: Nom de la campagne
        client_name: Nom du client/organisation
        submission_date: Date et heure de soumission
        total_questions: Nombre total de questions
        answered_questions: Nombre de questions répondues
        framework_name: Nom du référentiel
        review_url: URL pour accéder à la revue
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_auditeur_submission_email_subject(campaign_name, audite_name)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        text = get_auditeur_submission_email_text(
            auditeur_name=auditeur_name,
            audite_name=audite_name,
            campaign_name=campaign_name,
            client_name=client_name,
            submission_date=submission_date,
            total_questions=total_questions,
            answered_questions=answered_questions,
            framework_name=framework_name,
            review_url=review_url
        )
        html = get_auditeur_submission_email_html(
            auditeur_name=auditeur_name,
            audite_name=audite_name,
            campaign_name=campaign_name,
            client_name=client_name,
            submission_date=submission_date,
            total_questions=total_questions,
            answered_questions=answered_questions,
            framework_name=framework_name,
            review_url=review_url
        )

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email de notification soumission envoyé à l'auditeur {to_email}")
        return True

    except Exception as e:
        logger.error(f"❌ Erreur envoi email notification auditeur à {to_email}: {e}")
        raise


def send_chef_projet_submission_email(
    to_email: str,
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
):
    """
    Envoie un email de mise à jour au Chef de projet qu'un audit a été soumis

    Args:
        to_email: Email du chef de projet
        chef_projet_name: Nom complet du chef de projet
        audite_name: Nom de l'audité qui a soumis
        campaign_name: Nom de la campagne
        client_name: Nom du client/organisation
        submission_date: Date et heure de soumission
        total_questions: Nombre total de questions
        answered_questions: Nombre de questions répondues
        framework_name: Nom du référentiel
        campaign_url: URL pour accéder au tableau de bord
        total_audites: Nombre total d'audités dans la campagne
        submitted_audites: Nombre d'audités ayant soumis
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_chef_projet_submission_email_subject(campaign_name, audite_name)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        text = get_chef_projet_submission_email_text(
            chef_projet_name=chef_projet_name,
            audite_name=audite_name,
            campaign_name=campaign_name,
            client_name=client_name,
            submission_date=submission_date,
            total_questions=total_questions,
            answered_questions=answered_questions,
            framework_name=framework_name,
            campaign_url=campaign_url,
            total_audites=total_audites,
            submitted_audites=submitted_audites
        )
        html = get_chef_projet_submission_email_html(
            chef_projet_name=chef_projet_name,
            audite_name=audite_name,
            campaign_name=campaign_name,
            client_name=client_name,
            submission_date=submission_date,
            total_questions=total_questions,
            answered_questions=answered_questions,
            framework_name=framework_name,
            campaign_url=campaign_url,
            total_audites=total_audites,
            submitted_audites=submitted_audites
        )

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email de mise à jour soumission envoyé au chef de projet {to_email}")
        return True

    except Exception as e:
        logger.error(f"❌ Erreur envoi email chef de projet à {to_email}: {e}")
        raise


def send_campaign_reminder_email(
    to_email: str,
    audite_firstname: str,
    audite_lastname: str,
    referentiel_name: str,
    entity_name: str,
    magic_link: str,
    expiration_date: str
):
    """
    Envoie un email de relance de campagne à un audité qui n'a pas encore complété son audit

    Args:
        to_email: Email de l'audité
        audite_firstname: Prénom de l'audité
        audite_lastname: Nom de l'audité
        referentiel_name: Nom du référentiel (ex: ISO 27001)
        entity_name: Nom de l'entité auditée
        magic_link: URL complète du lien magique avec token
        expiration_date: Date d'expiration du lien (format: "31 décembre 2025")
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_campaign_reminder_email_subject(referentiel_name)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        text = get_campaign_reminder_email_text(
            audite_firstname=audite_firstname,
            audite_lastname=audite_lastname,
            referentiel_name=referentiel_name,
            entity_name=entity_name,
            magic_link=magic_link,
            expiration_date=expiration_date
        )
        html = get_campaign_reminder_email_html(
            audite_firstname=audite_firstname,
            audite_lastname=audite_lastname,
            referentiel_name=referentiel_name,
            entity_name=entity_name,
            magic_link=magic_link,
            expiration_date=expiration_date
        )

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(
            f"✅ Email de relance envoyé à {to_email} - "
            f"Entité: {entity_name}, Référentiel: {referentiel_name}"
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email de relance à {to_email}: {e}")
        raise


def send_discussion_new_message_email(
    to_email: str,
    recipient_name: str,
    sender_name: str,
    conversation_title: str,
    conversation_type: str,
    message_preview: str,
    conversation_url: str,
    campaign_name: str = None,
    entity_name: str = None,
    organization_name: str = "CYBERGARD AI"
):
    """
    Envoie un email de notification pour un nouveau message dans une discussion.

    Args:
        to_email: Email du destinataire
        recipient_name: Nom du destinataire
        sender_name: Nom de l'expéditeur du message
        conversation_title: Titre de la conversation
        conversation_type: Type de conversation (RIGHTS, ACTION, QUESTION, DIRECT_MESSAGE)
        message_preview: Aperçu du message (premiers 200 caractères)
        conversation_url: URL pour accéder à la conversation
        campaign_name: Nom de la campagne (optionnel)
        entity_name: Nom de l'entité (optionnel)
        organization_name: Nom de l'organisation
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_discussion_new_message_email_subject(conversation_title, sender_name)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        text = get_discussion_new_message_email_text(
            recipient_name=recipient_name,
            sender_name=sender_name,
            conversation_title=conversation_title,
            conversation_type=conversation_type,
            message_preview=message_preview,
            conversation_url=conversation_url,
            campaign_name=campaign_name,
            entity_name=entity_name,
            organization_name=organization_name
        )
        html = get_discussion_new_message_email_html(
            recipient_name=recipient_name,
            sender_name=sender_name,
            conversation_title=conversation_title,
            conversation_type=conversation_type,
            message_preview=message_preview,
            conversation_url=conversation_url,
            campaign_name=campaign_name,
            entity_name=entity_name,
            organization_name=organization_name
        )

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(
            f"✅ Email notification discussion envoyé à {to_email} - "
            f"Conversation: {conversation_title}, De: {sender_name}"
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email notification discussion à {to_email}: {e}")
        raise


def send_discussion_mention_email(
    to_email: str,
    recipient_name: str,
    sender_name: str,
    conversation_title: str,
    conversation_type: str,
    message_content: str,
    conversation_url: str,
    campaign_name: str = None,
    entity_name: str = None,
    organization_name: str = "CYBERGARD AI"
):
    """
    Envoie un email de notification pour une mention dans une discussion.

    Args:
        to_email: Email du destinataire mentionné
        recipient_name: Nom du destinataire
        sender_name: Nom de la personne qui a mentionné
        conversation_title: Titre de la conversation
        conversation_type: Type de conversation
        message_content: Contenu du message avec la mention
        conversation_url: URL pour accéder à la conversation
        campaign_name: Nom de la campagne (optionnel)
        entity_name: Nom de l'entité (optionnel)
        organization_name: Nom de l'organisation
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_discussion_mention_email_subject(sender_name, conversation_title)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        text = get_discussion_mention_email_text(
            recipient_name=recipient_name,
            sender_name=sender_name,
            conversation_title=conversation_title,
            conversation_type=conversation_type,
            message_content=message_content,
            conversation_url=conversation_url,
            campaign_name=campaign_name,
            entity_name=entity_name,
            organization_name=organization_name
        )
        html = get_discussion_mention_email_html(
            recipient_name=recipient_name,
            sender_name=sender_name,
            conversation_title=conversation_title,
            conversation_type=conversation_type,
            message_content=message_content,
            conversation_url=conversation_url,
            campaign_name=campaign_name,
            entity_name=entity_name,
            organization_name=organization_name
        )

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(
            f"✅ Email mention discussion envoyé à {to_email} - "
            f"Mentionné par: {sender_name}, Conversation: {conversation_title}"
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email mention discussion à {to_email}: {e}")
        raise


# ============================================================================
# EMAIL DEMANDE DE DROITS
# ============================================================================

def get_rights_request_email_subject(requester_name: str, action_name: str) -> str:
    """Génère le sujet de l'email de demande de droits"""
    return f"🔐 Demande de droits: {action_name} - {requester_name}"


def get_rights_request_email_text(
    admin_name: str,
    requester_name: str,
    requester_email: str,
    permission_code: str,
    action_name: str,
    message: str,
    permission_url: str,
    conversation_url: str,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """Génère le contenu texte de l'email de demande de droits"""
    text = f"""Bonjour {admin_name},

{requester_name} ({requester_email}) demande l'accès à une nouvelle permission.

DÉTAILS DE LA DEMANDE
---------------------
Permission demandée: {permission_code}
Action: {action_name}
"""
    if message:
        text += f"""
Message de l'utilisateur:
{message}
"""
    text += f"""
ACTIONS
-------
Gérer les permissions: {permission_url}
Voir la conversation: {conversation_url}

Cordialement,
L'équipe {organization_name}
"""
    return text


def get_rights_request_email_html(
    admin_name: str,
    requester_name: str,
    requester_email: str,
    permission_code: str,
    action_name: str,
    message: str,
    permission_url: str,
    conversation_url: str,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """Génère le contenu HTML de l'email de demande de droits"""

    message_section = ""
    if message:
        message_section = f"""
              <div style="background-color: #f9fafb; border-radius: 6px; padding: 15px; margin-top: 15px;">
                <p style="margin: 0; color: #6b7280; font-size: 14px; font-weight: 600;">Message de l'utilisateur:</p>
                <p style="margin: 10px 0 0 0; color: #4b5563; font-size: 14px; line-height: 1.5;">{message}</p>
              </div>
"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f4f4;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f4f4; padding: 20px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">

          <!-- Header avec Logo -->
          <tr>
            <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 8px 8px 0 0;">
              <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">
                🛡️ {organization_name}
              </h1>
              <p style="margin: 5px 0 0 0; color: #e0e7ff; font-size: 14px;">
                Plateforme d'Audit de Cybersécurité
              </p>
            </td>
          </tr>

          <!-- Contenu -->
          <tr>
            <td style="padding: 30px;">

              <!-- Badge de notification -->
              <div style="background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; margin-bottom: 20px; border-radius: 4px;">
                <p style="margin: 0; color: #92400e; font-size: 14px;">
                  🔐 <strong>Nouvelle demande de droits</strong>
                </p>
              </div>

              <!-- Salutation -->
              <h2 style="color: #1f2937; font-size: 20px; margin: 0 0 15px 0;">
                Bonjour {admin_name},
              </h2>

              <p style="color: #4b5563; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                <strong>{requester_name}</strong> ({requester_email}) demande l'accès à une nouvelle permission.
              </p>

              <!-- Détails de la demande -->
              <div style="background-color: #f3f4f6; border-radius: 8px; padding: 20px; margin-bottom: 20px;">
                <h3 style="color: #374151; font-size: 16px; margin: 0 0 15px 0;">📋 Détails de la demande</h3>

                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px; width: 140px;">Permission demandée:</td>
                    <td style="padding: 8px 0; color: #1f2937; font-size: 14px; font-weight: 600;">
                      <span style="background-color: #e0e7ff; color: #4338ca; padding: 4px 10px; border-radius: 4px;">{permission_code}</span>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px;">Action:</td>
                    <td style="padding: 8px 0; color: #1f2937; font-size: 14px;">{action_name}</td>
                  </tr>
                </table>
              </div>

              {message_section}

              <!-- Boutons d'action -->
              <table cellpadding="0" cellspacing="0" style="margin: 25px 0;">
                <tr>
                  <td style="border-radius: 6px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); margin-right: 10px;">
                    <a href="{permission_url}" style="display: inline-block; padding: 14px 28px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px;">
                      ⚙️ Gérer les permissions
                    </a>
                  </td>
                  <td style="width: 15px;"></td>
                  <td style="border-radius: 6px; border: 2px solid #667eea;">
                    <a href="{conversation_url}" style="display: inline-block; padding: 12px 24px; color: #667eea; text-decoration: none; font-weight: 600; font-size: 14px;">
                      💬 Voir la conversation
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Info supplémentaire -->
              <div style="background-color: #f0fdf4; border-radius: 6px; padding: 15px; margin-top: 20px; border: 1px solid #bbf7d0;">
                <p style="margin: 0; color: #166534; font-size: 14px; line-height: 1.5;">
                  💡 <strong>Conseil:</strong> Vous pouvez accorder cette permission en modifiant les droits du rôle de l'utilisateur dans la section Administration &gt; Rôles.
                </p>
              </div>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f9fafb; padding: 20px; border-radius: 0 0 8px 8px; border-top: 1px solid #e5e7eb;">
              <p style="margin: 0 0 10px 0; color: #6b7280; font-size: 12px; text-align: center;">
                Cet email a été envoyé automatiquement par {organization_name}
              </p>
              <p style="margin: 0; color: #9ca3af; font-size: 11px; text-align: center;">
                © 2024 {organization_name}. Tous droits réservés.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_rights_request_email(
    to_email: str,
    admin_name: str,
    requester_name: str,
    requester_email: str,
    permission_code: str,
    action_name: str,
    message: str = None,
    permission_url: str = None,
    conversation_url: str = None,
    organization_name: str = "CYBERGARD AI"
):
    """
    Envoie un email de notification pour une demande de droits à un administrateur.

    Args:
        to_email: Email de l'administrateur
        admin_name: Nom de l'administrateur
        requester_name: Nom de l'utilisateur qui demande
        requester_email: Email de l'utilisateur qui demande
        permission_code: Code de la permission demandée
        action_name: Nom lisible de l'action
        message: Message optionnel de l'utilisateur
        permission_url: URL vers la page de gestion des permissions
        conversation_url: URL vers la conversation
        organization_name: Nom de l'organisation
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_rights_request_email_subject(requester_name, action_name)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        text = get_rights_request_email_text(
            admin_name=admin_name,
            requester_name=requester_name,
            requester_email=requester_email,
            permission_code=permission_code,
            action_name=action_name,
            message=message or "",
            permission_url=permission_url or "",
            conversation_url=conversation_url or "",
            organization_name=organization_name
        )
        html = get_rights_request_email_html(
            admin_name=admin_name,
            requester_name=requester_name,
            requester_email=requester_email,
            permission_code=permission_code,
            action_name=action_name,
            message=message or "",
            permission_url=permission_url or "",
            conversation_url=conversation_url or "",
            organization_name=organization_name
        )

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(
            f"✅ Email demande de droits envoyé à {to_email} - "
            f"Demandeur: {requester_name}, Permission: {permission_code}"
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email demande de droits à {to_email}: {e}")
        raise


# ============================================================================
# EMAIL DÉCISION DEMANDE DE DROITS
# ============================================================================

def get_rights_decision_email_subject(action: str) -> str:
    """Génère le sujet de l'email de décision sur une demande de droits"""
    if action == "accept":
        return "✅ Votre demande de droits a été acceptée"
    else:
        return "❌ Votre demande de droits a été refusée"


def get_rights_decision_email_html(
    requester_name: str,
    admin_name: str,
    action: str,
    permissions: list,
    message: str,
    conversation_url: str,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """Génère le contenu HTML de l'email de décision"""

    if action == "accept":
        header_color = "linear-gradient(135deg, #10b981 0%, #059669 100%)"
        icon = "✅"
        title = "Demande acceptée !"
        intro = f"Bonne nouvelle ! {admin_name} a accepté votre demande d'accès."
        badge_color = "background-color: #d1fae5; color: #065f46;"
        permissions_section = f"""
              <div style="background-color: #f0fdf4; border-radius: 8px; padding: 20px; margin-bottom: 20px; border: 1px solid #bbf7d0;">
                <h3 style="color: #166534; font-size: 16px; margin: 0 0 15px 0;">🔓 Permissions accordées</h3>
                <ul style="margin: 0; padding-left: 20px; color: #166534;">
                  {"".join(f'<li style="margin-bottom: 5px;">{perm}</li>' for perm in permissions)}
                </ul>
              </div>
"""
    else:
        header_color = "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)"
        icon = "❌"
        title = "Demande refusée"
        intro = f"{admin_name} n'a pas pu accepter votre demande d'accès."
        badge_color = "background-color: #fee2e2; color: #991b1b;"
        permissions_section = ""

    message_section = ""
    if message:
        message_section = f"""
              <div style="background-color: #f9fafb; border-radius: 6px; padding: 15px; margin-bottom: 20px;">
                <p style="margin: 0; color: #6b7280; font-size: 14px; font-weight: 600;">Message de l'administrateur:</p>
                <p style="margin: 10px 0 0 0; color: #4b5563; font-size: 14px; line-height: 1.5;">{message}</p>
              </div>
"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f4f4;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f4f4; padding: 20px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">

          <!-- Header -->
          <tr>
            <td style="background: {header_color}; padding: 30px; border-radius: 8px 8px 0 0; text-align: center;">
              <div style="font-size: 48px; margin-bottom: 10px;">{icon}</div>
              <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">
                {title}
              </h1>
            </td>
          </tr>

          <!-- Contenu -->
          <tr>
            <td style="padding: 30px;">

              <h2 style="color: #1f2937; font-size: 20px; margin: 0 0 15px 0;">
                Bonjour {requester_name},
              </h2>

              <p style="color: #4b5563; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                {intro}
              </p>

              {permissions_section}

              {message_section}

              <!-- Bouton -->
              <table cellpadding="0" cellspacing="0" style="margin: 25px 0;">
                <tr>
                  <td style="border-radius: 6px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                    <a href="{conversation_url}" style="display: inline-block; padding: 14px 28px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px;">
                      💬 Voir la conversation
                    </a>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f9fafb; padding: 20px; border-radius: 0 0 8px 8px; border-top: 1px solid #e5e7eb;">
              <p style="margin: 0 0 10px 0; color: #6b7280; font-size: 12px; text-align: center;">
                Cet email a été envoyé automatiquement par {organization_name}
              </p>
              <p style="margin: 0; color: #9ca3af; font-size: 11px; text-align: center;">
                © 2024 {organization_name}. Tous droits réservés.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_rights_decision_email(
    to_email: str,
    requester_name: str,
    admin_name: str,
    action: str,
    permissions: list,
    message: str = None,
    conversation_url: str = None,
    organization_name: str = "CYBERGARD AI"
):
    """
    Envoie un email de notification de décision sur une demande de droits.

    Args:
        to_email: Email du demandeur
        requester_name: Nom du demandeur
        admin_name: Nom de l'administrateur qui a traité
        action: 'accept' ou 'reject'
        permissions: Liste des permissions concernées
        message: Message optionnel de l'admin
        conversation_url: URL vers la conversation
        organization_name: Nom de l'organisation
    """

    if not IS_LOCAL_SMTP and (not MAILTRAP_USERNAME or not MAILTRAP_PASSWORD):
        logger.error("❌ Configuration Mailtrap manquante dans .env")
        raise ValueError("Configuration Mailtrap manquante")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = get_rights_decision_email_subject(action)
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email

        # Version texte simple
        action_text = "acceptée" if action == "accept" else "refusée"
        text = f"""Bonjour {requester_name},

Votre demande de droits a été {action_text} par {admin_name}.

"""
        if action == "accept" and permissions:
            text += f"Permissions accordées: {', '.join(permissions)}\n\n"
        if message:
            text += f"Message de l'administrateur:\n{message}\n\n"
        text += f"""Voir la conversation: {conversation_url}

Cordialement,
L'équipe {organization_name}
"""

        html = get_rights_decision_email_html(
            requester_name=requester_name,
            admin_name=admin_name,
            action=action,
            permissions=permissions or [],
            message=message or "",
            conversation_url=conversation_url or "",
            organization_name=organization_name
        )

        part1 = MIMEText(text, 'plain', 'utf-8')
        part2 = MIMEText(html, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        with _create_smtp_connection() as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info(
            f"✅ Email décision droits envoyé à {to_email} - "
            f"Action: {action}, Admin: {admin_name}"
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Erreur d'authentification SMTP - Vérifiez les credentials dans .env")
        raise
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if "SMTPUTF8" in error_msg:
            logger.error(
                f"❌ L'adresse email '{to_email}' contient des caractères non-ASCII. "
                f"Veuillez utiliser une adresse email sans accents."
            )
            raise ValueError(f"L'adresse email ne doit pas contenir de caractères accentués: {to_email}")
        else:
            logger.error(f"❌ Erreur SMTP lors de l'envoi à {to_email}: {e}")
            raise
    except Exception as e:
        logger.error(f"❌ Erreur envoi email décision droits à {to_email}: {e}")
        raise
