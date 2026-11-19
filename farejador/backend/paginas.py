"""Páginas públicas: configuração padrão, validação e acesso no banco."""
import copy
import re
import secrets
from typing import Any, Dict, List, Optional

from .config import SLUGS_RESERVADOS
from .db import agora_iso, conexao, json_carregar, json_texto, transacao

FONTES = ["Plus Jakarta Sans", "Inter", "Poppins", "Montserrat", "Nunito", "Space Grotesk", "Outfit",
          "DM Sans", "Sora", "Playfair Display", "Lora", "Bebas Neue", "Righteous", "Pacifico", "Press Start 2P"]
PRESETS = ["aurora", "claro", "neon", "por-do-sol", "oceano", "floresta", "grafite", "personalizado"]

CONFIG_PADRAO: Dict[str, Any] = {
    "perfil": {
        "nome": "Minha página",
        "usuario": "@usuario",
        "bio": "Todas as minhas redes em um só lugar. Escolha onde quer me acompanhar 👇",
        "avatar": "",
        "verificado": False,
    },
    "textos": {
        "titulo_pagina": "Minhas redes",
        "descricao_pagina": "Guia com todas as redes sociais e links oficiais.",
        "secao_redes": "Redes sociais",
        "secao_links": "Links em destaque",
        "aviso_titulo": "Sua privacidade",
        "aviso_texto": "Usamos dados técnicos do seu navegador (dispositivo, tela, idioma, origem da visita e IP) para estudar o desempenho desta página. Nada de câmera, microfone ou senhas.",
        "botao_aceitar": "Aceitar",
        "botao_recusar": "Só o essencial",
        "botao_localizacao": "Compartilhar localização (opcional)",
        "botao_compartilhar": "Compartilhar",
        "rodape": "Feito com Farejador",
    },
    "tema": {
        "preset": "aurora",
        "cor_destaque": "#7c5cff",
        "fonte": "Plus Jakarta Sans",
        "fonte_titulo": "",
        "fundo_tipo": "preset",          # preset | cor | gradiente | imagem
        "fundo_cor1": "#0b0a1a",
        "fundo_cor2": "#3b1f7a",
        "fundo_angulo": 160,
        "fundo_imagem": "",
        "fundo_escurecer": 40,           # 0–85 (%), só para imagem
        "fundo_animado": True,
        "texto": "claro",                # claro | escuro (cor das letras em fundo personalizado)
        "formato_botao": "arredondado",  # arredondado | pilula | quadrado
        "estilo_botao": "vidro",         # vidro | solido | contorno | sombra
        "cor_botao": "#ffffff",
        "cor_texto_botao": "#111111",
        "animacao_botao": "subir",       # nenhuma | subir | brilho | pulsar | balancar
        "forma_avatar": "circulo",       # circulo | arredondado | quadrado
        "anel_avatar": True,
        "icones_coloridos": True,
        "mostrar_compartilhar": True,
    },
    "coleta": {"mostrar_aviso": True, "pedir_localizacao": False},
    "links": [],
}

_OPCOES = {
    "fundo_tipo": ("preset", "cor", "gradiente", "imagem"),
    "texto": ("claro", "escuro"),
    "formato_botao": ("arredondado", "pilula", "quadrado"),
    "estilo_botao": ("vidro", "solido", "contorno", "sombra"),
    "animacao_botao": ("nenhuma", "subir", "brilho", "pulsar", "balancar"),
    "forma_avatar": ("circulo", "arredondado", "quadrado"),
}
_RE_COR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _mesclar(padrao: Dict[str, Any], atual: Dict[str, Any]) -> Dict[str, Any]:
    saida = copy.deepcopy(padrao)
    for chave, valor in (atual or {}).items():
        if isinstance(valor, dict) and isinstance(padrao.get(chave), dict):
            saida[chave] = _mesclar(padrao[chave], valor)
        elif chave in padrao or not isinstance(padrao, dict):
            saida[chave] = valor
    return saida


def _texto(v: Any, limite: int = 600) -> str:
    return str(v if v is not None else "")[:limite]


