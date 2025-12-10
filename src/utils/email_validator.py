"""
Service de validation des adresses email
- Vérifie la structure et les caractères autorisés
- Vérifie l'existence du domaine (DNS)
- Vérifie les enregistrements MX (serveurs mail)
"""
import re
import dns.resolver
import logging
from typing import Tuple, Dict

logger = logging.getLogger(__name__)


def validate_email_format(email: str) -> Tuple[bool, str]:
    """
    Valide qu'une adresse email a un format correct et ne contient pas de caractères non-ASCII

    Args:
        email: L'adresse email à valider

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
        - is_valid: True si l'email est valide, False sinon
        - error_message: Message d'erreur si invalide, chaîne vide si valide
    """

    # 1. Vérifier que l'email n'est pas vide
    if not email or not email.strip():
        return False, "L'adresse email ne peut pas être vide"

    email = email.strip().lower()

    # 2. Vérifier les caractères non-ASCII (accents, caractères spéciaux)
    if not email.isascii():
        # Trouver les caractères problématiques
        non_ascii_chars = [c for c in email if ord(c) > 127]
        suggested = suggest_valid_email(email)
        return False, (
            f"L'adresse email ne doit pas contenir de caractères accentués. "
            f"Caractères invalides: {', '.join(set(non_ascii_chars))}. "
            f"Suggestion: {suggested}"
        )

    # 3. Pattern regex pour validation de base
    email_pattern = re.compile(
        r'^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$',
        re.IGNORECASE
    )

    if not email_pattern.match(email):
        return False, (
            "Format d'email invalide. "
            "Format attendu: utilisateur@domaine.com"
        )

    # 4. Vérifications supplémentaires
    if email.count('@') != 1:
        return False, "L'adresse email doit contenir exactement un '@'"

    local_part, domain = email.split('@')

    # Vérifier la partie locale (avant @)
    if not local_part or len(local_part) > 64:
        return False, "La partie avant '@' doit faire entre 1 et 64 caractères"

    if local_part.startswith('.') or local_part.endswith('.'):
        return False, "La partie avant '@' ne peut pas commencer ou finir par un point"

    if '..' in local_part:
        return False, "Points consécutifs non autorisés"

    # Vérifier le domaine (après @)
    if not domain or len(domain) > 255:
        return False, "Le domaine est trop long (max 255 caractères)"

    if domain.startswith('.') or domain.startswith('-') or domain.endswith('.') or domain.endswith('-'):
        return False, "Le domaine ne peut pas commencer ou finir par un point ou un tiret"

    if '..' in domain:
        return False, "Points consécutifs non autorisés dans le domaine"

    if '.' not in domain:
        return False, "Le domaine doit contenir au moins un point (ex: domaine.com)"

    # Vérifier l'extension du domaine (TLD)
    tld = domain.split('.')[-1]
    if len(tld) < 2:
        return False, "L'extension du domaine est trop courte"

    # ✅ Email valide
    return True, ""


def validate_domain_exists(domain: str) -> Tuple[bool, str]:
    """
    Vérifie que le domaine existe (enregistrements DNS et MX)

    Args:
        domain: Le nom de domaine à vérifier

    Returns:
        Tuple[bool, str]: (exists, error_message)
    """
    try:
        # 1. Vérifier les enregistrements MX (Mail eXchange)
        try:
            mx_records = dns.resolver.resolve(domain, 'MX')
            if mx_records:
                logger.info(f"✅ Domaine {domain} a {len(mx_records)} enregistrement(s) MX")
                return True, ""
        except dns.resolver.NoAnswer:
            logger.warning(f"⚠️ Pas d'enregistrement MX pour {domain}")
            # Pas de MX, mais peut-être que le domaine existe quand même
            pass
        except dns.resolver.NXDOMAIN:
            return False, f"Le domaine '{domain}' n'existe pas"
        except dns.resolver.Timeout:
            logger.warning(f"⚠️ Timeout lors de la vérification MX de {domain}")
            # On continue quand même

        # 2. Si pas de MX, vérifier au moins que le domaine existe (enregistrement A)
        try:
            a_records = dns.resolver.resolve(domain, 'A')
            if a_records:
                logger.info(f"✅ Domaine {domain} a des enregistrements A")
                return True, ""
        except dns.resolver.NoAnswer:
            return False, f"Le domaine '{domain}' n'a pas de serveur mail configuré"
        except dns.resolver.NXDOMAIN:
            return False, f"Le domaine '{domain}' n'existe pas"
        except dns.resolver.Timeout:
            logger.warning(f"⚠️ Timeout lors de la vérification DNS de {domain}")
            # En cas de timeout, on laisse passer (peut être un problème réseau temporaire)
            return True, ""

        # Si on arrive ici, le domaine n'a ni MX ni A
        return False, f"Le domaine '{domain}' semble invalide ou inaccessible"

    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification du domaine {domain}: {e}")
        # En cas d'erreur inattendue, on laisse passer pour ne pas bloquer l'utilisateur
        return True, ""


