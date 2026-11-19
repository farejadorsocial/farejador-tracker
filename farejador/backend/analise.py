"""Leitura do User-Agent, detecção de robôs/prévias e classificação da origem da visita."""
import re
from typing import Dict, Optional
from urllib.parse import urlparse

# Robôs que abrem o link para montar a prévia (WhatsApp, Facebook, X…) ou indexar.
_ROBOS = [
    (r"WhatsApp", "WhatsApp (prévia)"),
    (r"facebookexternalhit|facebookcatalog|meta-externalagent", "Facebook/Instagram (prévia)"),
    (r"Twitterbot", "X/Twitter (prévia)"),
    (r"TelegramBot", "Telegram (prévia)"),
    (r"Discordbot", "Discord (prévia)"),
    (r"Slackbot|Slack-ImgProxy", "Slack (prévia)"),
    (r"LinkedInBot", "LinkedIn (prévia)"),
    (r"SkypeUriPreview|Teams", "Microsoft (prévia)"),
    (r"Pinterestbot|Pinterest/", "Pinterest (prévia)"),
    (r"redditbot", "Reddit (prévia)"),
    (r"Googlebot|AdsBot-Google|Google-InspectionTool|GoogleOther", "Google (robô)"),
    (r"bingbot|BingPreview", "Bing (robô)"),
    (r"YandexBot|Baiduspider|DuckDuckBot|Applebot|PetalBot|SemrushBot|AhrefsBot|MJ12bot|DotBot|GPTBot|ClaudeBot|CCBot|Bytespider", "Rastreador"),
    (r"HeadlessChrome|PhantomJS|Puppeteer|Playwright|Selenium", "Navegador automatizado"),
    (r"curl/|Wget/|python-requests|python-urllib|httpx|aiohttp|Go-http-client|okhttp|Java/|libwww|axios/|node-fetch|PostmanRuntime|insomnia", "Script / ferramenta"),
    (r"bot\b|crawler|spider|preview|scanner|monitor|uptime", "Robô genérico"),
]


def detectar_robo(ua: Optional[str]) -> Optional[str]:
    """Retorna o nome do robô se o User-Agent for de robô/prévia; senão None."""
    if not ua:
        return "Sem User-Agent"
    # O app do WhatsApp/Instagram abre links num navegador real (Mobile Safari/Chrome);
    # só é robô se não houver um motor de navegador completo.
    navegador_real = re.search(r"Mozilla/5\.0 \((Linux; Android|iPhone|iPad|Windows NT|Macintosh|X11)", ua)
    for padrao, nome in _ROBOS:
        if re.search(padrao, ua, re.I):
            if nome == "WhatsApp (prévia)" and navegador_real and "Mobile" in ua:
                return None
            return nome
    return None


def analisar_ua(ua: Optional[str]) -> Dict[str, str]:
    ua = ua or ""
    robo = detectar_robo(ua)
    if robo:
        nav = robo
    elif "Instagram" in ua:
        nav = "Instagram (app)"
    elif re.search(r"musical_ly|BytedanceWebview|TikTok", ua, re.I):
        nav = "TikTok (app)"
    elif re.search(r"FBAN|FBAV|FB_IAB", ua):
        nav = "Facebook (app)"
    elif re.search(r"Kwai", ua, re.I):
        nav = "Kwai (app)"
    elif re.search(r"Edg/|Edge/", ua):
        nav = "Edge"
    elif re.search(r"OPR/|Opera", ua):
        nav = "Opera"
    elif "SamsungBrowser" in ua:
        nav = "Samsung Internet"
    elif re.search(r"Firefox/|FxiOS", ua):
        nav = "Firefox"
    elif re.search(r"Chrome/|CriOS", ua):
        nav = "Chrome"
    elif "Safari/" in ua:
        nav = "Safari"
    else:
        nav = "Outro"

    if re.search(r"iPhone|iPad|iPod", ua):
        so = "iOS"
    elif "Android" in ua:
        so = "Android"
    elif "Windows" in ua:
        so = "Windows"
    elif re.search(r"Mac OS X|Macintosh", ua):
        so = "macOS"
    elif "CrOS" in ua:
        so = "ChromeOS"
    elif "Linux" in ua:
        so = "Linux"
    else:
        so = "Outro"

    if robo:
        disp = "Robô"
    elif re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua):
        disp = "Tablet"
    elif re.search(r"Mobile|iPhone|iPod|Android", ua):
        disp = "Celular"
    else:
        disp = "Computador"
    return {"navegador": nav, "sistema": so, "dispositivo": disp}


ORIGENS_CONHECIDAS = [
    (r"instagram", "Instagram"),
    (r"tiktok", "TikTok"),
    (r"youtube|youtu\.be", "YouTube"),
    (r"facebook|fb\.com|fb\.me", "Facebook"),
    (r"whatsapp|wa\.me", "WhatsApp"),
    (r"t\.me|telegram", "Telegram"),
    (r"twitter|t\.co$|^x\.com|\.x\.com|^x$", "X / Twitter"),
    (r"threads", "Threads"),
    (r"kwai", "Kwai"),
    (r"linkedin|lnkd\.in", "LinkedIn"),
    (r"google", "Google"),
    (r"bing", "Bing"),
    (r"pinterest", "Pinterest"),
    (r"reddit", "Reddit"),
    (r"discord", "Discord"),
    (r"^qr|qrcode", "QR Code"),
    (r"email|e-mail|newsletter|gmail|outlook", "E-mail"),
]


def _rotulo(texto: str) -> Optional[str]:
    for padrao, rotulo in ORIGENS_CONHECIDAS:
        if re.search(padrao, texto, re.I):
            return rotulo
    return None


def classificar_origem(referer: Optional[str], utm_source: Optional[str], host_proprio: Optional[str], ua: Optional[str] = None) -> Dict[str, Optional[str]]:
    dominio = None
    if referer:
        try:
            dominio = (urlparse(referer).hostname or "").lower() or None
        except ValueError:
            dominio = None
    if dominio and host_proprio and dominio == host_proprio.split(":")[0].lower():
        dominio = None  # navegação interna
    if utm_source:
        nome = utm_source.strip()[:60]
        return {"canal": _rotulo(nome) or nome, "dominio": dominio, "via": "utm"}
    if dominio:
        return {"canal": _rotulo(dominio) or dominio.replace("www.", ""), "dominio": dominio, "via": "referer"}
    # Apps abrem links sem Referer: o navegador embutido denuncia a origem.
    nav = analisar_ua(ua)["navegador"]
    if nav.endswith("(app)"):
        return {"canal": nav.replace(" (app)", ""), "dominio": None, "via": "app"}
    return {"canal": "Direto", "dominio": None, "via": "direto"}
