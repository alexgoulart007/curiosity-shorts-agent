# MEMÓRIA — Curiosity Shorts Agent

## Projeto
Bot automatizado que gera e publica Shorts no YouTube com fatos curiosos em português.

## Repositório
`https://github.com/alexgoulart007/curiosity-shorts-agent.git`

## Stack
- **Linguagem:** Python 3.12
- **Hospedagem/CI:** GitHub Actions (Ubuntu)
- **APIs:** Wikipédia PT-BR, Pexels (vídeos), Google YouTube Data API v3
- **Bibliotecas principais:** wikipedia-api, edge-tts, moviepy, google-api-python-client

---

## Histórico de alterações

### Commit 1 — `initial commit`
- Estrutura inicial do projeto
- `agent.py`, `auth_youtube.py`, `requirements.txt`

### Commit 2 — `Add .gitignore and fix requirements`
- Criado `.gitignore` com `client_secret.json`, `youtube_token.json`, `output/`, `.env`
- `pillow` sem versão fixa

### Commit 3 — `Fix font not found on Linux runner`
- `agent.py`: `font` lê de `os.getenv("VIDEO_FONT", "Arial")`
- Workflow: adiciona `VIDEO_FONT=DejaVuSans` + instalação de fontes

### Commit 4 — `Use DejaVuSans font (pre-installed on Ubuntu)`
- Remove `fonts-liberation2` (desnecessário)
- `VIDEO_FONT=DejaVuSans` já vem instalado no Ubuntu

### Commit 5 — `Improve topics to avoid disambiguation and boring facts`
- 28 tópicos específicos (astronomia, biologia, paleontologia, etc.)
- `fetch_fact()`: pula páginas de desambiguação, retenta até 5x, mínimo 80 caracteres

### Commit 6 — `Improve retention: hooks, CTA, HD video, better SEO`
- **Hook:** "Você sabia que [tópico]?" em destaque dourado (3.5s)
- **CTA:** "Gostou? Inscreva-se!" no final (2.5s)
- **HD:** Filtra vídeos 720p+ do Pexels
- **Título:** Nome do tópico em maiúsculo + hashtag
- **Tags:** curiosidades, vocesabia, fatos, [topic], conhecimento, aprender
- **Query Pexels:** usa o nome do tópico em vez de primeiras palavras do fato

### Commit 7 — `Fix is_disambiguation not available in wikipedia-api 0.15.0`
- `fetch_fact()`: método `is_disambiguation()` não existe na biblioteca
- Criado `_is_disambig()` manual: verifica título `(desambiguação)` + resumo

### Commit 8 — `Add background music and voice variation`
- **Voz varia**: alterna entre `AntonioNeural` e `FranciscaNeural` aleatoriamente
- **Música de fundo**: baixa de SoundHelix (CC0/grátis) ou usa arquivos locais em `bg_music/`
- Volume da música reduzido para **12%** do original com `numpy`
- Se falhar baixar música, o vídeo segue sem (graceful fallback)

### Commit 9 — `Fix audio volume using numpy instead of fx import`
- `moviepy.audio.fx.all` não existe na versão 2.1.2
- Substituído por `AudioArrayClip(numpy_array * 0.12, fps=44100)`

### Commit 10 — `Add 3 daily schedules: 9h, 14h, 18h BRT`
- Workflow alterado de 1 para 3 schedules diários
- Cron: `0 12 * * *` (09h BRT), `0 17 * * *` (14h BRT), `0 21 * * *` (18h BRT)

### Commit 11 — `Fix: truncate TTS text at sentence boundary instead of mid-word`
- `fact[:500]` cortava no meio da palavra/frase
- Agora trunca no último ponto final (`.`, `!`, `?`) antes de 500 chars
- Áudio e legendas usam o mesmo texto truncado