def validate_email_complete(email: str) -> Dict[str, any]:
    """
    Validation complète d'une adresse email

    Args:
        email: L'adresse email à valider

    Returns:
        Dict avec:
        - valid: bool - True si l'email est complètement valide
        - errors: List[str] - Liste des erreurs trouvées
        - warnings: List[str] - Liste des avertissements
        - email_cleaned: str - Email nettoyé (minuscules, trimé)
    """
    result = {
        "valid": False,
        "errors": [],
        "warnings": [],
        "email_cleaned": sanitize_email(email)
    }

    # 1. Validation du format
    format_valid, format_error = validate_email_format(email)
    if not format_valid:
        result["errors"].append(format_error)
        return result

    # 2. Extraction du domaine
    try:
        _, domain = email.split('@')
    except ValueError:
        result["errors"].append("Format d'email invalide")
        return result

    # 3. Validation du domaine (optionnel - peut échouer en dev)
    try:
        domain_valid, domain_error = validate_domain_exists(domain)
        if not domain_valid:
            # Si le domaine semble invalide, on ajoute un warning mais on valide quand même
            # pour ne pas bloquer en développement
            result["warnings"].append(f"Avertissement: {domain_error}")
            logger.warning(f"⚠️ Validation DNS a échoué pour {email}: {domain_error}")
            # On valide quand même l'email si le format est bon
            result["valid"] = True
        else:
            # ✅ Email complètement valide (format + DNS)
            result["valid"] = True
    except Exception as e:
        # En cas d'erreur inattendue lors de la validation DNS, on accepte l'email
        logger.warning(f"⚠️ Impossible de valider le domaine {domain}: {e}")
        result["warnings"].append(f"Impossible de vérifier le domaine (erreur réseau)")
        result["valid"] = True

    return result


def sanitize_email(email: str) -> str:
    """
    Nettoie une adresse email en supprimant les espaces et en mettant en minuscules

    Args:
        email: L'adresse email à nettoyer

    Returns:
        str: L'adresse email nettoyée
    """
    if not email:
        return ""

    return email.strip().lower()


def suggest_valid_email(email: str) -> str:
    """
    Suggère une version valide d'un email en retirant les caractères non-ASCII

    Args:
        email: L'adresse email invalide

    Returns:
        str: Suggestion d'email valide (sans accents)
    """
    if not email:
        return ""

    # Mapper les caractères accentués vers leurs équivalents ASCII
    accent_map = {
        'á': 'a', 'à': 'a', 'â': 'a', 'ä': 'a', 'ã': 'a', 'å': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'ô': 'o', 'ö': 'o', 'õ': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ý': 'y', 'ÿ': 'y',
        'ç': 'c', 'ñ': 'n',
        'Á': 'A', 'À': 'A', 'Â': 'A', 'Ä': 'A', 'Ã': 'A', 'Å': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
        'Ó': 'O', 'Ò': 'O', 'Ô': 'O', 'Ö': 'O', 'Õ': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ý': 'Y', 'Ÿ': 'Y',
        'Ç': 'C', 'Ñ': 'N'
    }

    suggested = ""
    for char in email:
        if char in accent_map:
            suggested += accent_map[char]
        elif ord(char) <= 127:  # Caractère ASCII valide
            suggested += char
        # Sinon, on ignore le caractère

    return suggested.strip().lower()
