# backend/src/templates/activation_email_template.py
"""
Templates HTML pour les emails (activation, réinitialisation, etc.)
"""
import os
from pathlib import Path

# Charger le logo en base64 une seule fois au démarrage du module
def _load_logo_base64():
    """Charge le logo depuis logo.txt et retourne la data URI complète"""
    logo_path = Path(__file__).parent.parent.parent.parent / "frontend" / "public" / "logo.txt"
    try:
        with open(logo_path, 'r') as f:
            base64_data = f.read().strip()
        return f"data:image/png;base64,{base64_data}"
    except Exception as e:
        # Si le logo n'est pas trouvé, retourner None pour utiliser le SVG de fallback
        return None

LOGO_DATA_URI = _load_logo_base64()

def get_activation_email_html(user_name: str, activation_url: str, organization_name: str = "CYBERGARD AI") -> str:
    """
    Template HTML pour l'email d'activation de compte (Utilisateur interne)
    Design cohérent avec le style CYBERGARD AI (thème sombre rouge/noir)

    Args:
        user_name: Nom complet de l'utilisateur
        activation_url: URL d'activation du compte
        organization_name: Nom de l'organisation

    Returns:
        str: HTML formaté pour l'email d'activation
    """
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Activez votre compte</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <!-- Logo CYBERGARD AI -->
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                {'<img src="' + LOGO_DATA_URI + '" alt="CYBERGARD AI Logo" style="width: 100%; height: 100%; object-fit: contain;" />' if LOGO_DATA_URI else '<svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><path d="M9 12l2 2 4-4"></path></svg>'}
            </div>

            <!-- Titre marque -->
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Activez votre compte
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                Plateforme CYBERGARD AI
            </p>
        </div>

        <!-- Contenu -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{user_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Vous avez été invité par <strong style="color: #ffffff;">{organization_name}</strong> à rejoindre la plateforme CYBERGARD AI, la solution d'audit et de pilotage cyber assistée par IA.
            </p>

            <p style="margin: 0 0 32px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Votre compte a été créé avec succès. Pour l'activer et définir votre mot de passe sécurisé, veuillez cliquer sur le bouton ci-dessous :
            </p>

            <!-- Bouton CTA -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{activation_url}"
                   style="display: inline-block;
                          padding: 14px 32px;
                          background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 15px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);">
                    🔐 Activer mon compte et créer mon mot de passe
                </a>
            </div>

            <!-- Bloc : lien personnel -->
            <div style="background: rgba(59, 130, 246, 0.05);
                        border: 1px solid rgba(59, 130, 246, 0.2);
                        padding: 16px;
                        margin: 24px 0;
                        border-radius: 6px;
                        text-align: center;">
                <p style="margin: 0; font-size: 13px; color: #93c5fd; line-height: 1.6;">
                    🔒 Ce lien est <strong>strictement personnel</strong> et valable pendant <strong>7 jours</strong>.<br>
                    Une fois activé, vous pourrez accéder aux services mis à disposition par <strong>{organization_name}</strong> selon votre rôle.
                </p>
            </div>

            <!-- Informations importantes -->
            <div style="background: #374151;
                        border: 1px solid #4b5563;
                        border-radius: 6px;
                        padding: 20px;
                        margin: 32px 0;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #ffffff;">
                    📘 Informations importantes
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        🔑 <strong style="color: #ffffff;">Mot de passe sécurisé</strong> : Votre mot de passe doit contenir au minimum 12 caractères, incluant majuscules, minuscules, chiffres et caractères spéciaux.
                    </div>
                    <div style="margin-bottom: 8px;">
                        ⏳ <strong style="color: #ffffff;">Validité du lien</strong> : Le lien d'activation est valable 7 jours à compter de la réception de cet email.
                    </div>
                    <div>
                        🟢 <strong style="color: #ffffff;">Accès à la plateforme</strong> : Après activation, vous aurez accès aux fonctionnalités définies par votre organisation ({organization_name}) dans CYBERGARD AI.
                    </div>
                </div>
            </div>

            <!-- Lien de secours -->
            <div style="margin: 24px 0 0 0; padding: 16px; background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 6px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: #fbbf24;">
                    ❗Le bouton ne fonctionne pas ?
                </p>
                <p style="margin: 0 0 8px 0; font-size: 13px; color: #fcd34d;">
                    Copiez-collez le lien ci-dessous dans votre navigateur :
                </p>
                <code style="background: #374151;
                             padding: 12px;
                             display: block;
                             word-break: break-all;
                             border-radius: 6px;
                             font-size: 12px;
                             color: #93c5fd;
                             border: 1px solid #4b5563;">
                    {activation_url}
                </code>
            </div>
        </div>

        <!-- Footer -->
        <div style="background: #1a202c;
                    padding: 24px 30px;
                    text-align: center;
                    border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 12px 0; color: #d1d5db; font-size: 14px; font-weight: 500;">
                Bienvenue dans l'équipe,
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
</html>"""


def get_activation_email_text(user_name: str, activation_url: str, organization_name: str = "CYBERGARD AI") -> str:
    """
    Version texte de l'email d'activation (fallback pour clients email sans HTML)

    Args:
        user_name: Nom complet de l'utilisateur
        activation_url: URL d'activation du compte
        organization_name: Nom de l'organisation

    Returns:
        str: Texte formaté pour l'email d'activation
    """
    return f"""CYBERGARD AI - Activez votre compte
Plateforme CYBERGARD AI

Bonjour {user_name},

Vous avez été invité par {organization_name} à rejoindre la plateforme CYBERGARD AI, la solution d'audit et de pilotage cyber assistée par IA.

