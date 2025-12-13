# backend/src/templates/discussion_notification_email_template.py
"""
Templates HTML pour les emails de notification du module Discussions.

Types de notifications:
- Nouveau message dans une conversation
- Message système (changement de statut, etc.)
- Mention dans un message
"""

from pathlib import Path


def _load_logo_base64():
    """Charge le logo depuis logo.txt et retourne la data URI complète"""
    logo_path = Path(__file__).parent.parent.parent.parent / "frontend" / "public" / "logo.txt"
    try:
        with open(logo_path, 'r') as f:
            base64_data = f.read().strip()
        return f"data:image/png;base64,{base64_data}"
    except Exception:
        return None


LOGO_DATA_URI = _load_logo_base64()


def get_discussion_new_message_email_subject(
    conversation_title: str,
    sender_name: str
) -> str:
    """
    Génère le sujet de l'email pour un nouveau message de discussion.

    Args:
        conversation_title: Titre de la conversation
        sender_name: Nom de l'expéditeur du message

    Returns:
        str: Sujet de l'email
    """
    return f"Nouveau message de {sender_name} - {conversation_title}"


def get_discussion_new_message_email_html(
    recipient_name: str,
    sender_name: str,
    conversation_title: str,
    conversation_type: str,
    message_preview: str,
    conversation_url: str,
    campaign_name: str = None,
    entity_name: str = None,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """
    Template HTML pour l'email de notification d'un nouveau message dans une discussion.

    Args:
        recipient_name: Nom du destinataire
        sender_name: Nom de l'expéditeur du message
        conversation_title: Titre de la conversation
        conversation_type: Type de conversation (RIGHTS, ACTION, QUESTION, DIRECT_MESSAGE)
        message_preview: Aperçu du message (premiers 200 caractères)
        conversation_url: URL pour accéder à la conversation
        campaign_name: Nom de la campagne (optionnel)
        entity_name: Nom de l'entité (optionnel)
        organization_name: Nom de l'organisation

    Returns:
        str: HTML formaté pour l'email
    """
    # Mapping des types de conversation pour affichage
    type_labels = {
        "RIGHTS": "Demande de droits",
        "ACTION": "Discussion sur une action",
        "QUESTION": "Discussion sur une question",
        "DIRECT_MESSAGE": "Message direct"
    }
    type_label = type_labels.get(conversation_type, "Discussion")

    # Icône selon le type
    type_icons = {
        "RIGHTS": "🔐",
        "ACTION": "📋",
        "QUESTION": "❓",
        "DIRECT_MESSAGE": "💬"
    }
    type_icon = type_icons.get(conversation_type, "💬")

    # Contexte additionnel (campagne/entité)
    context_html = ""
    if campaign_name or entity_name:
        context_items = []
        if campaign_name:
            context_items.append(f"<strong>Campagne :</strong> {campaign_name}")
        if entity_name:
            context_items.append(f"<strong>Entité :</strong> {entity_name}")
        context_html = f"""
            <div style="background: rgba(59, 130, 246, 0.05);
                        border: 1px solid rgba(59, 130, 246, 0.2);
                        padding: 12px 16px;
                        margin: 16px 0;
                        border-radius: 6px;">
                <div style="font-size: 13px; color: #93c5fd; line-height: 1.6;">
                    {'<br>'.join(context_items)}
                </div>
            </div>
        """

    # Logo HTML (base64 ou SVG fallback)
    logo_html = f'<img src="{LOGO_DATA_URI}" alt="CYBERGARD AI Logo" style="width: 100%; height: 100%; object-fit: contain;" />' if LOGO_DATA_URI else '''
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            <path d="M9 12l2 2 4-4"></path>
        </svg>
    '''

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nouveau message - {conversation_title}</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <!-- Logo CYBERGARD AI -->
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                {logo_html}
            </div>

            <!-- Titre marque -->
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <div style="display: inline-block; padding: 8px 16px; background: rgba(220, 38, 38, 0.2); border-radius: 20px; margin-bottom: 12px;">
                <span style="font-size: 14px; color: #fca5a5;">{type_icon} {type_label}</span>
            </div>
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Nouveau message
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                {conversation_title}
            </p>
        </div>

        <!-- Contenu -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{recipient_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                <strong style="color: #ffffff;">{sender_name}</strong> vous a envoyé un nouveau message dans la discussion "<strong style="color: #ffffff;">{conversation_title}</strong>".
            </p>

            {context_html}

            <!-- Aperçu du message -->
            <div style="background: #374151;
                        border-left: 4px solid #dc2626;
                        padding: 20px;
                        margin: 24px 0;
                        border-radius: 0 8px 8px 0;">
                <p style="margin: 0 0 8px 0; font-size: 12px; font-weight: 600; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.5px;">
                    Aperçu du message
                </p>
                <p style="margin: 0; font-size: 15px; color: #e5e7eb; line-height: 1.6; font-style: italic;">
                    "{message_preview}"
                </p>
            </div>

            <!-- Bouton CTA -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{conversation_url}"
                   style="display: inline-block;
                          padding: 14px 32px;
                          background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 15px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);">
                    💬 Voir la conversation
                </a>
            </div>

            <!-- Info box -->
            <div style="background: #374151;
                        border: 1px solid #4b5563;
                        border-radius: 6px;
                        padding: 20px;
                        margin: 32px 0;">
                <p style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #ffffff;">
                    💡 Bon à savoir
                </p>
                <div style="font-size: 14px; color: #d1d5db; line-height: 1.8;">
                    <div style="margin-bottom: 8px;">
                        📝 <strong style="color: #ffffff;">Répondre</strong> : Vous pouvez répondre directement depuis la plateforme.
                    </div>
                    <div style="margin-bottom: 8px;">
                        🔔 <strong style="color: #ffffff;">Notifications</strong> : Vous recevrez un email à chaque nouveau message.
                    </div>
                    <div>
                        📁 <strong style="color: #ffffff;">Pièces jointes</strong> : Les documents sont accessibles depuis la conversation.
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
                    {conversation_url}
                </code>
            </div>
        </div>

        <!-- Footer -->
        <div style="background: #1a202c;
                    padding: 24px 30px;
                    text-align: center;
                    border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 12px 0; color: #d1d5db; font-size: 14px; font-weight: 500;">
                Cordialement,
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


def get_discussion_new_message_email_text(
    recipient_name: str,
    sender_name: str,
    conversation_title: str,
    conversation_type: str,
    message_preview: str,
    conversation_url: str,
    campaign_name: str = None,
    entity_name: str = None,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """
    Version texte de l'email de notification d'un nouveau message.

    Args:
        recipient_name: Nom du destinataire
        sender_name: Nom de l'expéditeur du message
        conversation_title: Titre de la conversation
        conversation_type: Type de conversation
        message_preview: Aperçu du message
        conversation_url: URL pour accéder à la conversation
        campaign_name: Nom de la campagne (optionnel)
        entity_name: Nom de l'entité (optionnel)
        organization_name: Nom de l'organisation

    Returns:
        str: Texte formaté pour l'email
    """
    # Mapping des types
    type_labels = {
        "RIGHTS": "Demande de droits",
        "ACTION": "Discussion sur une action",
        "QUESTION": "Discussion sur une question",
        "DIRECT_MESSAGE": "Message direct"
    }
    type_label = type_labels.get(conversation_type, "Discussion")

    # Contexte
    context_text = ""
    if campaign_name:
        context_text += f"\nCampagne : {campaign_name}"
    if entity_name:
        context_text += f"\nEntité : {entity_name}"

    return f"""CYBERGARD AI - Nouveau message

Bonjour {recipient_name},

{sender_name} vous a envoyé un nouveau message dans la discussion "{conversation_title}".

Type : {type_label}
{context_text}

APERÇU DU MESSAGE :
"{message_preview}"

VOIR LA CONVERSATION :
{conversation_url}

BON À SAVOIR :
• Vous pouvez répondre directement depuis la plateforme.
• Vous recevrez un email à chaque nouveau message.
• Les documents sont accessibles depuis la conversation.

Cordialement,
L'équipe {organization_name}
Plateforme de gestion des audits et plans d'action"""


def get_discussion_mention_email_subject(
    sender_name: str,
    conversation_title: str
) -> str:
    """
    Génère le sujet de l'email pour une mention dans une discussion.

    Args:
        sender_name: Nom de la personne qui a mentionné
        conversation_title: Titre de la conversation

    Returns:
        str: Sujet de l'email
    """
    return f"{sender_name} vous a mentionné - {conversation_title}"


def get_discussion_mention_email_html(
    recipient_name: str,
    sender_name: str,
    conversation_title: str,
    conversation_type: str,
    message_content: str,
    conversation_url: str,
    campaign_name: str = None,
    entity_name: str = None,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """
    Template HTML pour l'email de notification d'une mention dans une discussion.

    Args:
        recipient_name: Nom du destinataire mentionné
        sender_name: Nom de la personne qui a mentionné
        conversation_title: Titre de la conversation
        conversation_type: Type de conversation
        message_content: Contenu du message avec la mention
        conversation_url: URL pour accéder à la conversation
        campaign_name: Nom de la campagne (optionnel)
        entity_name: Nom de l'entité (optionnel)
        organization_name: Nom de l'organisation

    Returns:
        str: HTML formaté pour l'email
    """
    # Mapping des types
    type_labels = {
        "RIGHTS": "Demande de droits",
        "ACTION": "Discussion sur une action",
        "QUESTION": "Discussion sur une question",
        "DIRECT_MESSAGE": "Message direct"
    }
    type_label = type_labels.get(conversation_type, "Discussion")

    # Contexte additionnel
    context_html = ""
    if campaign_name or entity_name:
        context_items = []
        if campaign_name:
            context_items.append(f"<strong>Campagne :</strong> {campaign_name}")
        if entity_name:
            context_items.append(f"<strong>Entité :</strong> {entity_name}")
        context_html = f"""
            <div style="background: rgba(59, 130, 246, 0.05);
                        border: 1px solid rgba(59, 130, 246, 0.2);
                        padding: 12px 16px;
                        margin: 16px 0;
                        border-radius: 6px;">
                <div style="font-size: 13px; color: #93c5fd; line-height: 1.6;">
                    {'<br>'.join(context_items)}
                </div>
            </div>
        """

    # Logo HTML
    logo_html = f'<img src="{LOGO_DATA_URI}" alt="CYBERGARD AI Logo" style="width: 100%; height: 100%; object-fit: contain;" />' if LOGO_DATA_URI else '''
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            <path d="M9 12l2 2 4-4"></path>
        </svg>
    '''

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vous avez été mentionné - {conversation_title}</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 50%, #7f1d1d 100%); min-height: 100vh; padding: 40px 20px;">

    <div style="max-width: 600px; margin: 0 auto; background: #2d3748; border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);">

        <!-- Header avec logo -->
        <div style="text-align: center; padding: 32px 30px; background: #1a202c; border-bottom: 1px solid #4a5568;">
            <div style="width: 100px; height: 100px; margin: 0 auto 16px; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 10px; box-shadow: 0 8px 24px rgba(220, 38, 38, 0.4);">
                {logo_html}
            </div>
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: white; letter-spacing: 0.05em;">
                CYBERGARD AI
            </h1>
        </div>

        <!-- Section titre -->
        <div style="text-align: center; padding: 32px 30px 24px;">
            <div style="display: inline-block; padding: 8px 16px; background: rgba(251, 191, 36, 0.2); border-radius: 20px; margin-bottom: 12px;">
                <span style="font-size: 14px; color: #fbbf24;">@ Mention</span>
            </div>
            <h2 style="margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: white;">
                Vous avez été mentionné
            </h2>
            <p style="margin: 0; font-size: 14px; color: #9ca3af;">
                {type_label} - {conversation_title}
            </p>
        </div>

        <!-- Contenu -->
        <div style="padding: 0 30px 40px;">
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                Bonjour <strong style="color: #ffffff;">{recipient_name}</strong>,
            </p>

            <p style="margin: 0 0 20px 0; font-size: 16px; color: #d1d5db; line-height: 1.6;">
                <strong style="color: #ffffff;">{sender_name}</strong> vous a mentionné dans un message de la discussion "<strong style="color: #ffffff;">{conversation_title}</strong>".
            </p>

            {context_html}

            <!-- Message avec mention -->
            <div style="background: #374151;
                        border-left: 4px solid #fbbf24;
                        padding: 20px;
                        margin: 24px 0;
                        border-radius: 0 8px 8px 0;">
                <p style="margin: 0 0 8px 0; font-size: 12px; font-weight: 600; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.5px;">
                    Message de {sender_name}
                </p>
                <p style="margin: 0; font-size: 15px; color: #e5e7eb; line-height: 1.6;">
                    {message_content}
                </p>
            </div>

            <!-- Bouton CTA -->
            <div style="text-align: center; margin: 32px 0;">
                <a href="{conversation_url}"
                   style="display: inline-block;
                          padding: 14px 32px;
                          background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 6px;
                          font-weight: 600;
                          font-size: 15px;
                          box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);">
                    💬 Répondre au message
                </a>
            </div>

            <!-- Lien de secours -->
            <div style="margin: 24px 0 0 0; padding: 16px; background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 6px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: #fbbf24;">
                    💡 Le bouton ne fonctionne pas ?
                </p>
                <code style="background: #374151;
                             padding: 12px;
                             display: block;
                             word-break: break-all;
                             border-radius: 6px;
                             font-size: 12px;
                             color: #93c5fd;
                             border: 1px solid #4b5563;">
                    {conversation_url}
                </code>
            </div>
        </div>

        <!-- Footer -->
        <div style="background: #1a202c;
                    padding: 24px 30px;
                    text-align: center;
                    border-top: 1px solid #4a5568;">
            <p style="margin: 0 0 12px 0; color: #d1d5db; font-size: 14px; font-weight: 500;">
                Cordialement,
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


def get_discussion_mention_email_text(
    recipient_name: str,
    sender_name: str,
    conversation_title: str,
    conversation_type: str,
    message_content: str,
    conversation_url: str,
    campaign_name: str = None,
    entity_name: str = None,
    organization_name: str = "CYBERGARD AI"
) -> str:
    """
    Version texte de l'email de mention.

    Args:
        recipient_name: Nom du destinataire
        sender_name: Nom de la personne qui a mentionné
        conversation_title: Titre de la conversation
        conversation_type: Type de conversation
        message_content: Contenu du message
        conversation_url: URL pour accéder à la conversation
        campaign_name: Nom de la campagne (optionnel)
        entity_name: Nom de l'entité (optionnel)
        organization_name: Nom de l'organisation

    Returns:
        str: Texte formaté pour l'email
    """
    type_labels = {
        "RIGHTS": "Demande de droits",
        "ACTION": "Discussion sur une action",
        "QUESTION": "Discussion sur une question",
        "DIRECT_MESSAGE": "Message direct"
    }
    type_label = type_labels.get(conversation_type, "Discussion")

    context_text = ""
    if campaign_name:
        context_text += f"\nCampagne : {campaign_name}"
    if entity_name:
        context_text += f"\nEntité : {entity_name}"

    return f"""CYBERGARD AI - Vous avez été mentionné

Bonjour {recipient_name},

{sender_name} vous a mentionné dans un message de la discussion "{conversation_title}".

Type : {type_label}
{context_text}

MESSAGE :
{message_content}

RÉPONDRE AU MESSAGE :
{conversation_url}

Cordialement,
L'équipe {organization_name}
Plateforme de gestion des audits et plans d'action"""
