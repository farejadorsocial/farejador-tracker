"""Consulta ao IPinfo — chamada SOMENTE pelo painel administrativo."""
import ipaddress
import json
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from .config import IPINFO_TOKEN
from .db import agora_iso

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 3600


def ip_publico(ip: Optional[str]) -> bool:
    try:
        e = ipaddress.ip_address(ip or "")
        return not (e.is_private or e.is_loopback or e.is_reserved or e.is_unspecified or e.is_link_local or e.is_multicast)
    except ValueError:
        return False


def consultar(ip: Optional[str]) -> Dict[str, Any]:
    vazio: Dict[str, Any] = {
        "consultado": False, "ip": ip, "provedor": None, "organizacao": None, "asn": None,
        "pais": None, "codigo_pais": None, "regiao": None, "cidade": None, "codigo_postal": None,
        "timezone": None, "localizacao_aproximada": None, "latitude": None, "longitude": None,
        "hostname": None, "anycast": None, "bruto": None, "consultado_em": None, "erro": None,
    }
    if not ip:
        vazio["erro"] = "IP não identificado"
        return vazio
    try:
        ip = str(ipaddress.ip_address(ip))
    except ValueError:
        vazio["erro"] = "Formato de IP inválido"
        return vazio
    vazio["ip"] = ip
    if not ip_publico(ip):
        vazio["erro"] = "IP privado, local ou reservado; consulta pública não aplicável"
        return vazio

    agora = time.time()
    cache = _CACHE.get(ip)
    if cache and agora - cache["hora"] < _CACHE_TTL:
        return dict(cache["dados"])

    resultado = dict(vazio)
    url = "https://ipinfo.io/{}/json".format(ip) + ("?token=" + IPINFO_TOKEN if IPINFO_TOKEN else "")
    try:
        req = UrlRequest(url, headers={"User-Agent": "Farejador/4.0", "Accept": "application/json"})
        with urlopen(req, timeout=8) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
        org = str(dados.get("org") or "").strip()
        asn = org.split(" ", 1)[0] if org.upper().startswith("AS") else None
        lat = lon = None
        loc = dados.get("loc")
        if loc and "," in loc:
            try:
                lat, lon = [float(x) for x in loc.split(",", 1)]
            except ValueError:
                pass
        dados.pop("readme", None)
        resultado.update({
            "consultado": True,
            "provedor": (org.split(" ", 1)[1] if asn and " " in org else org) or None,
            "organizacao": org or None, "asn": asn,
            "pais": dados.get("country"), "codigo_pais": dados.get("country"),
            "regiao": dados.get("region"), "cidade": dados.get("city"), "codigo_postal": dados.get("postal"),
            "timezone": dados.get("timezone"), "localizacao_aproximada": loc, "latitude": lat, "longitude": lon,
            "hostname": dados.get("hostname"), "anycast": dados.get("anycast"), "bruto": dados,
            "consultado_em": agora_iso(),
        })
        _CACHE[ip] = {"hora": agora, "dados": dict(resultado)}
    except HTTPError as erro:
        resultado["erro"] = "IPinfo HTTP {}".format(erro.code)
    except (URLError, TimeoutError, ValueError, OSError) as erro:
        resultado["erro"] = str(erro)[:250]
    return resultado