Votre compte a été créé avec succès. Pour l'activer et définir votre mot de passe sécurisé, veuillez cliquer sur le lien ci-dessous :

🔐 Activer mon compte et créer mon mot de passe : {activation_url}

🔒 LIEN PERSONNEL
Ce lien est strictement personnel et valable pendant 7 jours.
Une fois activé, vous pourrez accéder aux services mis à disposition par {organization_name} selon votre rôle.

📘 INFORMATIONS IMPORTANTES

🔑 Mot de passe sécurisé : Votre mot de passe doit contenir au minimum 12 caractères, incluant majuscules, minuscules, chiffres et caractères spéciaux.

⏳ Validité du lien : Le lien d'activation est valable 7 jours à compter de la réception de cet email.

🟢 Accès à la plateforme : Après activation, vous aurez accès aux fonctionnalités définies par votre organisation ({organization_name}) dans CYBERGARD AI.

❗LE BOUTON NE FONCTIONNE PAS ?
Copiez-collez le lien ci-dessous dans votre navigateur :
{activation_url}

Cordialement,
L'équipe CYBERGARD AI
Plateforme de gestion des audits et plans d'action"""


def get_password_reset_email_html(user_name: str, reset_url: str, organization_name: str = "Vision Agile") -> str:
    """
    Template HTML pour l'email de réinitialisation de mot de passe
    
    Args:
        user_name: Nom complet de l'utilisateur
        reset_url: URL de réinitialisation du mot de passe
        organization_name: Nom de l'organisation
    
    Returns:
        str: HTML formaté pour l'email de réinitialisation
    """
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Réinitialisation de mot de passe</title>
</head>
<body style="font-family: Arial, sans-serif; margin: 0; padding: 0; background-color: #f9fafb;">
    <div style="max-width: 600px; margin: 20px auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
        
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #DC2626 0%, #B91C1C 100%); color: white; padding: 40px 30px; text-align: center;">
            <h1 style="margin: 0; font-size: 28px; font-weight: 700;">🔑 Réinitialisation de mot de passe</h1>
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">{organization_name}</p>
        </div>
        
        <!-- Content -->
        <div style="padding: 40px 30px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #374151;">
                Bonjour <strong>{user_name}</strong>,
            </p>
            
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #374151;">
                Vous avez demandé la réinitialisation de votre mot de passe.
            </p>
            
            <p style="margin: 0 0 30px 0; font-size: 16px; color: #374151;">
                Pour créer un nouveau mot de passe, veuillez cliquer sur le bouton ci-dessous :
            </p>
            
            <!-- Button -->
            <div style="text-align: center; margin: 30px 0;">
                <a href="{reset_url}" 
                   style="display: inline-block; 
                          padding: 16px 32px; 
                          background: linear-gradient(135deg, #DC2626 0%, #B91C1C 100%); 
                          color: white; 
                          text-decoration: none; 
                          border-radius: 8px; 
                          font-weight: 600; 
                          font-size: 16px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.4);">
                    Réinitialiser mon mot de passe
                </a>
            </div>
            
            <!-- Warning box -->
            <div style="background: #FEF2F2; 
                        border-left: 4px solid #DC2626; 
                        padding: 16px; 
                        margin: 30px 0;
                        border-radius: 4px;">
                <p style="margin: 0; font-size: 14px; color: #991B1B;">
                    <strong>⚠️ Important :</strong><br>
                    Ce lien est valide pendant <strong>1 heure</strong>.<br>
                    Si vous n'avez pas demandé cette réinitialisation, ignorez cet email et votre mot de passe restera inchangé.
                </p>
            </div>
            
            <p style="margin: 20px 0 0 0; font-size: 14px; color: #6B7280;">
                Si le bouton ne fonctionne pas, copiez et collez ce lien dans votre navigateur :<br>
                <code style="background: #F3F4F6; 
                             padding: 8px; 
                             display: block; 
                             margin-top: 8px; 
                             word-break: break-all; 
                             border-radius: 4px;
                             font-size: 12px;">
                    {reset_url}
                </code>
            </p>
        </div>
        
        <!-- Footer -->
        <div style="background: #F9FAFB; 
                    padding: 30px; 
                    text-align: center; 
                    border-top: 1px solid #E5E7EB;">
            <p style="margin: 0 0 10px 0; color: #6B7280; font-size: 14px;">
                © 2025 {organization_name} - Tous droits réservés
            </p>
            <p style="margin: 0; color: #9CA3AF; font-size: 12px;">
                Cet email a été envoyé automatiquement, merci de ne pas y répondre.
            </p>
        </div>
    </div>
</body>
</html>"""


def get_password_reset_email_text(user_name: str, reset_url: str, organization_name: str = "Vision Agile") -> str:
    """
    Version texte de l'email de réinitialisation de mot de passe
    
    Args:
        user_name: Nom complet de l'utilisateur
        reset_url: URL de réinitialisation du mot de passe
        organization_name: Nom de l'organisation
    
    Returns:
        str: Texte formaté pour l'email de réinitialisation
    """
    return f"""Bonjour {user_name},

Vous avez demandé la réinitialisation de votre mot de passe.

Pour créer un nouveau mot de passe, cliquez sur ce lien : {reset_url}

⚠️ IMPORTANT : Ce lien est valide pendant 1 heure seulement.

Si vous n'avez pas demandé cette réinitialisation, ignorez cet email et votre mot de passe restera inchangé.

Cordialement,
L'équipe {organization_name}