### Commit 12 — `Improve topics: 60+ specific facts, no repeat tracking, full TTS reading`
- **60+ tópicos específicos** no lugar de 28 genéricos (ex: "Buraco negro", "Vikings", "Fossa das Marianas")
- **Sem repetição**: `used_topics.json` rastreia tópicos já usados e os pula
- **Fim do corte de áudio**: TTS lê o texto completo (removido limite de 500 chars)
- **Mais conteúdo**: busca na Wikipedia aumentado de 600 para 2000 caracteres
- **Seções**: 40% das vezes busca seções específicas do artigo em vez do resumo
- Workflow salva `used_topics.json` no repositório após cada execução bem-sucedida

### Commit 13 — `Fix: add write permissions and token auth for used_topics push`
- `github-actions[bot]` não tinha permissão de escrita no repositório
- Adicionado `permissions: contents: write` no workflow
- Autenticação via `${{ github.token }}` no `git push`

### Commit 14 — `Improve engagement: hooks with topic, countdown, highlights, brand color, auto-comment, Pexels English queries`
- **Hook personalizado**: `HOOKS` agora usam `{topic}` embutido no texto (ex: *"Pare tudo! {topic} é mais incrível do que parece:"*)
- **Countdown**: `3... 2... 1...` em laranja entre hook e conteúdo (1.5s) para segurar o espectador
- **Destaque numérico**: detecta números como "400 milhões", "70%" e exibe em destaque no topo da tela
- **CTA variado**: 5 opções com senso de prova social (*"1.432 pessoas já viram. Comenta aí!"*)
- **Cor de marca**: `COR_MARCA = "#FF6B00"` (laranja) padroniza hook, countdown, CTA e destaques
- **Título SEO**: `"{TOPIC} #Shorts"` mais limpo e buscável
- **Descrição**: pergunta "O que você achou?" + hashtags sem espaços
- **Comentário automático**: posta comentário no vídeo logo após o upload para engajar nos primeiros segundos
- **Música**: volume subiu de 12% para 25%
- **Mapeamento Pexels em inglês**: dicionário `TOPIC_QUERIES` com queries manuais em inglês para cada tópico (ex: "História do cinema" → `"vintage movie camera"`)
- **Fallback por categoria**: se a query específica falha, tenta queries da categoria (nature, space, history, etc.)
- **Escopo YouTube**: adicionado `youtube.force-ssl` para permitir comentários automáticos

### Commit 15 — `Add multi-clip Pexels (3 per video) and smooth zoom effect`
- **Múltiplos clipes**: `fetch_videos()` baixa 3 clipes diferentes do Pexels em vez de 1
- **Alternância**: os 3 clipes se alternam no vídeo final (sem loop monótono)
- **Zoom suave**: `_apply_zoom()` aplica zoom progressivo de 1.0x → 1.12x em cada clipe
- **Fallback**: se Pexels retornar menos de 3 vídeos, usa quantos conseguir

---

### Commit 16 — "Auto-renovação do token YouTube + workflow persist"
- **Problema:** Token expirava a cada 7 dias e o GitHub Actions perdia o token renovado por ser efêmero
- **Solução:**
  - `auth_youtube.py`: porta alterada de `8080` para `0` (evita conflito)
  - `daily-short.yml`: adicionado `gh secret set YOUTUBE_TOKEN` após o agent rodar, persistindo o token renovado de volta ao Secret do GitHub
- **App publicado no Google Cloud** (OAuth consent screen → "Em produção") para refresh token durar indefinidamente
- **Resultado:** Token renova sozinho para sempre, zero manutenção manual

### Commit 17 — "Blacklist de músicas + fallback automático"
- **Problema:** Vídeo "VIKINGS" bloqueado por Content ID por causa de música ("Recargado - Bólidos Venadenses")
- **Solução:**
  - Criado `music_blacklist.json`: músicas com claim são adicionadas e nunca mais usadas
  - **Ordem de escolha:** 1) Arquivos locais em `bg_music/` (pula blacklist) → 2) SoundHelix (pula blacklist) → 3) Música gerada por código (`numpy`, 100% original)
  - Blacklistadas: `Recargado - Bolidos Venadenses.mp3` e `Trance workout music - Salh Alheib Klel.mp3`
  - Workflow também comita `music_blacklist.json` junto com `used_topics.json`
  - No final do vídeo, o log mostra o nome da música usada

