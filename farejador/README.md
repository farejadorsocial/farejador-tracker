# Farejador — Guia de Redes Sociais + Laboratório de Coleta (v4, Python 3.9+)

Páginas no estilo "link na bio" com rastreamento de visitas e cliques, coleta consentida
de dados do navegador (para estudo) e um painel administrativo completo.

## Executar (Windows / VS Code)

```bash
python -m pip install -r requirements.txt
python iniciar.py        # ou duplo clique em executar.bat
```

| Endereço | O que é |
|---|---|
| `http://127.0.0.1:8000` | Página principal |
| `http://127.0.0.1:8000/<endereço>` | Outras páginas (ex.: `/games`) |
| `http://127.0.0.1:8000/c/<código>` | Link curto de campanha |
| `http://127.0.0.1:8000/admin` | Painel administrativo |

### Atualizando da versão 3
Na primeira vez que o servidor iniciar, os dados antigos (`data/config.json`, `data/eventos.jsonl`,
`data/visitors/*.json` e a senha de `data/admin.json`) são **importados automaticamente** para o
banco `data/farejador.db`. Entre no painel com o usuário **admin** e a mesma senha de antes.
Os arquivos antigos não são apagados; depois de conferir o painel você pode removê-los.

## O que tem no painel

**Análise**
- **Visão geral** — indicadores, gráfico diário, funil, cliques por link, origens, dispositivos e horários de pico.
  Ligue **Comparar** para ver o período anterior tracejado no gráfico e a tabela de variação por link e por origem.
  Escolha Hoje / 7 / 30 / 90 dias ou datas personalizadas (📅).
- **Tráfego** — fluxo *de onde veio → para onde foi*, feed ao vivo, sites de origem, campanhas UTM, idiomas, fusos e telas.
- **Retorno** — visitantes novos × recorrentes, tempo até voltar, origem que mais fideliza, coortes semanais e visitantes mais fiéis
  (mede quem aceitou a coleta, pois depende do cookie de visitante).
- **Campanhas** — crie links rastreados (`/c/código`) para cada lugar onde divulga: bio, stories, vídeo, grupo, QR impresso…
  Cada campanha mostra visitas, cliques, CTR e quais links foram clicados.
- **Visitantes** e **Mapa** — todos os dados do navegador e localização por IP (o IPinfo só é chamado quando você clica).

**Página**
- **Minhas páginas** — várias páginas no mesmo painel, cada uma com endereço, links, visual e estatísticas próprios.
  Dá para criar copiando outra página e escolher qual é a principal (`/`).
- **Links e redes** — mais de 30 redes com ícone e cor oficial; cada link aparece uma vez (botão ou ícone pequeno).
- **Aparência e textos** — fundo (tema pronto, cor, gradiente ou imagem), cor das letras, formato/estilo/animação dos botões,
  cor dos botões, 15 fontes, formato da foto e todos os textos. Prévia ao vivo no celular.
- **QR Code** — da página ou de qualquer campanha, com cores, estilo dos pontos e foto no centro. Baixa em PNG ou SVG.

**Sistema (Configurações)**
- Troca de senha, dispositivos conectados (desconectar), vários usuários.
- **Limpeza automática** de dados antigos (tráfego e visitantes, prazos configuráveis), também sob demanda.
- Exportação de eventos em CSV.

## Robôs e prévias
WhatsApp, Instagram/Facebook, X, Telegram, Google e outros "abrem" o link para montar a prévia.
Esses acessos (e navegadores automatizados ou pré-carregamentos) são marcados como **robô** e ficam
fora dos números. Para vê-los, ligue **Robôs** no topo ou o filtro "Robôs" no feed.

## Segurança do login
- Usuário + senha (mínimo 8 caracteres), senhas guardadas com PBKDF2-SHA256 (310 mil iterações).
- Sessões guardadas no banco (sobrevivem a reinícios), 12 h ou 30 dias com "manter conectado".
- Bloqueio por tentativas erradas (por conta e por dispositivo), proteção CSRF e cabeçalhos de segurança.
- Esqueceu a senha? Defina `FAREJADOR_ADMIN_SENHA` e reinicie: o usuário `admin` passa a usar essa senha.

## Organização do projeto

```
backend/
  main.py           monta a aplicação (rotas, cabeçalhos, inicialização)
  config.py         caminhos e variáveis de ambiente
  db.py             banco SQLite (data/farejador.db)
  paginas.py        páginas, personalização e validação
  seguranca.py      login, sessões, bloqueio e CSRF
  analise.py        User-Agent, robôs e origem das visitas
  estatisticas.py   visão geral, comparação, retorno e campanhas
  ipinfo.py         consulta de IP (só pelo painel)
  limpeza.py        apagar dados antigos
  migracao.py       importa os dados da versão anterior
  rotas/            publico.py, admin_auth.py, admin_paginas.py, admin_dados.py
frontend/
  index.html        página pública          css/style.css   js/coleta.js
  admin.html        painel                  css/admin.css   js/admin.js (entrada)
  js/admin/         api, estado, util, gráficos, mapas, QR, editor
  js/admin/vistas/  uma tela por arquivo (geral, trafego, retorno, campanhas, …)
  js/icones.js      ícones das redes (Simple Icons, CC0)
  vendor/           Chart.js, Leaflet e qrcode-generator (sem depender de CDN)
data/               farejador.db e uploads/ (não publique esta pasta)
```

## IPinfo, proxy e privacidade
- A página pública **não chama o IPinfo**; só descobre o IP público pelo ipify (necessário em `localhost`).
  Token opcional: `IPINFO_TOKEN`.
- Atrás de Cloudflare/Nginx que você controla: `FAREJADOR_TRUST_PROXY=1`.
- A coleta completa só acontece depois do "Aceitar". Quem recusa é contado de forma anônima.
- Para publicar na internet: HTTPS, senha forte e prazos de retenção adequados à LGPD. Faça backup da pasta `data`.