---
© 2025 {organization_name} - Tous droits réservés
Cet email a été envoyé automatiquement, merci de ne pas y répondre."""


def get_auditee_activation_email_html(
    user_name: str,
    activation_url: str,
    organization_name: str = "Cybergard",
    entity_name: str = None
) -> str:
    """
    Template HTML pour l'email d'invitation à l'audit (Audité)
    Design cohérent avec la page d'activation (version verte pour audités)

    Args:
        user_name: Nom complet de l'utilisateur
        activation_url: URL d'activation du compte
        organization_name: Nom de l'organisation (Cybergard par défaut)
        entity_name: Nom de la société rattachée/entité auditée

    Returns:
        str: HTML formaté pour l'email d'invitation à l'audit
    """
    entity_info = f"<strong style='color: #111827;'>{entity_name}</strong>" if entity_name else "votre organisation"

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Invitation à participer à votre audit de conformité</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 50%, #a7f3d0 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15); border: 2px solid #86efac;">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 40px 30px 32px 30px; background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);">
            <!-- Logo CYBERGARD AI -->
            <div style="width: 80px; height: 80px; border-radius: 16px; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 16px; box-shadow: 0 8px 24px rgba(5, 150, 105, 0.3); background: linear-gradient(135deg, #059669 0%, #047857 100%); padding: 8px; overflow: hidden;">
                {'<img src="' + LOGO_DATA_URI + '" alt="CYBERGARD AI Logo" style="width: 100%; height: 100%; object-fit: contain;" />' if LOGO_DATA_URI else '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path></svg>'}
            </div>

            <!-- Titre avec gradient -->
            <h1 style="margin: 0; font-size: 30px; font-weight: 700; background: linear-gradient(135deg, #059669 0%, #047857 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">
                Invitation à l'audit de conformité
            </h1>
            <p style="margin: 8px 0 0 0; font-size: 16px; color: #6b7280;">
                Plateforme Cybergard
            </p>
        </div>

        <!-- Contenu -->
        <div style="padding: 40px 30px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #374151; line-height: 1.6;">
                Bonjour <strong style="color: #111827;">{user_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #374151; line-height: 1.6;">
                Vous avez été invité par la société {entity_info} à participer à un <strong style="color: #111827;">audit de conformité</strong> sur la plateforme Cybergard.
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #374151; line-height: 1.6;">
                Cet audit vise à évaluer les pratiques et dispositifs en place au sein de votre organisation.
                Votre participation est essentielle pour garantir la qualité et la fiabilité de l'évaluation.
            </p>

            <!-- Section "Pour commencer" -->
            <div style="background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
                        border-left: 4px solid #059669;
                        padding: 20px;
                        margin: 28px 0;
                        border-radius: 8px;">
                <p style="margin: 0 0 12px 0; font-size: 15px; font-weight: 700; color: #065f46;">
                    📝 Pour commencer votre audit :
                </p>
                <p style="margin: 0; font-size: 14px; color: #166534; line-height: 1.6;">
                    Cliquez sur le lien ci-dessous pour activer votre accès sécurisé et réaliser votre audit :
                </p>
            </div>

            <!-- Bouton CTA -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{activation_url}"
                   style="display: inline-block;
                          padding: 16px 32px;
                          background: linear-gradient(135deg, #059669 0%, #047857 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 8px;
                          font-weight: 600;
                          font-size: 16px;
                          box-shadow: 0 8px 24px rgba(5, 150, 105, 0.3);
                          transition: all 0.2s;">
                    👉 Commencer mon audit
                </a>
            </div>

            <!-- Info temporelle -->
            <div style="background: #fef3c7;
                        border: 1px solid #fbbf24;
                        padding: 16px;
                        margin: 24px 0;
                        border-radius: 8px;
                        text-align: center;">
                <p style="margin: 0; font-size: 14px; color: #78350f; line-height: 1.6;">
                    ⏳ Ce lien est <strong>strictement personnel</strong> et valide pendant <strong>7 jours</strong> à compter de la réception de ce message.<br>
                    Vous pouvez reprendre votre audit à tout moment durant cette période en utilisant le même lien.
                </p>
            </div>

            <!-- Info box stylée -->
            <div style="background: linear-gradient(135deg, #f9fafb 0%, #ecfdf5 100%);
                        border: 2px solid #e5e7eb;
                        border-radius: 12px;
                        padding: 20px;
                        margin: 32px 0;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #1f2937; display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 18px;">⚠️</span>
                    Informations importantes
                </p>
                <div style="font-size: 14px; color: #4b5563; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        🔒 <strong style="color: #111827;">Le lien ne doit pas être partagé</strong> : il contient votre accès personnel.
                    </div>
                    <div style="margin-bottom: 8px;">
                        🔄 Si le lien a expiré, vous pouvez demander une nouvelle invitation auprès de votre contact ou de l'administrateur Cybergard.
                    </div>
                    <div>
                        ✅ Une fois l'audit terminé, vos réponses seront automatiquement enregistrées et intégrées à la campagne en cours.
                    </div>
                </div>
            </div>

            <!-- Lien de secours -->
            <div style="margin: 24px 0 0 0; padding: 16px; background: #fefce8; border: 1px solid #fde047; border-radius: 8px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: #854d0e;">
                    ℹ️ Ou copiez ce lien dans votre navigateur :
                </p>
                <code style="background: #ffffff;
                             padding: 12px;
                             display: block;
                             word-break: break-all;
                             border-radius: 6px;
                             font-size: 12px;
                             color: #059669;
                             border: 1px solid #e5e7eb;">
                    {activation_url}
                </code>
            </div>
        </div>

        <!-- Footer -->
        <div style="background: #f9fafb;
                    padding: 24px 30px;
                    text-align: center;
                    border-top: 1px solid #e5e7eb;">
            <p style="margin: 0 0 12px 0; color: #374151; font-size: 14px; font-weight: 500;">
                Merci pour votre collaboration,
            </p>
            <p style="margin: 0 0 8px 0; color: #6b7280; font-size: 14px; font-weight: 600;">
                L'équipe Cybergard
            </p>
            <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                Plateforme de gestion des audits et plans d'action
            </p>
        </div>
    </div>

</body>
</html>"""