### Commit 18 — "Fix: GH_PAT para persistir token renovado"
- **Problema:** `gh secret set YOUTUBE_TOKEN` falhou — `secrets: write` não é permissão válida no GitHub Actions
- **Solução:** Workflow agora usa `GH_PAT` (Personal Access Token) para autenticar o `gh secret set`
- **Resultado:** Token renovado é salvo automaticamente no Secret do GitHub após cada execução ✅

### Commit 19 — "Fix: HDR metadata crash in MoviePy ffmpeg parser"
- **Problema:** Pexels passou a retornar vídeos com metadados HDR (`Side data: Mastering Display Metadata`), e o MoviePy 2.1.2 quebrava ao fazer parsing das linhas sem `:` no formato esperado
- **Solução:**
  - `_strip_hdr_metadata()` — remove metadados HDR via `ffmpeg -bsf:v filter_units=remove_types=6 -map_metadata -1` (cópia do bitstream, sem re-encodar)
  - `VideoFileClip()` dentro de try/except — se falhar ao carregar, limpa o vídeo e tenta de novo
  - Filtro de resolução corrigido no fallback do `fetch_videos()` — `elif videos:` vazava vídeos <720p

### Commit 20 — "Fix 6 bugs: download validation, OAuth port, blacklist, topic tracking"
- **#3** Download Pexels sem validação: adicionado `raise_for_status()` + try/except graceful
- **#4** `video_files` vazio: proteção contra `IndexError` (se Pexels retornar vídeo sem arquivos)
- **#2** Porta OAuth `8080` → `0` no `agent.py` (já estava corrigido no `auth_youtube.py` desde Commit 16)
- **#1** Blacklist SoundHelix: comparava URL completa contra filename, nunca bloqueava músicas
- **#9** Tópico salvo antes do upload: `save_used_topics()` movido para depois de `upload_short()` bem-sucedido
- **#10** `body_duration` negativo: adicionado `max(0, ...)` no cálculo do tempo de legendas
- **#6** Tópico "Fotossíntese" removido do `science_set` (já estava no `nature_set`)
- **#12** Tag do YouTube com espaços: `topic.replace(" ", "")` no lugar de `topic` bruto

### Commit 21 — "Add 32 topics, increase Pexels pool, expand hooks/CTAs"
- **+32 tópicos**: Origem do Universo, Matéria escura, Buraco de minhoca, Viagem no tempo, Clonagem, CRISPR, Células-tronco, Robótica, IA, Realidade virtual, Primeiro computador, Invenção do rádio, Invenção da lâmpada, Maior avião do mundo, Trem mais rápido do mundo, Muralha da China, Machu Picchu, Stonehenge, Guerra de Tróia, Catacumbas de Paris, Maior tempestade, Cachoeira mais alta, Lago mais profundo, Rio mais longo, Polvo, Ornitorrinco, Lula-colossal, Tubarão-baleia, Açaí, Café — **total: 108 tópicos** (~36 dias sem repetir)
- **Pexels**: `per_page` de 9 para 15 (mais variedade no shuffle, sem custo extra)
- **Hooks**: de 9 para **20 templates**
- **CTAs**: de 5 para **10 variações**
- `__pycache__/` adicionado ao `.gitignore`

### Commit 22 — "Fix 4 topics missing from categories"
- "Vulcão", "Terremoto", "Ilha mais remota do mundo" → `nature_set`
- "Língua mais falada do mundo" → `history_set`
- Agora **100% dos tópicos** têm categoria definida

### Commit 23 — "Fix: HDR video causing black/no-image on YouTube"
- **Problema:** Pexels retornava vídeos HDR (PQ/HLG), o MoviePy carregava sem crash mas mantinha pixels em gamma HDR, e o YouTube exibia o vídeo **preto** por interpretar como SDR
- **Solução:**
  - `_strip_hdr_metadata()` substituída por `_has_hdr()` + `_convert_hdr_to_sdr()`
  - `_has_hdr()` — detecta HDR via `ffprobe` (color_transfer) ou `ffmpeg` stderr (Mastering Display Metadata)
  - `_convert_hdr_to_sdr()` — transcodifica com `tonemap=hable:desat=0` + libx264 SDR (`yuv420p`) **só quando HDR é detectado**, vídeos SDR são ignorados
  - Loop de carregamento agora chama `_convert_hdr_to_sdr()` proativamente em todos os clipes (não espera crash)
  - Fallback seguro: se um clipe falha, pula e continua com os demais