def migrar_tema_antigo(tema: Dict[str, Any]) -> Dict[str, Any]:
    """Converte o tema da versão 3 (estilo_botao = arredondado/pilula/...) para os campos novos."""
    tema = dict(tema or {})
    antigo = tema.get("estilo_botao")
    if antigo in ("arredondado", "pilula", "quadrado"):
        tema["formato_botao"] = antigo
        tema["estilo_botao"] = "vidro"
    elif antigo == "contorno":
        tema["estilo_botao"] = "contorno"
    return tema


def normalizar_config(bruto: Dict[str, Any]) -> Dict[str, Any]:
    """Valida tudo que vem do painel antes de salvar."""
    bruto = bruto if isinstance(bruto, dict) else {}
    if "tema" in bruto:
        bruto = dict(bruto, tema=migrar_tema_antigo(bruto.get("tema")))
    cfg = _mesclar(CONFIG_PADRAO, {k: v for k, v in bruto.items() if k in CONFIG_PADRAO and k != "links"})
    for sec in ("perfil", "textos"):
        for k, v in list(cfg[sec].items()):
            cfg[sec][k] = bool(v) if isinstance(CONFIG_PADRAO[sec][k], bool) else _texto(v)
    t = cfg["tema"]
    for k, v in list(t.items()):
        p = CONFIG_PADRAO["tema"][k]
        if isinstance(p, bool):
            t[k] = bool(v)
        elif isinstance(p, int):
            try:
                t[k] = int(v)
            except (TypeError, ValueError):
                t[k] = p
        else:
            t[k] = _texto(v, 400)
    for k, ops in _OPCOES.items():
        if t[k] not in ops:
            t[k] = CONFIG_PADRAO["tema"][k]
    if t["preset"] not in PRESETS:
        t["preset"] = "aurora"
    if t["fonte"] not in FONTES:
        t["fonte"] = "Plus Jakarta Sans"
    if t["fonte_titulo"] and t["fonte_titulo"] not in FONTES:
        t["fonte_titulo"] = ""
    for k in ("cor_destaque", "fundo_cor1", "fundo_cor2", "cor_botao", "cor_texto_botao"):
        if not _RE_COR.match(t[k]):
            t[k] = CONFIG_PADRAO["tema"][k]
    t["fundo_angulo"] = max(0, min(360, t["fundo_angulo"]))
    t["fundo_escurecer"] = max(0, min(85, t["fundo_escurecer"]))
    cfg["coleta"] = {k: bool(cfg["coleta"].get(k)) for k in CONFIG_PADRAO["coleta"]}

    links: List[Dict[str, Any]] = []
    ids = set()
    for item in (bruto.get("links") or [])[:150]:
        if not isinstance(item, dict):
            continue
        url = _texto(item.get("url"), 1000).strip()
        if url and not re.match(r"^(https?://|mailto:|tel:|sms:)", url, re.I):
            url = "https://" + url
        lid = re.sub(r"[^a-z0-9_-]", "", _texto(item.get("id"), 40).lower()) or secrets.token_hex(3)
        while lid in ids:
            lid = lid + "-" + secrets.token_hex(2)
        ids.add(lid)
        cor = _texto(item.get("cor"), 20)
        links.append({
            "id": lid,
            "tipo": _texto(item.get("tipo") or "link", 30),
            "titulo": _texto(item.get("titulo"), 80),
            "subtitulo": _texto(item.get("subtitulo"), 120),
            "url": url,
            "ativo": bool(item.get("ativo", True)),
            "exibicao": "icone" if item.get("exibicao") == "icone" else "botao",
            "destaque": bool(item.get("destaque")),
            "icone_custom": _texto(item.get("icone_custom"), 300),
            "cor": cor if _RE_COR.match(cor) else "",
        })
    cfg["links"] = links
    return cfg