def get_auditee_activation_email_text(
    user_name: str,
    activation_url: str,
    organization_name: str = "Cybergard",
    entity_name: str = None
) -> str:
    """
    Version texte de l'email d'invitation à l'audit (Audité)

    Args:
        user_name: Nom complet de l'utilisateur
        activation_url: URL d'activation du compte
        organization_name: Nom de l'organisation (Cybergard par défaut)
        entity_name: Nom de la société rattachée/entité auditée

    Returns:
        str: Texte formaté pour l'email d'invitation à l'audit
    """
    entity_info = f"{entity_name}" if entity_name else "votre organisation"

    return f"""Bonjour {user_name},

Vous avez été invité par la société {entity_info} à participer à un audit de conformité sur la plateforme Cybergard.

Cet audit vise à évaluer les pratiques et dispositifs en place au sein de votre organisation.
Votre participation est essentielle pour garantir la qualité et la fiabilité de l'évaluation.

📝 POUR COMMENCER VOTRE AUDIT :

Cliquez sur le lien ci-dessous pour activer votre accès sécurisé et réaliser votre audit :
{activation_url}

⏳ Ce lien est strictement personnel et valide pendant 7 jours à compter de la réception de ce message.
Vous pouvez reprendre votre audit à tout moment durant cette période en utilisant le même lien.

⚠️ INFORMATIONS IMPORTANTES :

• Le lien ne doit pas être partagé : il contient votre accès personnel.
• Si le lien a expiré, vous pouvez demander une nouvelle invitation auprès de votre contact ou de l'administrateur Cybergard.
• Une fois l'audit terminé, vos réponses seront automatiquement enregistrées et intégrées à la campagne en cours.

Merci pour votre collaboration,
L'équipe Cybergard
Plateforme de gestion des audits et plans d'action"""


def get_magic_link_email_html(
    user_name: str,
    magic_link: str,
    campaign_name: str,
    entity_name: str,
    organization_name: str = "CYBERGARD AI",
    expiry_days: int = 7,
    max_uses: int = 10
) -> str:
    """
    Template HTML pour l'email avec lien magique (accès audit sans mot de passe)
    Design cohérent avec la page d'activation (style rouge foncé CYBERGARD AI)
    Le logo est intégré en base64 pour éviter les problèmes d'affichage dans les clients email.

    Args:
        user_name: Nom complet de l'utilisateur
        magic_link: URL du lien magique avec token JWT
        campaign_name: Nom de la campagne d'audit
        entity_name: Nom de l'entité auditée
        organization_name: Nom de l'organisation (CYBERGARD AI par défaut)
        expiry_days: Nombre de jours avant expiration du lien
        max_uses: Nombre maximal d'utilisations

    Returns:
        str: HTML formaté pour l'email avec lien magique
    """

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Accès à votre audit de conformité</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <!-- Logo CYBERGARD AI -->
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                {'<img src="' + LOGO_DATA_URI + '" alt="CYBERGARD AI Logo" style="width: 100%; height: 100%; object-fit: contain;" />' if LOGO_DATA_URI else '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><path d="M9 12l2 2 4-4"></path></svg>'}
            </div>

            <!-- Titre marque -->
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Accédez à votre audit
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
                Vous participez à un <strong style="color: #ffffff;">audit de conformité {campaign_name}</strong>.
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Cet audit est organisé par <strong style="color: #ffffff;">{organization_name}</strong> pour l'entité <strong style="color: #ffffff;">{entity_name}</strong>.
            </p>

            <p style="margin: 0 0 32px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Cliquez sur le bouton ci-dessous pour accéder directement à votre questionnaire d'audit. Aucun mot de passe n'est nécessaire.
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
                    ✨ Accéder à mon audit
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
                    ⏳ Ce lien est <strong>strictement personnel</strong> et valide pendant <strong>{expiry_days} jours</strong>.<br>
                    Vous pouvez l'utiliser jusqu'à <strong>{max_uses} fois</strong> pour compléter votre audit à votre rythme.
                </p>
            </div>

            <!-- Info box stylée -->
            <div style="background: #374151;
                        border: 1px solid #4b5563;
                        border-radius: 6px;
                        padding: 20px;
                        margin: 32px 0;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #ffffff;">
                    💡 Points importants
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        🔒 <strong style="color: #ffffff;">Lien personnel</strong> : Ne partagez pas ce lien, il est unique et lié à votre email.
                    </div>
                    <div style="margin-bottom: 8px;">
                        💾 <strong style="color: #ffffff;">Sauvegarde automatique</strong> : Vos réponses sont enregistrées au fur et à mesure.
                    </div>
                    <div style="margin-bottom: 8px;">
                        🔄 <strong style="color: #ffffff;">Reprise possible</strong> : Vous pouvez revenir sur ce lien plusieurs fois pour modifier vos réponses.
                    </div>
                    <div>
                        🔐 <strong style="color: #ffffff;">Confidentialité</strong> : Vos réponses sont strictement confidentielles.
                    </div>
                </div>
            </div>

            <!-- Lien de secours -->
            <div style="margin: 24px 0 0 0; padding: 16px; background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 6px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: #fbbf24;">
                    ℹ️ Le bouton ne fonctionne pas ?
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
                Merci pour votre participation,
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
</html>"""


def get_magic_link_email_text(
    user_name: str,
    magic_link: str,
    campaign_name: str,
    entity_name: str,
    organization_name: str = "CYBERGARD AI",
    expiry_days: int = 7,
    max_uses: int = 10
) -> str:
    """
    Version texte de l'email avec lien magique

    Args:
        user_name: Nom complet de l'utilisateur
        magic_link: URL du lien magique avec token JWT
        campaign_name: Nom de la campagne d'audit
        entity_name: Nom de l'entité auditée
        organization_name: Nom de l'organisation (CYBERGARD AI par défaut)
        expiry_days: Nombre de jours avant expiration
        max_uses: Nombre maximal d'utilisations

    Returns:
        str: Texte formaté pour l'email
    """
    return f"""Bonjour {user_name},