### Commit 24 — "Fix: refresh_token revogado + erros silenciosos"
- **Problema:** Refresh_token do YouTube foi revogado (troca de senha Google), e o script crashava sem fallback para nova autenticação
- **Solução:**
  - `auth_youtube.py`: se `refresh()` falha, inicia novo fluxo OAuth automaticamente
  - `_search_pexels()`: erros HTTP e JSON agora são exibidos no log (antes eram silenciosos)
  - `create_short()`: se nenhum clipe carregar, levanta erro em vez de crashar com `concatenate_videoclips([])`
  - `main()`: valida se `final.mp4` existe antes do upload
- **GH_PAT configurado e funcionando:** Token renovado é persistido automaticamente no Secret do GitHub após cada execução ✅

### 2026-06-15 — Manutenção corretiva
- **Problema:** Refresh_token do YouTube foi revogado (causa provável: troca de senha Google)
- **Solução executada:**
  - Novo token gerado via `auth_youtube.py` corrigido
  - Secret `YOUTUBE_TOKEN` atualizado manualmente no GitHub
  - GH_PAT confirmado funcionando (passo "Persistir token renovado" ✅ verde)
- **Status atual:** Bot rodando normalmente (3x/dia)
- **Música com claim:** Áudio do vídeo `oc6Pl3K_AXI` substituído manualmente no YouTube Studio
- **Blacklist:** "Trance workout music - Salh Alheib Klel.mp3" já bloqueada (Commit 17)

### 2026-06-16 — Pixabay fallback quando Pexels falha
- **Problema:** Pexels ocasionalmente retornava 0 vídeos para queries específicas (acervo limitado), resultando em execuções sem clipe de fundo
- **Solução:**
  - `_search_pixabay()` — nova função que busca na API do Pixabay (vertical, >=10s, >=720p) seguindo a mesma lógica de queries + fallbacks por categoria
  - `_pexels_download()` / `_pixabay_download()` — funções extraídas para baixar clipes de cada fonte separadamente
  - `fetch_videos()` reestruturada: tenta Pexels primeiro; se falhar, tenta Pixabay com as mesmas queries antes de desistir
  - Workflow: adicionado `PIXABAY_API_KEY: ${{ secrets.PIXABAY_API_KEY }}`
- **Limites:** Pixabay 5.000 req/hora (nunca vai bater combinado com Pexels)
- **Arquivos alterados:**
  - `src/agent.py`: `_search_pixabay()`, `_pexels_download()`, `_pixabay_download()`; `fetch_videos()` reestruturada
  - `.github/workflows/daily-short.yml`: `PIXABAY_API_KEY` adicionado

### 2026-06-16 — Voz alternada + Legendas SRT
- **TTS_VOICE fixo removido do workflow:** Antes o GitHub Actions sempre usava `pt-BR-AntonioNeural`. Agora cai no `random.choice(VOICES)` e alterna entre Antonio e Francisca aleatoriamente a cada vídeo
- **Legendas SRT implementadas:**
  - Texto do corpo removido do vídeo (não tem mais `TextClip` queimado nos frames)
  - Arquivo `.srt` é gerado com os timestamps de cada frase
  - Enviado ao YouTube como legenda oculta via `captions().insert()`
  - Espectador pode ligar/desligar as legendas
  - Hook, contagem regressiva, destaques numéricos e CTA continuam como elementos visuais no vídeo
- **Arquivos alterados:**
  - `src/agent.py`: novas funções `_srt_time()`, `generate_srt()`, `upload_caption()`; `create_short()` modificada para gerar SRT e remover TextClips do corpo; `upload_short()` aceita `srt_path` opcional
  - `.github/workflows/daily-short.yml`: `TTS_VOICE` removido