def validar_slug(slug: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "-", (slug or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:40]
    if not slug or slug in SLUGS_RESERVADOS:
        raise ValueError("Endereço inválido ou reservado. Use letras, números e hífen.")
    return slug


def _linha(linha) -> Dict[str, Any]:
    return {
        "id": linha["id"], "slug": linha["slug"], "nome": linha["nome"], "principal": bool(linha["principal"]),
        "config": normalizar_config(json_carregar(linha["config"])),
        "criado_em": linha["criado_em"], "atualizado_em": linha["atualizado_em"],
    }


def listar() -> List[Dict[str, Any]]:
    with conexao() as con:
        return [_linha(l) for l in con.execute("SELECT * FROM paginas ORDER BY principal DESC, nome")]


def obter(pagina_id: Optional[int] = None, slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with conexao() as con:
        if pagina_id is not None:
            l = con.execute("SELECT * FROM paginas WHERE id = ?", (pagina_id,)).fetchone()
        elif slug:
            l = con.execute("SELECT * FROM paginas WHERE slug = ?", (slug.lower(),)).fetchone()
        else:
            l = con.execute("SELECT * FROM paginas ORDER BY principal DESC, id LIMIT 1").fetchone()
    return _linha(l) if l else None


def criar(nome: str, slug: str, config: Optional[Dict[str, Any]] = None, principal: bool = False) -> Dict[str, Any]:
    slug = validar_slug(slug)
    cfg = normalizar_config(config or {"perfil": {"nome": nome}, "textos": {"titulo_pagina": nome}})
    agora = agora_iso()
    with transacao() as con:
        if con.execute("SELECT 1 FROM paginas WHERE slug = ?", (slug,)).fetchone():
            raise ValueError("Já existe uma página com esse endereço.")
        tem = con.execute("SELECT COUNT(*) FROM paginas").fetchone()[0]
        cur = con.execute("INSERT INTO paginas (slug, nome, principal, config, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?)",
                          (slug, _texto(nome, 80) or slug, 1 if (principal or not tem) else 0, json_texto(cfg), agora, agora))
        novo_id = cur.lastrowid
        if principal and tem:
            con.execute("UPDATE paginas SET principal = 0 WHERE id <> ?", (novo_id,))
    return obter(novo_id)


def salvar_config(pagina_id: int, config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = normalizar_config(config)
    with transacao() as con:
        con.execute("UPDATE paginas SET config = ?, atualizado_em = ? WHERE id = ?", (json_texto(cfg), agora_iso(), pagina_id))
    return obter(pagina_id)


def atualizar(pagina_id: int, nome: Optional[str] = None, slug: Optional[str] = None, principal: Optional[bool] = None) -> Dict[str, Any]:
    with transacao() as con:
        if slug is not None:
            slug = validar_slug(slug)
            if con.execute("SELECT 1 FROM paginas WHERE slug = ? AND id <> ?", (slug, pagina_id)).fetchone():
                raise ValueError("Já existe uma página com esse endereço.")
            con.execute("UPDATE paginas SET slug = ? WHERE id = ?", (slug, pagina_id))
        if nome is not None:
            con.execute("UPDATE paginas SET nome = ? WHERE id = ?", (_texto(nome, 80) or "Página", pagina_id))
        if principal:
            con.execute("UPDATE paginas SET principal = CASE WHEN id = ? THEN 1 ELSE 0 END", (pagina_id,))
        con.execute("UPDATE paginas SET atualizado_em = ? WHERE id = ?", (agora_iso(), pagina_id))
    return obter(pagina_id)


def excluir(pagina_id: int) -> None:
    with transacao() as con:
        total = con.execute("SELECT COUNT(*) FROM paginas").fetchone()[0]
        if total <= 1:
            raise ValueError("Mantenha pelo menos uma página.")
        era_principal = con.execute("SELECT principal FROM paginas WHERE id = ?", (pagina_id,)).fetchone()
        con.execute("DELETE FROM eventos WHERE pagina_id = ?", (pagina_id,))
        con.execute("DELETE FROM campanhas WHERE pagina_id = ?", (pagina_id,))
        con.execute("DELETE FROM paginas WHERE id = ?", (pagina_id,))
        if era_principal and era_principal["principal"]:
            con.execute("UPDATE paginas SET principal = 1 WHERE id = (SELECT id FROM paginas ORDER BY id LIMIT 1)")


def config_publica(pagina: Dict[str, Any]) -> Dict[str, Any]:
    cfg = pagina["config"]
    links = [{k: l.get(k) for k in ("id", "tipo", "titulo", "subtitulo", "exibicao", "destaque", "icone_custom", "cor")}
             for l in cfg["links"] if l.get("ativo") and l.get("url")]
    return {"slug": pagina["slug"], "perfil": cfg["perfil"], "textos": cfg["textos"], "tema": cfg["tema"], "coleta": cfg["coleta"], "links": links}