Vous participez à un audit de conformité {campaign_name}.

Cet audit est organisé par {organization_name} pour l'entité {entity_name}.

✨ ACCÉDER À VOTRE AUDIT :

Cliquez sur le lien ci-dessous pour accéder directement à votre questionnaire.
Aucun mot de passe n'est nécessaire.

{magic_link}

⏳ VALIDITÉ DU LIEN :

• Valide pendant {expiry_days} jours
• Utilisable jusqu'à {max_uses} fois
• Strictement personnel (ne pas partager)

💡 POINTS IMPORTANTS :

• Vos réponses sont sauvegardées automatiquement
• Vous pouvez revenir sur ce lien pour modifier vos réponses
• Toutes vos réponses sont strictement confidentielles

Merci pour votre participation,
L'équipe {organization_name}
Plateforme de gestion des audits et plans d'action"""


def get_client_admin_creation_email_html(
    user_name: str,
    organization_name: str,
    activation_url: str,
    temp_password: str = None
) -> str:
    """
    Template HTML pour l'email de création d'un nouveau client admin

    Args:
        user_name: Nom complet de l'utilisateur admin
        organization_name: Nom de l'organisation créée
        activation_url: URL d'activation du compte
        temp_password: Mot de passe temporaire (optionnel, pour information)

    Returns:
        str: HTML formaté pour l'email de création client admin
    """
    password_info = f"""
            <div style="background: #fef3c7;
                        border: 1px solid #fbbf24;
                        padding: 16px;
                        margin: 24px 0;
                        border-radius: 8px;">
                <p style="margin: 0 0 8px 0; font-size: 14px; font-weight: 600; color: #78350f;">
                    🔑 Mot de passe temporaire généré
                </p>
                <p style="margin: 0 0 8px 0; font-size: 13px; color: #78350f;">
                    Pour votre information, voici le mot de passe temporaire qui a été généré :
                </p>
                <code style="background: #ffffff;
                             padding: 12px;
                             display: block;
                             word-break: break-all;
                             border-radius: 6px;
                             font-size: 14px;
                             font-weight: 600;
                             color: #dc2626;
                             border: 1px solid #fbbf24;">
                    {temp_password}
                </code>
                <p style="margin: 8px 0 0 0; font-size: 12px; color: #78350f; font-style: italic;">
                    ⚠️ Ce mot de passe sera invalidé après activation. Vous devrez en créer un nouveau.
                </p>
            </div>
    """ if temp_password else ""

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Votre organisation a été créée</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <!-- Logo CYBERGARD AI -->
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                {'<img src="' + LOGO_DATA_URI + '" alt="CYBERGARD AI Logo" style="width: 100%; height: 100%; object-fit: contain;" />' if LOGO_DATA_URI else '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><path d="M9 12l2 2 4-4"></path></svg>'}
            </div>

            <!-- Titre marque -->
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                🎉 Bienvenue sur CYBERGARD AI !
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                Votre organisation a été créée avec succès
            </p>
        </div>

        <!-- Contenu -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{user_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Votre organisation <strong style="color: #ffffff;">{organization_name}</strong> a été créée sur la plateforme CYBERGARD AI.
                Nous sommes ravis de vous accompagner dans la transformation de votre démarche de pilotage cyber et de conformité.
            </p>

            <!-- Vision écosystème -->
            <div style="background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
                        border-left: 4px solid #dc2626;
                        padding: 20px;
                        margin: 24px 0;
                        border-radius: 8px;">
                <p style="margin: 0 0 12px 0; font-size: 16px; font-weight: 700; color: #ffffff;">
                    🌐 Une plateforme pensée pour votre écosystème
                </p>
                <p style="margin: 0 0 16px 0; font-size: 14px; color: #d1d5db; line-height: 1.6;">
                    CYBERGARD AI vous offre une vision complète et dynamique de votre organisation :
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        🔹 <strong style="color: #ffffff;">Pôles internes</strong> : Suivez la conformité par pôle (DSI, RH, Finance, Production)
                    </div>
                    <div style="margin-bottom: 8px;">
                        🔹 <strong style="color: #ffffff;">Catégories externes</strong> : Pilotez la maturité de vos fournisseurs et prestataires
                    </div>
                    <div>
                        🔹 <strong style="color: #ffffff;">Entités & relations</strong> : Vision claire de toutes vos entités et leur statut
                    </div>
                </div>
            </div>

            <!-- Cross-référentiel -->
            <div style="background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
                        border-left: 4px solid #fbbf24;
                        padding: 20px;
                        margin: 24px 0;
                        border-radius: 8px;">
                <p style="margin: 0 0 12px 0; font-size: 16px; font-weight: 700; color: #ffffff;">
                    🔀 Cross-référentiel : une révolution du pilotage conformité
                </p>
                <p style="margin: 0 0 16px 0; font-size: 14px; color: #d1d5db; line-height: 1.6;">
                    Croisez plusieurs référentiels (ISO 27001, NIS2, HDS, RGPD, PCI-DSS) pour :
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">✓ Éviter les redondances</div>
                    <div style="margin-bottom: 8px;">✓ Mutualiser les efforts d'audit</div>
                    <div style="margin-bottom: 8px;">✓ Offrir une vision consolidée de la conformité</div>
                    <div>✓ Identifier les écarts communs à plusieurs standards</div>
                </div>
            </div>

            <!-- IA -->
            <div style="background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
                        border-left: 4px solid #3b82f6;
                        padding: 20px;
                        margin: 24px 0;
                        border-radius: 8px;">
                <p style="margin: 0 0 12px 0; font-size: 16px; font-weight: 700; color: #ffffff;">
                    🤖 Une IA qui assiste chaque étape de vos audits
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 6px;">• Génération intelligente des questionnaires</div>
                    <div style="margin-bottom: 6px;">• Consolidation automatique des preuves</div>
                    <div style="margin-bottom: 6px;">• Détection automatique des risques</div>
                    <div style="margin-bottom: 6px;">• Génération d'actions correctives</div>
                    <div>• Pré-rédaction du rapport d'audit</div>
                </div>
            </div>

            <p style="margin: 24px 0 16px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Vous avez été désigné comme <strong style="color: #fbbf24;">administrateur principal</strong>.
                Pour activer votre compte et définir votre mot de passe sécurisé, cliquez sur le bouton ci-dessous :
            </p>

            <!-- Bouton CTA -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{activation_url}"
                   style="display: inline-block;
                          padding: 14px 32px;
                          background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 15px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);">
                    🔐 Activer mon compte administrateur
                </a>
            </div>

            {password_info}

            <!-- Info temporelle -->
            <div style="background: rgba(59, 130, 246, 0.05);
                        border: 1px solid rgba(59, 130, 246, 0.2);
                        padding: 16px;
                        margin: 24px 0;
                        border-radius: 6px;
                        text-align: center;">
                <p style="margin: 0; font-size: 13px; color: #93c5fd; line-height: 1.6;">
                    ⏳ Ce lien d'activation est <strong>valide pendant 7 jours</strong>.<br>
                    Vous devrez créer un mot de passe sécurisé lors de l'activation.
                </p>
            </div>

            <!-- Info box stylée -->
            <div style="background: #374151;
                        border: 1px solid #4b5563;
                        border-radius: 6px;
                        padding: 20px;
                        margin: 32px 0;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #ffffff;">
                    💡 En tant qu'administrateur, vous pourrez :
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        👥 <strong style="color: #ffffff;">Gérer les utilisateurs</strong> : Inviter et gérer les membres de votre équipe
                    </div>
                    <div style="margin-bottom: 8px;">
                        🏢 <strong style="color: #ffffff;">Gérer l'écosystème</strong> : Ajouter clients, fournisseurs et partenaires
                    </div>
                    <div style="margin-bottom: 8px;">
                        📋 <strong style="color: #ffffff;">Créer des audits</strong> : Lancer des campagnes d'audit de conformité
                    </div>
                    <div>
                        📊 <strong style="color: #ffffff;">Suivre la conformité</strong> : Accéder aux tableaux de bord et rapports
                    </div>
                </div>
            </div>

            <!-- Lien de secours -->
            <div style="margin: 24px 0 0 0; padding: 16px; background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 6px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: #fbbf24;">
                    ℹ️ Le bouton ne fonctionne pas ?
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
                    {activation_url}
                </code>
            </div>
        </div>

        <!-- Footer -->
        <div style="background: #1a202c;
                    padding: 24px 30px;
                    text-align: center;
                    border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 12px 0; color: #d1d5db; font-size: 14px; font-weight: 500;">
                Bienvenue dans CYBERGARD AI,
            </p>
            <p style="margin: 0 0 8px 0; color: #ffffff; font-size: 14px; font-weight: 600;">
                L'équipe CYBERGARD AI
            </p>
            <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                Plateforme de gestion des audits et plans d'action
            </p>
        </div>
    </div>