### 2026-06-16 — Blacklist SoundHelix Song-4 + Pool expandido para 17 músicas
- **Problema:** Vídeo "ABELHA" com claim de direitos autorais no YouTube por causa de `SoundHelix-Song-4.mp3`
- **Solução:**
  - `music_blacklist.json`: adicionado `"SoundHelix-Song-4.mp3"` à blacklist
  - `src/agent.py`: `BG_MUSIC_URLS` expandido de 6 para 17 músicas (`range(1, 18)`) — Songs 1-17 existem, Songs 18+ não
  - Agora o sistema tem **17 músicas SoundHelix** disponíveis, das quais 1 está blacklistada (Song-4) = **16 utilizáveis**
- **Arquivos alterados:**
  - `music_blacklist.json`: entrada Song-4 adicionada
  - `src/agent.py`: `BG_MUSIC_URLS` gerado dinamicamente com `range(1, 18)`

### 2026-06-16 — Blacklist SoundHelix Song-8
- **Problema:** Vídeo "EXTINÇÃO DOS DINOSSAUROS" com claim de direitos autorais por causa de `SoundHelix-Song-8.mp3`
- **Solução:** `music_blacklist.json`: adicionado `"SoundHelix-Song-8.mp3"` à blacklist
- **Arquivos alterados:** `music_blacklist.json`

---
- YouTube Data API: **10.000 unidades/dia** (~6 uploads)
- GitHub Actions: **2000 minutos/mês** (cada execução leva ~1 min)
- Pexels: **15.000 requisições/mês** (plano grátis)
- Pixabay: **5.000 requisições/hora** (plano grátis, usado como fallback)

---

## Melhorias futuras possíveis
- [x] ~~Usar banco de curiosidades pré-selecionadas (evita texto genérico)~~ ✅ 108 tópicos específicos
- [x] ~~Música de fundo~~ ✅ SoundHelix CC0 + fallback local
- [x] ~~Voz feminina alternativa (pt-BR-FranciscaNeural)~~ ✅ Alterna aleatoriamente (agora também em produção)
- [x] ~~Hook genérico~~ ✅ Hook com tópico embutido + countdown
- [x] ~~CTA fixo~~ ✅ Variado com prova social
- [x] ~~Vídeo genérico do Pexels~~ ✅ Queries em inglês por tópico + fallback por categoria
- [x] ~~Sem comentários~~ ✅ Comentário automático pós-upload
- [x] ~~Legendas queimadas no vídeo~~ ✅ SRT enviado como legenda oculta do YouTube
- [ ] Legendas com animação (palavra por palavra)
- [x] ~~Pixabay como fallback do Pexels~~ ✅ Implementado no Commit 25
- [ ] **Pixabay + Pexels combinados**: buscar nos dois simultaneamente, juntar os resultados, shuffle e pegar os 3 melhores do pool total (mais variedade visual por vídeo)
- [ ] Dashboard para acompanhar vídeos postados
- [ ] Postar em múltiplos canais
- [x] ~~Vídeo em loop (monótono)~~ ✅ 3 clipes alternados + zoom suave
- [ ] Banco de vídeos próprio (evita depender do Pexels)
- [ ] Melhorias no highlight numérico com animação
- [x] ~~Vídeo preto (HDR sem conversão SDR)~~ ✅ _has_hdr() + _convert_hdr_to_sdr() com tonemap
- [x] ~~Refresh token revogado sem fallback~~ ✅ Fallback para nova autenticação automática
- [x] ~~Erros do Pexels silenciosos~~ ✅ Erros HTTP/JSON são exibidos no log
- [x] ~~GH_PAT não configurado~~ ✅ Configurado e funcionando

---

## Credenciais

| Serviço | Chave/Arquivo | Status |
|---------|---------------|--------|
| Google Cloud | `client_secret.json` | ✅ No secret `GOOGLE_CLIENT_SECRET` |
| YouTube Token | `youtube_token.json` | ✅ No secret `YOUTUBE_TOKEN` (renovado em 2026-06-15 c/ escopo force-ssl) |
| Pexels | API Key | ✅ No secret `PEXELS_API_KEY` |
| GH_PAT | Personal Access Token | ✅ Configurado — persiste token renovado automaticamente |
| Pixabay | API Key | ✅ No secret `PIXABAY_API_KEY` — fallback implementado |