</body>
</html>"""


def get_client_admin_creation_email_text(
    user_name: str,
    organization_name: str,
    activation_url: str,
    temp_password: str = None
) -> str:
    """
    Version texte de l'email de création client admin

    Args:
        user_name: Nom complet de l'utilisateur admin
        organization_name: Nom de l'organisation créée
        activation_url: URL d'activation du compte
        temp_password: Mot de passe temporaire (optionnel)

    Returns:
        str: Texte formaté pour l'email
    """
    password_section = f"""
🔑 MOT DE PASSE TEMPORAIRE GÉNÉRÉ :

{temp_password}

⚠️ Ce mot de passe sera invalidé après activation. Vous devrez en créer un nouveau.
""" if temp_password else ""

    return f"""Bonjour {user_name},

Bienvenue sur CYBERGARD AI !

Votre organisation {organization_name} a été créée sur la plateforme CYBERGARD AI.
Nous sommes ravis de vous accompagner dans la transformation de votre démarche de pilotage cyber et de conformité.

🌐 UNE PLATEFORME PENSÉE POUR VOTRE ÉCOSYSTÈME

CYBERGARD AI vous offre une vision complète et dynamique de votre organisation :

🔹 Pôles internes : Suivez la conformité par pôle (DSI, RH, Finance, Production)
🔹 Catégories externes : Pilotez la maturité de vos fournisseurs et prestataires
🔹 Entités & relations : Vision claire de toutes vos entités et leur statut