> **Observação:** O token **renova automaticamente** via GitHub Actions. GH_PAT salva o token renovado de volta no Secret a cada execução. Zero manutenção manual.

---

## Fluxo do código (`src/agent.py`)

```
main()
├── fetch_fact() → (topic, full_text)
│   ├── Carrega used_topics.json → pula tópicos já usados
│   ├── Escolhe tópico aleatório dos 108
│   ├── Busca na Wikipédia PT-BR (resumo até 2000 chars)
│   ├── _is_disambig() → pula desambiguação (título + resumo)
│   ├── 40% de chance: busca seção específica do artigo
│   ├── Mínimo 80 caracteres
│   ├── Hook personalizado com {topic} embutido (20 templates)
│   └── Marca tópico como usado em memória (_used_topics)
├── generate_audio() → audio.mp3
│   └── edge-tts: voz aleatória (AntonioNeural ou FranciscaNeural)
├── fetch_videos() → [stock_0.mp4, stock_1.mp4, stock_2.mp4]
│   ├── TOPIC_QUERIES[topic] → queries em inglês (ex: "Buraco negro" → "black hole space")
│   ├── Fallback por categoria (nature, space, history, science, ocean)
│   ├── Pexels API (filtro 720p+, portrait, 10s+, 15 resultados)
│   ├── Se Pexels falhar → Pixabay API (mesmas queries, filtro vertical, 720p+, 10s+)
│   └── Baixa 3 clipes diferentes (Pexels ou Pixabay)
├── fetch_background_music() → bg_music/
│   └── SoundHelix (CC0) ou arquivos locais
├── create_short() → final.mp4 + legendas.srt
│   ├── _convert_hdr_to_sdr() em cada clipe (HDR→SDR se necessário)
│   ├── 3 clipes alternados com zoom suave 1.0x→1.12x
│   ├── Crop 1080x1920
│   ├── Hook com cor da marca (3.5s, #FF6B00)
│   ├── Countdown "3...2...1..." (1.5s, laranja)
│   ├── Texto do corpo via SRT (legenda oculta do YouTube)
│   ├── Destaque numérico no topo da tela
│   ├── Música de fundo (25% volume)
│   ├── CTA variado com prova social (10 variações, 2.5s)
│   └── generate_srt() → legendas.srt com timestamps sincronizados
└── upload_short() → YouTube
    ├── Google API (categoria 27, público)
    ├── Título SEO: "{TOPIC} #Shorts"
    ├── Descrição com call-to-action
    ├── Tags: curiosidades, vocesabia, fatos, [topic_sem_espacos], conhecimento
    ├── upload_caption() → envia legendas.srt como legenda oculta
    ├── Comentário automático pós-upload
    └── Só então salva used_topics.json (evita queimar tópico se crashar)
```

---

## ✅ Implementado — Pixabay fallback (Commit 25)

### O que foi feito
Quando `fetch_videos()` não encontra clipes no Pexels, tenta o Pixabay antes de desistir.

### O que você precisa fazer (1 vez)
1. **Criar conta no Pixabay** (https://pixabay.com/api/) → gerar API Key gratuita
2. **Adicionar `PIXABAY_API_KEY`** nos Secrets do GitHub (Settings → Secrets and variables → Actions)

### Como funciona
1. Tenta Pexels com as queries específicas + fallbacks por categoria
2. Se Pexels retornar 0 vídeos, tenta Pixabay com as mesmas queries
3. Se ambos falharem, retorna lista vazia (comportamento anterior: aborta)

### API Pixabay
```
GET https://pixabay.com/api/videos/?key=CHAVE&q=black+hole&orientation=vertical&per_page=15
```
- ✅ 5.000 requisições/hora (nunca vai bater)
- ✅ Licença gratuita, sem copyright, sem atribuição obrigatória
- Pexels + Pixabay juntos: cobertura muito maior que só Pexels, praticamente elimina falhas