🔀 CROSS-RÉFÉRENTIEL : UNE RÉVOLUTION DU PILOTAGE CONFORMITÉ

Croisez plusieurs référentiels (ISO 27001, NIS2, HDS, RGPD, PCI-DSS) pour :

✓ Éviter les redondances
✓ Mutualiser les efforts d'audit
✓ Offrir une vision consolidée de la conformité
✓ Identifier les écarts communs à plusieurs standards

🤖 UNE IA QUI ASSISTE CHAQUE ÉTAPE DE VOS AUDITS

• Génération intelligente des questionnaires
• Consolidation automatique des preuves
• Détection automatique des risques
• Génération d'actions correctives
• Pré-rédaction du rapport d'audit

🔐 ACTIVER VOTRE COMPTE :

Vous avez été désigné comme administrateur principal.
Pour activer votre compte et définir votre mot de passe sécurisé, cliquez sur le lien ci-dessous :

{activation_url}

{password_section}
⏳ VALIDITÉ DU LIEN :

• Ce lien d'activation est valide pendant 7 jours
• Vous devrez créer un mot de passe sécurisé lors de l'activation

💡 EN TANT QU'ADMINISTRATEUR, VOUS POURREZ :

• Gérer les utilisateurs : Inviter et gérer les membres de votre équipe
• Gérer l'écosystème : Ajouter clients, fournisseurs et partenaires
• Créer des audits : Lancer des campagnes d'audit de conformité
• Suivre la conformité : Accéder aux tableaux de bord et rapports

🤝 NOUS SOMMES À VOS CÔTÉS

Notre équipe reste disponible pour vous accompagner dans votre mise en route : création d'audits,
import des référentiels, structuration de votre écosystème, activation des pôles, ou configuration de vos campagnes.

Merci encore pour votre confiance,
L'équipe CYBERGARD AI
Plateforme de gestion des audits et plans d'action"""


def get_activation_confirmation_email_html(
    user_name: str,
    login_url: str,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """
    Template HTML pour l'email de confirmation d'activation de compte
    Envoyé après que l'utilisateur a activé son compte avec succès
    Design cohérent avec le style CYBERGARD AI (thème sombre rouge/noir)

    Args:
        user_name: Nom complet de l'utilisateur
        login_url: URL de la page de connexion
        organization_name: Nom de l'organisation/tenant

    Returns:
        str: HTML formaté pour l'email de confirmation
    """
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Compte activé avec succès</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <!-- Logo CYBERGARD AI -->
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                {'<img src="' + LOGO_DATA_URI + '" alt="CYBERGARD AI Logo" style="width: 100%; height: 100%; object-fit: contain;" />' if LOGO_DATA_URI else '<svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><path d="M9 12l2 2 4-4"></path></svg>'}
            </div>

            <!-- Titre marque -->
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre avec icône succès -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <!-- Badge succès -->
            <div style="width: 80px; height: 80px; margin: 0 auto 20px; border-radius: 50%; background: linear-gradient(135deg, #10b981 0%, #059669 100%); display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 24px rgba(16, 185, 129, 0.4);">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            </div>
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: #10b981;">
                Compte activé avec succès ! 🎉
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                Bienvenue sur la plateforme CYBERGARD AI
            </p>
        </div>

        <!-- Contenu -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{user_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Félicitations ! Votre compte sur la plateforme <strong style="color: #ffffff;">CYBERGARD AI</strong> a été activé avec succès.
            </p>

            <p style="margin: 0 0 32px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Vous pouvez désormais vous connecter à votre espace <strong style="color: #ffffff;">{organization_name}</strong> et accéder à l'ensemble des fonctionnalités mises à votre disposition.
            </p>

            <!-- Bouton CTA -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{login_url}"
                   style="display: inline-block;
                          padding: 14px 32px;
                          background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 15px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);">
                    🚀 Se connecter à CYBERGARD AI
                </a>
            </div>

            <!-- Récapitulatif compte -->
            <div style="background: rgba(16, 185, 129, 0.1);
                        border: 1px solid rgba(16, 185, 129, 0.3);
                        padding: 20px;
                        margin: 24px 0;
                        border-radius: 6px;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #10b981;">
                    ✅ Récapitulatif de votre compte
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        👤 <strong style="color: #ffffff;">Utilisateur :</strong> {user_name}
                    </div>
                    <div style="margin-bottom: 8px;">
                        🏢 <strong style="color: #ffffff;">Organisation :</strong> {organization_name}
                    </div>
                    <div>
                        🔒 <strong style="color: #ffffff;">Statut :</strong> <span style="color: #10b981;">Actif</span>
                    </div>
                </div>
            </div>

            <!-- Prochaines étapes -->
            <div style="background: #374151;
                        border: 1px solid #4b5563;
                        border-radius: 6px;
                        padding: 20px;
                        margin: 32px 0;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #ffffff;">
                    📋 Prochaines étapes
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        1️⃣ <strong style="color: #ffffff;">Connectez-vous</strong> à votre espace personnel avec vos identifiants
                    </div>
                    <div style="margin-bottom: 8px;">
                        2️⃣ <strong style="color: #ffffff;">Explorez</strong> les différentes fonctionnalités de la plateforme
                    </div>
                    <div>
                        3️⃣ <strong style="color: #ffffff;">Contactez-nous</strong> si vous avez des questions ou besoin d'assistance
                    </div>
                </div>
            </div>

            <!-- Conseil sécurité -->
            <div style="margin: 24px 0 0 0; padding: 16px; background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.2); border-radius: 6px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: #93c5fd;">
                    🔐 Conseil de sécurité
                </p>
                <p style="margin: 0; font-size: 13px; color: #93c5fd; line-height: 1.6;">
                    Ne partagez jamais vos identifiants de connexion. En cas de suspicion d'accès non autorisé,
                    changez immédiatement votre mot de passe et contactez votre administrateur.
                </p>
            </div>
        </div>

        <!-- Footer -->
        <div style="background: #1a202c;
                    padding: 24px 30px;
                    text-align: center;
                    border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 12px 0; color: #d1d5db; font-size: 14px; font-weight: 500;">
                Bienvenue dans l'équipe !
            </p>
            <p style="margin: 0 0 8px 0; color: #ffffff; font-size: 14px; font-weight: 600;">
                L'équipe CYBERGARD AI
            </p>
            <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                La plateforme intelligente d'audit et de pilotage cyber
            </p>
        </div>
    </div>

</body>
</html>"""


def get_activation_confirmation_email_text(
    user_name: str,
    login_url: str,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """
    Template texte pour l'email de confirmation d'activation de compte
    Version texte brut pour les clients email qui ne supportent pas HTML

    Args:
        user_name: Nom complet de l'utilisateur
        login_url: URL de la page de connexion
        organization_name: Nom de l'organisation/tenant

    Returns:
        str: Texte formaté pour l'email de confirmation
    """
    return f"""
CYBERGARD AI - Compte activé avec succès ! 🎉

Bonjour {user_name},

Félicitations ! Votre compte sur la plateforme CYBERGARD AI a été activé avec succès.

Vous pouvez désormais vous connecter à votre espace {organization_name} et accéder à l'ensemble des fonctionnalités mises à votre disposition.

🔗 Se connecter : {login_url}

═══════════════════════════════════════════════════
✅ RÉCAPITULATIF DE VOTRE COMPTE
═══════════════════════════════════════════════════

👤 Utilisateur : {user_name}
🏢 Organisation : {organization_name}
🔒 Statut : Actif

═══════════════════════════════════════════════════
📋 PROCHAINES ÉTAPES
═══════════════════════════════════════════════════

1️⃣ Connectez-vous à votre espace personnel avec vos identifiants
2️⃣ Explorez les différentes fonctionnalités de la plateforme
3️⃣ Contactez-nous si vous avez des questions ou besoin d'assistance

═══════════════════════════════════════════════════
🔐 CONSEIL DE SÉCURITÉ
═══════════════════════════════════════════════════

Ne partagez jamais vos identifiants de connexion. En cas de suspicion d'accès non autorisé, changez immédiatement votre mot de passe et contactez votre administrateur.

---

Bienvenue dans l'équipe !

L'équipe CYBERGARD AI
La plateforme intelligente d'audit et de pilotage cyber

Cet email a été envoyé automatiquement, merci de ne pas y répondre.
"""


def get_welcome_email_html(user_name: str, organization_name: str = "Vision Agile") -> str:
    """
    Template HTML pour l'email de bienvenue (après activation)

    Args:
        user_name: Nom complet de l'utilisateur
        organization_name: Nom de l'organisation

    Returns:
        str: HTML formaté pour l'email de bienvenue
    """
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bienvenue !</title>
</head>
<body style="font-family: Arial, sans-serif; margin: 0; padding: 0; background-color: #f9fafb;">
    <div style="max-width: 600px; margin: 20px auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
        
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #10B981 0%, #059669 100%); color: white; padding: 40px 30px; text-align: center;">
            <h1 style="margin: 0; font-size: 28px; font-weight: 700;">🎉 Bienvenue !</h1>
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">{organization_name}</p>
        </div>
        
        <!-- Content -->
        <div style="padding: 40px 30px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #374151;">
                Bonjour <strong>{user_name}</strong>,
            </p>
            
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #374151;">
                Votre compte a été activé avec succès ! 🎉
            </p>
            
            <p style="margin: 0 0 30px 0; font-size: 16px; color: #374151;">
                Vous pouvez maintenant vous connecter et commencer à utiliser notre plateforme.
            </p>
            
            <!-- Success box -->
            <div style="background: #ECFDF5; 
                        border-left: 4px solid #10B981; 
                        padding: 16px; 
                        margin: 30px 0;
                        border-radius: 4px;">
                <p style="margin: 0; font-size: 14px; color: #065F46;">
                    <strong>✅ Prochaines étapes :</strong><br>
                    • Connectez-vous à votre compte<br>
                    • Explorez les fonctionnalités<br>
                    • N'hésitez pas à nous contacter si vous avez des questions
                </p>
            </div>
        </div>
        
        <!-- Footer -->
        <div style="background: #F9FAFB; 
                    padding: 30px; 
                    text-align: center; 
                    border-top: 1px solid #E5E7EB;">
            <p style="margin: 0 0 10px 0; color: #6B7280; font-size: 14px;">
                © 2025 {organization_name} - Tous droits réservés
            </p>
            <p style="margin: 0; color: #9CA3AF; font-size: 12px;">
                Cet email a été envoyé automatiquement, merci de ne pas y répondre.
            </p>
        </div>
    </div>
</body>
</html>"""