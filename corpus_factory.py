# -*- coding: utf-8 -*-
"""
corpus_factory.py - Fábrica de Corpus "Bairro em Dia" (GS 2027, CitizenTech)

Funções do pipeline: ingestão, extração, limpeza, normalização, anonimização,
segmentação, geração dos corpus, controle de qualidade.
Nenhuma etapa usa chave de API: os modelos de linguagem são abertos
(Hugging Face) e as saídas geradas ficam salvas em arquivo (cache).
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, deque
from pathlib import Path

DATA_CONSULTA = "2026-11-16"
MODELO_TOKENIZADOR = "Qwen/Qwen2.5-0.5B-Instruct"

SYSTEM_PROMPT = (
    "Você é o assistente do Bairro em Dia, um app para moradores do estado de São Paulo "
    "relatarem problemas do bairro (buracos, iluminação, lixo, barulho). Responda de forma "
    "simples e educada. Oriente como relatar, acompanhar o protocolo e a quem recorrer. "
    "Em urgência, mande ligar para 192 (SAMU), 193 (Bombeiros) ou 199 (Defesa Civil). "
    "Não faça diagnóstico nem aconselhamento jurídico individual: encaminhe a um profissional "
    "ou órgão público. Fora do tema, recuse com gentileza."
)

# ----------------------------------------------------------------------------
# 1. INGESTÃO
# ----------------------------------------------------------------------------

def carregar_manifesto(caminho):
    """Lê o CSV com os metadados dos documentos."""
    with open(caminho, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def baixar_documentos(manifesto, destino):
    """Baixa cada documento do manifesto (precisa de internet, ex.: Colab)."""
    import requests

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    resultado = {}
    for doc in manifesto:
        link = doc.get("link", "")
        alvo = destino / doc["arquivo"]
        if alvo.exists() and alvo.stat().st_size > 0:
            resultado[doc["arquivo"]] = "já existe"
            continue
        if not link.startswith("http"):
            resultado[doc["arquivo"]] = "sem link (envie o arquivo manualmente)"
            continue
        try:
            r = requests.get(
                link, headers={"User-Agent": "Mozilla/5.0 (GS FIAP - corpus)"}, timeout=60
            )
            r.raise_for_status()
            alvo.write_bytes(r.content)
            resultado[doc["arquivo"]] = f"ok ({len(r.content) // 1024} KB)"
        except Exception as e:  # noqa: BLE001
            resultado[doc["arquivo"]] = f"FALHOU: {e}"
    return resultado


def ingerir(manifesto, pasta_entrada, textos_colados=None):
    """Lê os arquivos do manifesto (PDF, TXT, DOCX, HTML) e o texto colado."""
    pasta = Path(pasta_entrada)
    docs, ausentes = [], []
    for m in manifesto:
        caminho = pasta / m["arquivo"]
        if not caminho.exists():
            ausentes.append(m["arquivo"])
            continue
        d = dict(m)
        d["texto_bruto"] = extrair_texto(caminho)
        docs.append(d)
    for i, t in enumerate(textos_colados or [], start=1):
        docs.append({
            "arquivo": f"texto_colado_{i}.txt", "titulo": f"Texto colado {i}",
            "orgao": "não informado", "link": "", "data": DATA_CONSULTA,
            "em_corpus": "sim", "texto_bruto": t,
        })
    return docs, ausentes


# ----------------------------------------------------------------------------
# 2. EXTRAÇÃO
# ----------------------------------------------------------------------------

def _ler_texto_simples(caminho):
    dados = Path(caminho).read_bytes()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return dados.decode(enc)
        except UnicodeDecodeError:
            continue
    return dados.decode("utf-8", errors="ignore")


def extrair_pdf(caminho):
    from pypdf import PdfReader

    paginas = [(p.extract_text() or "") for p in PdfReader(str(caminho)).pages]
    return "\n".join(paginas)  # a limpeza remove cabeçalhos/rodapés repetidos


def extrair_docx(caminho):
    import docx

    d = docx.Document(str(caminho))
    linhas = [p.text for p in d.paragraphs]
    for tabela in d.tables:
        for linha in tabela.rows:
            linhas.append(" ".join(c.text.strip() for c in linha.cells))
    return "\n".join(linhas)


def extrair_html(caminho):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(Path(caminho).read_bytes(), "html.parser")  # detecta a codificação
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript",
                     "strike", "s", "del"]):  # strike/del = texto revogado no Planalto
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with(" ")  # <br> dentro de parágrafo vira espaço
    for tag in soup.find_all(["sup", "u", "b", "i", "a", "span", "font", "strong", "em"]):
        tag.unwrap()  # evita quebrar "Art. 1º" em várias linhas
    soup.smooth()
    # o HTML do Planalto quebra linhas DENTRO dos parágrafos: vira espaço
    for no in soup.find_all(string=True):
        no.replace_with(re.sub(r"[ \t\r\n]+", " ", str(no)))
    return soup.get_text("\n")


def extrair_texto(caminho):
    ext = Path(caminho).suffix.lower()
    if ext == ".pdf":
        return extrair_pdf(caminho)
    if ext == ".docx":
        return extrair_docx(caminho)
    if ext in (".html", ".htm"):
        return extrair_html(caminho)
    return _ler_texto_simples(caminho)  # .txt e demais


# ----------------------------------------------------------------------------
# 3. LIMPEZA
# ----------------------------------------------------------------------------
RE_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
RE_NUM_PAG = re.compile(r"^\s*(?:p[áa]g(?:ina)?\.?\s*)?\d{1,4}\s*(?:de|/)\s*\d{1,4}\s*$", re.I)
RE_SO_NUM = re.compile(r"^\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*$")
RE_DATAHORA = re.compile(r"^\s*\d{2}/\d{2}/\d{2,4}(?:,)?\s+\d{2}:\d{2}.*$")
RE_CODIGO = re.compile(r"^\s*(?:DEL|L)\d{3,6}\s*$")
RE_CABECALHO = re.compile(
    r"^\s*(Presid[eê]ncia da Rep[úu]blica|Casa Civil|Secretaria-Geral|Subchefia para Assuntos "
    r"Jur[íi]dicos|Texto compilado|Vig[êe]ncia|Regulamento|Mensagem de veto|Ficha informativa|"
    r"Assembleia Legislativa do Estado de S[ãa]o Paulo.*|\((?:Atualizad[ao]|Texto atualizado|"
    r"[ÚU]ltima atualiza[çc][ãa]o).*\)|Este texto n[ãa]o substitui.*|Publica[çc][ãa]o Original|"
    r"Veja tamb[ée]m:?)\s*$", re.I)
RE_NOTA_LINHA = re.compile(
    r"^\s*(?:[a-z]\)\s*)?(?:Declarad[oa] inconstitucional|Texto republicado|Nota LegisWeb|"
    r"Revogad[oa]\.?\s*$|Vetado\.?\s*$)", re.I)
RE_ANOTACAO = re.compile(
    r"\s*\((?:Reda[çc][ãa]o dada|Inclu[íi]d[oa]|Revogad[oa]|Vide|Vig[êe]ncia|Regulamento|"
    r"Regulamenta|Produ[çc][ãa]o de efeito|Vetad[oa]|VETAD[OA]|Veto|Promulga[çc][ãa]o|"
    r"Renumerad[oa]|Declarad[oa]|Alterad[oa]|Acrescentad[oa]|Institu[íi]d[oa]|Acrescid[oa]|"
    r"Suprimid[oa]|Lei n|Medida Provis|Decreto n|Emenda)[^)]*\)", re.I)
RE_ASSINATURA = re.compile(
    r"^\s*(Bras[íi]lia,\s+\d{1,2}\s+de\s+\w+\s+de\s+\d{4}|Pal[áa]cio dos Bandeirantes)", re.I)
RE_ASSINATURA_INLINE = re.compile(
    r"(Bras[íi]lia,\s+\d{1,2}\s+de\s+\w+\s+de\s+\d{4}|Pal[áa]cio dos Bandeirantes,\s+\d{1,2}|"
    r"Pal[áa]cio dos Bandeirantes,\s+aos)", re.I)
RE_CABECALHO_INICIO = re.compile(
    r"(Presid[eê]ncia da Rep[úu]blica|Secretaria-Geral|Subchefia para Assuntos Jur[íi]dicos|"
    r"Casa Civil)\s*", re.I)
RE_ESTRUTURA = re.compile(
    r"^(Art\.|§|Par[áa]grafo|[IVXLC]+\s*[-–.)]|[a-z]\)|\d+[.)]\s)")
RE_SECAO = re.compile(
    r"^(?:T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|LIVRO|Cap[íi]tulo|T[íi]tulo|Se[çc][ãa]o)\s+[IVXLCDM\d]+\b.*$")


def limpar_texto(texto, reflow_linhas=False):
    """Remove ruído: cabeçalhos/rodapés, páginas, URLs, anotações, linhas repetidas."""
    t = texto.replace("\f", "\n").replace("\r", "\n")
    # junta palavras quebradas por hífen no fim da linha
    t = re.sub(r"(?<=[a-záéíóúâêôãõç])-[ \t]*\n[ \t]*(?=[a-záéíóúâêôãõç])", "", t)
    t = RE_URL.sub("", t)
    # caracteres estranhos: controles, formatação invisível, hífen suave
    t = "".join(
        ch for ch in t
        if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs")
    )
    linhas = []
    for linha in t.split("\n"):
        l = linha.strip()
        if not l:
            linhas.append("")
            continue
        if (RE_NUM_PAG.match(l) or RE_SO_NUM.match(l) or RE_DATAHORA.match(l)
                or RE_CODIGO.match(l) or RE_CABECALHO.match(l) or RE_NOTA_LINHA.match(l)):
            continue
        linhas.append(l)
    # corta o bloco de assinatura (nomes de autoridades públicas), mesmo no meio da linha
    for i, l in enumerate(linhas):
        m = RE_ASSINATURA_INLINE.search(l)
        if m:
            linhas = linhas[:i] + ([l[:m.start()].rstrip()] if l[:m.start()].strip() else [])
            break
    # cabeçalho institucional colado no início do documento
    inicio = " ".join(linhas[:8])
    if RE_CABECALHO_INICIO.search(inicio):
        linhas = [RE_CABECALHO_INICIO.sub("", l) for l in linhas[:8]] + linhas[8:]
    # linhas repetidas (cabeçalho/rodapé de PDF), preservando estrutura legal e títulos de seção
    contagem = Counter(l for l in linhas if l)
    filtradas, anterior = [], ""
    for l in linhas:
        repetida = (l and contagem[l] >= 3 and len(l) <= 100 and not RE_ESTRUTURA.match(l)
                    and not RE_SECAO.match(l) and not RE_SECAO.match(anterior))
        if not repetida:
            filtradas.append(l)
        if l:
            anterior = l
    linhas = filtradas
    t = "\n".join(linhas)
    t = RE_ANOTACAO.sub("", t)
    return _reflow(t) if reflow_linhas else t


def parece_quebrado_por_largura(texto):
    """True se as linhas parecem ter sido quebradas na largura da página (PDF/TXT)."""
    comp = [len(l) for l in texto.split("\n") if l.strip()]
    if len(comp) < 10:
        return False
    comp.sort()
    mediana = comp[len(comp) // 2]
    sem_ponto = sum(1 for l in texto.split("\n") if l.strip() and l.strip()[-1] not in ".:;!?")
    return 40 <= mediana <= 110 and sem_ponto / len(comp) > 0.4


def _reflow(texto):
    saida, atual = [], ""
    for linha in texto.split("\n"):
        l = linha.strip()
        if not l:
            if atual:
                saida.append(atual)
                atual = ""
            continue
        if not atual:
            atual = l
            continue
        fim_frase = atual[-1] in ".:;!?"
        if RE_ESTRUTURA.match(l) or RE_SECAO.match(l) or (fim_frase and l[0].isupper()):
            saida.append(atual)
            atual = l
        else:
            atual += " " + l
    if atual:
        saida.append(atual)
    return "\n".join(saida)


# ----------------------------------------------------------------------------
# 4. NORMALIZAÇÃO
# ----------------------------------------------------------------------------
_ASPAS = {"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "´": "'", "`": "'", "«": '"', "»": '"'}


def normalizar_texto(texto):
    """UTF-8/NFC, aspas, espaços e quebras padronizados. Mantém acentos e maiúsculas."""
    t = texto
    try:
        import ftfy

        t = ftfy.fix_text(t)
    except ImportError:
        pass
    t = unicodedata.normalize("NFC", t)
    for a, b in _ASPAS.items():
        t = t.replace(a, b)
    t = t.replace("\u00a0", " ").replace("\u2009", " ")
    t = re.sub(r"\b(Art\.?\s*\d+)[oº°]\b", r"\1º", t)      # "Art. 5o" -> "Art. 5º"
    t = re.sub(r"(§\s*\d+)[o°]\b", r"\1º", t)                # "§ 1o" -> "§ 1º"
    t = re.sub(r"\b(n)[º°o]\s*(?=\d)", r"\1º ", t)           # "n° 12" -> "nº 12"
    t = re.sub(r"[ \t]+", " ", t)
    t = "\n".join(l.strip() for l in t.split("\n"))
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def estruturar_paragrafos(texto, titulo_padrao):
    """Cada linha vira um parágrafo e recebe a seção (capítulo/seção) em vigor."""
    linhas = [l.strip() for l in texto.split("\n")]
    paragrafos, secao, i = [], titulo_padrao, 0
    while i < len(linhas):
        l = linhas[i]
        if not l:
            i += 1
            continue
        if RE_SECAO.match(l):
            sec = l
            prox = linhas[i + 1] if i + 1 < len(linhas) else ""
            if prox and len(prox) < 90 and not RE_ESTRUTURA.match(prox) and not prox.endswith("."):
                sec += " - " + prox
                i += 1
            secao = sec
        else:
            paragrafos.append((l, secao))
        i += 1
    return paragrafos


# ----------------------------------------------------------------------------
# 5. ANONIMIZAÇÃO (sem tabela de correspondência: a troca é irreversível)
# ----------------------------------------------------------------------------
EXCECOES_NOMES = [  # leis, instituições e figuras públicas que NÃO são mascaradas
    "Maria da Penha", "Fiocruz", "Defesa Civil", "SAMU", "Corpo de Bombeiros",
    "Código de Trânsito", "Defensoria Pública", "Ministério Público", "Poder Executivo",
    "Constituição", "Estatuto", "Tribunal",
]
TERMOS_NAO_NOME = {
    "Lei", "Decreto", "Código", "Estatuto", "Estado", "União", "Município", "Poder", "Defesa",
    "Civil", "Ministério", "Governo", "Presidente", "Constituição", "Federal", "Nacional",
    "Política", "Sistema", "Conselho", "Secretaria", "Prefeitura", "Câmara", "Assembleia",
    "Departamento", "Agência", "Tribunal", "Comissão", "Ouvidoria", "Resolução",
}
TERMOS_NAO_NOME.update({
    "Distrito", "Sistema", "Resíduos", "Sólidos", "Administração", "Pública", "Público", "Agentes",
    "Trânsito", "Brasileiro", "Normas", "Regime", "Plano", "Programa", "Contravenções", "Penais",
    "Informação", "Acesso", "Proteção", "Usuário", "Usuários", "Serviços", "Públicos", "Municipal",
    "Estadual", "Ministro", "Secretário", "Governador", "Congresso", "Senado", "Art", "Artigo",
    "Parágrafo", "Capítulo", "Seção", "Título", "Anexo", "Inciso", "Autoridade", "Órgão", "Órgãos",
    "Entidade", "Entidades", "Gestor", "Gestão", "Ambiental", "Ambientais", "Licenciamento",
    "Saneamento", "Transporte", "Infração", "Penalidade", "Veículo", "Condutor", "Registro",
    "Cidades", "Metropolitanas", "Região", "Regiões", "Solo", "Social", "Sociedade", "Cidadão",
})
_TERMOS_LOWER = {t.lower() for t in TERMOS_NAO_NOME}
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_CPF = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
RE_11_DIGITOS = re.compile(r"(?<![\d.])\d{11}(?!\d)")


def _cpf_valido(d):
    if len(set(d)) == 1:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def _rotulo_11_digitos(m):
    d = m.group(0)
    if _cpf_valido(d):
        return "[CPF]"
    return "[TELEFONE]" if re.fullmatch(r"\d{2}9\d{8}", d) else "[CPF]"
RE_RG = re.compile(r"(?<!\d)\d{1,2}\.\d{3}\.\d{3}-[\dXx](?!\d)")
RE_TEL = re.compile(
    r"(?<![\d.])(?:\+?55[\s-]?)?(?:\(\s*\d{2}\s*\)|\b\d{2})[\s-]?(?:9[\s-]?)?\d{4}[\s-]?\d{4}(?!\d)")
RE_TEL_CURTO = re.compile(r"(?<![\d.-])(?:9\s?)?\d{4}-\d{4}(?!\d)")
RE_ENDERECO = re.compile(
    r"\b(?:Rua|Avenida|Av\.|Travessa|Alameda|Estrada|Rodovia|Praça)[ \t]+(?:d[aeo]s?[ \t]+)?"
    r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][^,\n]{1,50},[ \t]*(?:n[ºo.]?[ \t]*)?\d+")
_NOME = (r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w'’-]+(?:[ \t]+(?:d[aeo]s?[ \t]+)?[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w'’-]+)*")
RE_NOME_ROTULO = re.compile(
    r"((?:Nome(?: do solicitante| completo)?|Solicitante|Requerente|Paciente|Morador|Moradora|"
    r"Atendente|Respons[áa]vel)\s*:\s*)(" + _NOME + ")")
RE_NOME_TRATAMENTO = re.compile(
    r"\b((?i:Sr\.?|Sra\.?|Dr\.?|Dra\.?|senhor|senhora|moradora?|vizinh[oa]|atendente)\s+)("
    + _NOME + ")")
RE_CANDIDATO_NOME = re.compile(
    r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+\s+(?:d[aeo]s?\s+)?[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+")


def _tem_termo_institucional(texto):
    return any(tok.strip(",.;:()\"'").lower() in _TERMOS_LOWER for tok in texto.split())


def _entidade_pessoa_valida(e):
    """Regras para uma entidade PER do NER ser mascarada (evita falsos positivos em leis)."""
    txt = e.text
    return (e.label_ == "PER" and len(txt.split()) >= 2 and not _eh_excecao(txt)
            and not _tem_termo_institucional(txt) and not txt.isupper()
            and not re.search(r"\d", txt) and "[" not in txt)


def _eh_excecao(nome):
    n = nome.lower()
    return any(e.lower() in n for e in EXCECOES_NOMES)


def _tel_valido(m):
    d = re.sub(r"\D", "", m.group(0))
    if d.startswith("55") and len(d) > 11:
        d = d[2:]
    if len(d) not in (10, 11):
        return False
    resto = d[2:]
    if len(resto) == 8 and re.fullmatch(r"(?:19|20)\d{2}(?:19|20)\d{2}", resto):
        return False  # intervalo de anos, ex.: 2011-2014
    return True


def carregar_ner(modelo="pt_core_news_lg"):
    """Carrega o spaCy só com o NER. Retorna None se não estiver instalado."""
    try:
        import spacy

        return spacy.load(modelo, exclude=["parser", "lemmatizer", "morphologizer",
                                           "attribute_ruler", "senter"])
    except Exception as e:  # noqa: BLE001
        print(f"AVISO: NER indisponível ({e}). Nomes só serão mascarados por regras.")
        return None


def anonimizar(texto, nlp=None, contagem=None):
    """Troca dados pessoais por marcadores. Retorna (texto_anonimizado, contagem)."""
    cont = contagem if contagem is not None else Counter()

    def sub(regex, marcador, t, fn=None):
        def r(m):
            if fn and not fn(m):
                return m.group(0)
            cont[marcador] += 1
            return marcador
        return regex.sub(r, t)

    t = sub(RE_EMAIL, "[EMAIL]", texto)
    t = sub(RE_CPF, "[CPF]", t)

    def troca_11(m):
        r = _rotulo_11_digitos(m)
        cont[r] += 1
        return r

    t = RE_11_DIGITOS.sub(troca_11, t)
    t = sub(RE_RG, "[RG]", t)
    t = sub(RE_TEL, "[TELEFONE]", t, _tel_valido)
    t = sub(RE_TEL_CURTO, "[TELEFONE]",
            t, lambda m: not re.fullmatch(r"(?:19|20)\d{2}-(?:19|20)\d{2}", m.group(0)))
    t = sub(RE_ENDERECO, "[ENDERECO]", t)

    def troca_nome(m):
        if _eh_excecao(m.group(2)) or set(m.group(2).split()) & TERMOS_NAO_NOME:
            return m.group(0)
        cont["[NOME]"] += 1
        return m.group(1) + "[NOME]"

    t = RE_NOME_ROTULO.sub(troca_nome, t)
    t = RE_NOME_TRATAMENTO.sub(troca_nome, t)

    if nlp is not None and RE_CANDIDATO_NOME.search(t):  # NER só onde há candidato
        doc = nlp(t)
        spans = [e for e in doc.ents if _entidade_pessoa_valida(e)]
        for e in sorted(spans, key=lambda s: s.start_char, reverse=True):
            t = t[: e.start_char] + "[NOME]" + t[e.end_char:]
            cont["[NOME]"] += 1
    return t, cont


PADROES_PII = [RE_EMAIL, RE_CPF, RE_RG, RE_ENDERECO, RE_11_DIGITOS]


def varrer_pii(registros, extrator):
    """Verificação final: nenhum CPF/e-mail/RG/telefone pode sobrar nos corpus."""
    achados = []
    for i, r in enumerate(registros):
        txt = extrator(r)
        for rx in PADROES_PII:
            if rx.search(txt):
                achados.append((i, rx.pattern[:20]))
        for m in RE_TEL.finditer(txt):
            if _tel_valido(m):
                achados.append((i, "telefone"))
    return achados


def varrer_nomes(registros, extrator, nlp):
    """Nomes de pessoas que o NER ainda encontra nos corpus FINAIS. Esperado: lista vazia."""
    if nlp is None:
        return []
    achados = []
    for i, r in enumerate(registros):
        t = extrator(r)
        if not RE_CANDIDATO_NOME.search(t):
            continue
        for e in nlp(t).ents:
            if _entidade_pessoa_valida(e):
                achados.append((i, e.text))
    return achados


RE_MOJIBAKE = re.compile("Ã[\u0080-\u00bf]|Â[\u00a0-\u00bf]|\ufffd|â€")


def auditar_codificacao(registros, extrator):
    """Procura texto com codificação quebrada (Ã§, Ã£, �). Esperado: lista vazia."""
    saida = []
    for i, r in enumerate(registros):
        m = RE_MOJIBAKE.search(extrator(r))
        if m:
            saida.append((i, m.group(0)))
    return saida


def auditar_ner(docs, nlp):
    """CONFERÊNCIA (não salvar!): entidades PER que o NER acha nos documentos oficiais.
    Retorna Counter[(arquivo, entidade, sera_mascarada)] para achar falsos positivos."""
    cont = Counter()
    if nlp is None:
        return cont
    for d in docs:
        if str(d.get("em_corpus", "sim")).lower() not in ("sim", "s", "true", "1"):
            continue
        quebrado = d["arquivo"].lower().endswith(".pdf")
        norm = normalizar_texto(limpar_texto(d["texto_bruto"], reflow_linhas=quebrado))
        for p, _ in estruturar_paragrafos(norm, d.get("titulo", d["arquivo"])):
            if not RE_CANDIDATO_NOME.search(p):
                continue
            for e in nlp(p).ents:
                if e.label_ == "PER" and len(e.text.split()) >= 2:
                    cont[(d["arquivo"], e.text, _entidade_pessoa_valida(e))] += 1
    return cont


# ----------------------------------------------------------------------------
# 6. SEGMENTAÇÃO (256-512 tokens do tokenizador do Qwen2.5-0.5B-Instruct)
# ----------------------------------------------------------------------------

def carregar_contador(nome=MODELO_TOKENIZADOR, permitir_fallback=False):
    """Retorna uma função texto -> nº de tokens. Fallback aproximado só p/ testes locais."""
    try:
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(nome)
        return lambda t: len(tok.encode(t, add_special_tokens=False))
    except Exception as e:  # noqa: BLE001
        if not permitir_fallback:
            raise
        print(f"AVISO: tokenizador real indisponível ({e}); usando estimativa APENAS para teste.")
        return lambda t: int(len(re.findall(r"\w+|[^\w\s]", t)) * 1.35)


_RE_FRASE = re.compile(
    r"(?<!\bArt)(?<!\bart)(?<!\bnº)(?<!\binc)(?<!§)(?<!\bDr)(?<!\bSr)(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])")


def dividir_frases(texto):
    return [s.strip() for s in _RE_FRASE.split(texto) if s.strip()]


def _cortar_por_palavras(frase, contar, maximo):
    partes, atual = [], []
    for w in frase.split():
        if atual and contar(" ".join(atual + [w])) > maximo:
            partes.append(" ".join(atual))
            atual = []
        atual.append(w)
    if atual:
        partes.append(" ".join(atual))
    return partes


def segmentar(paragrafos, contar, minimo=256, maximo=512):
    """Agrupa parágrafos em trechos de minimo..maximo tokens, sem cortar frases."""
    fila = deque()
    for texto, secao in paragrafos:
        fila.append((texto, secao, contar(texto), False))
    trechos, atual, ntok = [], [], 0

    def fechar():
        nonlocal atual, ntok
        if atual:
            trechos.append(atual)
        atual, ntok = [], 0

    while fila:
        texto, secao, n, dividido = fila.popleft()
        if n > maximo:  # parágrafo grande: divide por frases (e, se preciso, por palavras)
            partes = []
            for fr in dividir_frases(texto):
                nfr = contar(fr)
                partes += [fr] if nfr <= maximo else _cortar_por_palavras(fr, contar, maximo)
            for p in reversed(partes):
                fila.appendleft((p, secao, contar(p), True))
            continue
        if atual and ntok + n + 1 > maximo:
            if ntok < minimo and not dividido:
                frases = dividir_frases(texto)
                if len(frases) > 1:  # tenta preencher o trecho atual com as frases
                    for fr in reversed(frases):
                        fila.appendleft((fr, secao, contar(fr), True))
                    continue
            fechar()
        atual.append((texto, secao))
        ntok += n + 1
    fechar()

    # cauda curta: tenta fundir com o trecho anterior
    if len(trechos) >= 2:
        ult = "\n".join(t for t, _ in trechos[-1])
        if contar(ult) < minimo:
            junto = "\n".join(t for t, _ in trechos[-2] + trechos[-1])
            if contar(junto) <= maximo:
                trechos[-2] = trechos[-2] + trechos[-1]
                trechos.pop()
    return [("\n".join(t for t, _ in tr), tr[0][1]) for tr in trechos]


def construir_corpus_texto(docs, contar, nlp=None, minimo=256, maximo=512):
    """Limpeza -> normalização -> anonimização -> segmentação para cada documento."""
    registros, relatorio, cont_total = [], {}, Counter()
    for d in docs:
        if str(d.get("em_corpus", "sim")).lower() not in ("sim", "s", "true", "1"):
            continue
        bruto = d["texto_bruto"]
        quebrado = (d["arquivo"].lower().endswith(".pdf")
                    or (d["arquivo"].lower().endswith(".txt") and parece_quebrado_por_largura(bruto)))
        limpo = limpar_texto(bruto, reflow_linhas=quebrado)
        norm = normalizar_texto(limpo)
        paragrafos = estruturar_paragrafos(norm, d.get("titulo", d["arquivo"]))
        anon = []
        for p, s in paragrafos:
            p2, _ = anonimizar(p, nlp, cont_total)
            anon.append((p2, s))
        trechos = segmentar(anon, contar, minimo, maximo)
        antes = len(trechos)
        trechos = [(t, sc) for t, sc in trechos if minimo <= contar(t) <= maximo]
        descartados_faixa = antes - len(trechos)
        for i, (txt, secao) in enumerate(trechos, start=1):
            registros.append({
                "text": txt, "fonte": d["arquivo"], "secao": secao, "data": d["data"],
                "id": f"{Path(d['arquivo']).stem}#{i:03d}", "titulo": d.get("titulo", ""),
                "orgao": d.get("orgao", ""), "link": d.get("link", ""),
            })
        palavras = sum(len(p.split()) for p, _ in anon)
        relatorio[d["arquivo"]] = {"palavras": palavras, "trechos": len(trechos),
                                   "descartados_fora_da_faixa": descartados_faixa}
    return registros, relatorio, cont_total


# ----------------------------------------------------------------------------
# 7. LÍNGUA REAL, DUPLICATAS E VAZAMENTO
# ----------------------------------------------------------------------------
_ABREV = [
    (r"\bvocês\b", "vcs"), (r"\bvocê\b", "vc"), (r"\bpara\b", "pra"), (r"\bpor que\b", "pq"),
    (r"\bporque\b", "pq"), (r"\bnão\b", "nao"), (r"\btambém\b", "tb"), (r"\bquando\b", "qnd"),
    (r"\bo que\b", "oq"), (r"\bestá\b", "ta"), (r"\bestou\b", "to"), (r"\bmuito\b", "mto"),
    (r"\bhoje\b", "hj"), (r"\bcomigo\b", "cmg"), (r"\bque\b", "q"), (r"\bquem\b", "qm"),
]
_MARCAS_REAIS = re.compile(r"\b(vc|vcs|pq|pra|tb|oq|q|nao|hj|ta|to|mto|qnd|cmg|qm)\b")


def _sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def ruidificar(pergunta, rng):
    """Faz a pergunta imitar o jeito real de escrever (as respostas NÃO passam por aqui)."""
    estilo = rng.choice(["informal", "informal", "caps", "typo"])
    t = pergunta
    if estilo == "caps":
        t = _sem_acento(t.upper()) if rng.random() < 0.5 else t.upper()
        return t.rstrip("?") + "??" if rng.random() < 0.6 else t
    if estilo == "typo":
        palavras = t.split()
        longas = [i for i, w in enumerate(palavras) if len(w) > 5 and w.isalpha()]
        if longas:
            i = rng.choice(longas)
            w = palavras[i]
            j = rng.randrange(1, len(w) - 2)
            palavras[i] = w[:j] + w[j + 1] + w[j] + w[j + 2:]  # troca duas letras
        t = " ".join(palavras)
        return _sem_acento(t.lower()) if rng.random() < 0.5 else t
    t = t.lower()
    for padrao, troca in _ABREV:
        t = re.sub(padrao, troca, t)
    t = _sem_acento(t)
    if rng.random() < 0.7:
        t = t.rstrip("?")
        if rng.random() < 0.4:
            t += "??"
    return t


def eh_lingua_real(p):
    """Heurística: caixa alta, '??', abreviações, sem maiúscula inicial ou sem pontuação/acentos."""
    return bool(
        (p.isupper() and len(p) > 3) or "??" in p or _MARCAS_REAIS.search(p.lower())
        or p[:1].islower() or (p == p.lower() and "?" not in p)
    )


def aplicar_lingua_real(perguntas, fracao=0.35, semente=7):
    """Retorna as perguntas com `fracao` delas reescritas em língua real."""
    rng = random.Random(semente)
    n = len(perguntas)
    alvo = set(rng.sample(range(n), int(round(n * fracao)))) if n else set()
    return [ruidificar(p, rng) if i in alvo else p for i, p in enumerate(perguntas)]


def _norm_chave(t):
    t = _sem_acento(t.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def deduplicar(registros, extrator):
    """Remove duplicatas exatas após normalização. Retorna (únicos, removidos)."""
    vistos, unicos = set(), []
    for r in registros:
        k = _norm_chave(extrator(r))
        if k in vistos:
            continue
        vistos.add(k)
        unicos.append(r)
    return unicos, len(registros) - len(unicos)


def remover_quase_duplicatas(registros, extrator, limiar=0.95,
                             modelo="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
    """Quase-duplicatas por similaridade de cosseno entre embeddings (aula de RAG)."""
    from sentence_transformers import SentenceTransformer

    if len(registros) < 2:
        return registros, 0
    emb = SentenceTransformer(modelo).encode(
        [extrator(r) for r in registros], normalize_embeddings=True, show_progress_bar=False)
    sim = emb @ emb.T
    manter = []
    for i in range(len(registros)):
        if all(sim[i, j] < limiar for j in manter):
            manter.append(i)
    return [registros[i] for i in manter], len(registros) - len(manter)


def verificar_vazamento(perguntas_teste, perguntas_treino, jaccard=0.8):
    """Lista pares (teste, treino) iguais ou quase iguais. Esperado: lista vazia."""
    def toks(p):
        return set(_norm_chave(p).split())
    achados = []
    tt = [(p, _norm_chave(p), toks(p)) for p in perguntas_teste]
    for q in perguntas_treino:
        kq, tq = _norm_chave(q), toks(q)
        for p, kp, tp in tt:
            if kp == kq or (tp and tq and len(tp & tq) / len(tp | tq) >= jaccard):
                achados.append((p, q))
    return achados


# ----------------------------------------------------------------------------
# 8. GERAÇÃO COM MODELO ABERTO (cache em arquivo: o notebook roda sem API)
# ----------------------------------------------------------------------------
PROMPT_QA = """Você cria dados de treino para um assistente público do estado de São Paulo que \
orienta moradores sobre problemas do bairro (buracos, iluminação, lixo, barulho) e sobre \
como buscar atendimento.

TRECHO DO DOCUMENTO OFICIAL:
\"\"\"{trecho}\"\"\"

Escreva {n} pares de pergunta e resposta sobre o trecho.
Regras:
1. Use SOMENTE informações que estão no trecho. Não invente prazos, valores, números ou órgãos.
2. A pergunta é curta e faz sentido SOZINHA, sem o trecho: cita o assunto (ex.: ouvidoria, pedido de informação, lixo, barulho, Defesa Civil). Não cite "o trecho" nem o número do artigo.
3. A resposta tem até 3 frases, em português correto, simples, sem jargão jurídico.
4. A resposta nunca diz "o trecho" nem "não especificado". Se o trecho não permitir uma pergunta útil ao morador (ex.: regras só para servidores, empresas ou motoristas habilitados), devolva [].
5. Responda APENAS com JSON válido: [{{"pergunta": "...", "resposta": "..."}}]"""

PROMPT_CHAT = """Você cria diálogos de treino para um assistente público do estado de São Paulo.

TRECHO DO DOCUMENTO OFICIAL:
\"\"\"{trecho}\"\"\"

Escreva um diálogo de 2 trocas entre um morador e o assistente, usando SOMENTE informações do trecho.
Regras:
1. A segunda pergunta do morador deve depender da primeira resposta (ex.: "E se eles não responderem?", "E quanto tempo demora?"), com no máximo 12 palavras.
2. As respostas do assistente: até 3 frases, português correto e simples, sem inventar dados e sem dizer "o trecho".
3. Se o trecho não servir para um diálogo útil, devolva {{}}.
4. Responda APENAS com JSON válido: {{"pergunta1": "...", "resposta1": "...", "pergunta2": "...", "resposta2": "..."}}"""


def carregar_llm(nome="Qwen/Qwen2.5-3B-Instruct"):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(nome)
    modelo = AutoModelForCausalLM.from_pretrained(
        nome, dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto")
    return tok, modelo


def gerar_texto(llm, prompt, max_new_tokens=700, temperatura=0.3):
    tok, modelo = llm
    msgs = [{"role": "system", "content": "Você responde sempre em português do Brasil e em JSON válido."},
            {"role": "user", "content": prompt}]
    entrada = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    ids = tok(entrada, return_tensors="pt").to(modelo.device)
    saida = modelo.generate(**ids, max_new_tokens=max_new_tokens, do_sample=True,
                            temperature=temperatura, top_p=0.9)
    return tok.decode(saida[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)


def extrair_json(texto):
    m = re.search(r"[\[{].*[\]}]", texto, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _palavras_conteudo(t):
    return {w for w in re.findall(r"\w+", _sem_acento(t.lower())) if len(w) >= 4}


MOTIVOS = Counter()   # motivos de descarte da última montagem (diagnóstico)
RE_META = re.compile(r"\b(trecho|texto acima|no texto|n[ãa]o (?:[ée] )?especificad|n[ãa]o h[áa] informa|"
                     r"n[ãa]o informa|n[ãa]o consta|n[ãa]o (?:est[áa]|foi) (?:mencionad|indicad))", re.I)


def fiel_ao_trecho(resposta, trecho, minimo=0.6):
    """Filtro automático (heurístico): números e palavras da resposta devem estar no trecho."""
    if RE_META.search(resposta):
        return False
    nums = set(re.findall(r"\d+", resposta))
    if any(n not in trecho for n in nums):
        return False
    pc = _palavras_conteudo(resposta)
    if not pc:
        return False
    return len(pc & _palavras_conteudo(trecho)) / len(pc) >= minimo


def _ler_cache(caminho):
    c = {}
    p = Path(caminho)
    if p.exists():
        for linha in p.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                o = json.loads(linha)
                c[o["id"]] = o["bruto"]
    return c


def gerar_ate_alvo(trechos, prompt_modelo, cache_path, llm, montar_fn, alvo, lote=20, **kw):
    """Gera em lotes de `lote` trechos até haver `alvo` exemplos válidos (ou acabarem os trechos)."""
    limite = len(trechos) if llm is None else lote   # sem LLM: usa todo o cache salvo
    while True:
        saidas = gerar_com_cache(trechos, prompt_modelo, cache_path, llm, max_trechos=limite, **kw)
        itens, _ = montar_fn(trechos, saidas)
        print(f"{len(saidas)} trechos processados -> {len(itens)} exemplos válidos (alvo {alvo})")
        if len(itens) >= alvo or limite >= len(trechos) or llm is None:
            return saidas
        limite += lote


def _ordem_balanceada(trechos):
    """Intercala os documentos para que as fontes fiquem balanceadas (>= 3 documentos)."""
    por_doc = {}
    for t in trechos:
        por_doc.setdefault(t["fonte"], []).append(t)
    ordem, filas = [], [deque(v) for v in por_doc.values()]
    while any(filas):
        for f in filas:
            if f:
                ordem.append(f.popleft())
    return ordem


def gerar_com_cache(trechos, prompt_modelo, cache_path, llm=None, alvo=None, n=3,
                    max_trechos=None, **fmt):
    """Gera (ou lê do cache) a saída bruta do LLM para cada trecho."""
    cache = _ler_cache(cache_path)
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    ordem = _ordem_balanceada(trechos)[: max_trechos or len(trechos)]
    with open(cache_path, "a", encoding="utf-8") as f:
        for t in ordem:
            if t["id"] in cache:
                continue
            if llm is None:
                continue  # modo offline: usa só o que já está salvo
            bruto = gerar_texto(llm, prompt_modelo.format(trecho=t["text"], n=n, **fmt))
            cache[t["id"]] = bruto
            f.write(json.dumps({"id": t["id"], "bruto": bruto}, ensure_ascii=False) + "\n")
            f.flush()
    return {t["id"]: cache[t["id"]] for t in ordem if t["id"] in cache}


def _norm_chave_json(k):
    return re.sub(r"[^a-z0-9]", "", _sem_acento(str(k).lower()))


def _normalizar_chat(d):
    """Aceita variações de chaves (pergunta_1, Pergunta1...) e lista de turnos."""
    if isinstance(d, list) and len(d) >= 4 and all(isinstance(x, dict) for x in d):
        txt = [x.get("content") or x.get("texto") or "" for x in d[:4]]
        return dict(zip(("pergunta1", "resposta1", "pergunta2", "resposta2"), txt))
    if not isinstance(d, dict):
        return None
    mapa = {_norm_chave_json(k): v for k, v in d.items()}
    out = {k: mapa.get(k) for k in ("pergunta1", "resposta1", "pergunta2", "resposta2")}
    return out if all(isinstance(v, str) and v.strip() for v in out.values()) else None


def montar_qa(trechos, saidas, minimo_fidelidade=0.6):
    MOTIVOS.clear()
    por_id = {t["id"]: t for t in trechos}
    pares, descartados = [], 0
    for tid, bruto in saidas.items():
        dados = extrair_json(bruto)
        if not isinstance(dados, list):
            descartados += 1
            MOTIVOS["json_invalido"] += 1
            continue
        t = por_id[tid]
        for it in dados:
            if not isinstance(it, dict) or not it.get("pergunta") or not it.get("resposta"):
                descartados += 1
                MOTIVOS["campos_ausentes"] += 1
                continue
            if RE_META.search(it["resposta"]):
                descartados += 1
                MOTIVOS["resposta_meta"] += 1
                continue
            if not fiel_ao_trecho(it["resposta"], t["text"], minimo_fidelidade):
                descartados += 1
                MOTIVOS["infiel_ao_trecho"] += 1
                continue
            pares.append({"instruction": it["pergunta"].strip(), "input": "",
                          "output": it["resposta"].strip(), "trecho": t["text"],
                          "fonte": t["fonte"]})
    return pares, descartados


def montar_chat(trechos, saidas, system=SYSTEM_PROMPT, minimo_fidelidade=0.5):
    MOTIVOS.clear()
    por_id = {t["id"]: t for t in trechos}
    dialogos, descartados = [], 0
    for tid, bruto in saidas.items():
        t = por_id[tid]
        d = _normalizar_chat(extrair_json(bruto))
        if d is None:
            descartados += 1
            MOTIVOS["json_invalido_ou_chaves"] += 1
            continue
        if len(d["pergunta2"].split()) > 18:
            descartados += 1
            MOTIVOS["pergunta2_longa"] += 1
            continue
        if RE_META.search(d["resposta1"] + " " + d["resposta2"]):
            descartados += 1
            MOTIVOS["resposta_meta"] += 1
            continue
        if not (fiel_ao_trecho(d["resposta1"], t["text"], minimo_fidelidade)
                and fiel_ao_trecho(d["resposta2"], t["text"], minimo_fidelidade)):
            descartados += 1
            MOTIVOS["infiel_ao_trecho"] += 1
            continue
        dialogos.append({"messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": d["pergunta1"].strip()},
            {"role": "assistant", "content": d["resposta1"].strip()},
            {"role": "user", "content": d["pergunta2"].strip()},
            {"role": "assistant", "content": d["resposta2"].strip()}],
            "fonte": t["fonte"]})
    return dialogos, descartados


RELEVANTE_CTB = re.compile(
    r"(conserva|manuten[çc]|sinaliza|pavimento|buraco|obra|cal[çc]ada|via p[úu]blica|"
    r"respons[aá]vel|respondem|dano|ruído|ruido|polui|limpeza|res[íi]duo|lixo|"
    r"ilumina|calçamento|trânsito seguro|transito seguro)", re.I)


def filtrar_relevantes(trechos, doc_amplo="lei_9503_1997_ctb.html", regex=RELEVANTE_CTB):
    """Para a GERAÇÃO de Q&A/chat: do documento muito amplo (CTB) fica só o que toca o tema."""
    return [t for t in trechos if t["fonte"] != doc_amplo or regex.search(t["text"])]


def diagnosticar(saidas, trechos=None, n=3):
    """Mostra saídas brutas do LLM e, se possível, o trecho que as originou."""
    por_id = {t["id"]: t for t in (trechos or [])}
    for tid, bruto in list(saidas.items())[:n]:
        print(f"--- {tid} ---")
        if tid in por_id:
            print("TRECHO:", por_id[tid]["text"][:300].replace("\n", " "), "...")
        print("SAÍDA BRUTA:", bruto[:700], "\n")


# ----------------------------------------------------------------------------
# 9. E/S, ESTATÍSTICAS E REVISÃO
# ----------------------------------------------------------------------------

def salvar_jsonl(registros, caminho):
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def ler_jsonl(caminho):
    return [json.loads(l) for l in Path(caminho).read_text(encoding="utf-8").splitlines() if l.strip()]


def sha256_arquivo(caminho):
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


CATEGORIAS_RECUSA = {"urgencia", "fora_do_tema", "diagnostico", "orientacao_juridica", "encaminhamento"}

PALAVRAS_RECUSA = ("não posso", "não consigo", "fora do que", "não faz parte", "procure um",
                   "procure uma", "procure a defensoria", "ligue 192", "ligue 193", "ligue 199",
                   "ligue para o 19", "192", "193", "199")


def conta_recusas(dialogos):
    return sum(
        1 for d in dialogos
        if any(p in " ".join(m["content"] for m in d["messages"] if m["role"] == "assistant").lower()
               for p in PALAVRAS_RECUSA))


def estatisticas(nome, registros, texto_de, contar, duplicatas=0, recusas=None, amostra=5, semente=3):
    toks = [contar(texto_de(r)) for r in registros]
    est = {"corpus": nome, "exemplos": len(registros),
           "media_tokens": round(sum(toks) / len(toks), 1) if toks else 0,
           "min_tokens": min(toks) if toks else 0, "max_tokens": max(toks) if toks else 0,
           "duplicatas_removidas": duplicatas, "recusas_e_encaminhamentos": recusas}
    print(f"\n=== {nome} ===")
    for k, v in est.items():
        print(f"  {k}: {v}")
    rng = random.Random(semente)
    for r in rng.sample(registros, min(amostra, len(registros))):
        print("  --", texto_de(r)[:220].replace("\n", " "))
    return est


def exportar_revisao(corpora, caminho, fracao=0.2, semente=11):
    """Gera o revisao.csv (modelo) com >= 20% dos exemplos gerados por IA. Preencher à mão."""
    rng = random.Random(semente)
    linhas = []
    for arquivo, n in corpora.items():
        for i in sorted(rng.sample(range(1, n + 1), max(1, int(round(n * fracao))))):
            linhas.append({"arquivo": arquivo, "linha": i, "alterado": "", "comentario": "PENDENTE"})
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["arquivo", "linha", "alterado", "comentário"])
        w.writeheader()
        for l in linhas:
            w.writerow({"arquivo": l["arquivo"], "linha": l["linha"], "alterado": l["alterado"],
                        "comentário": l["comentario"]})
    return len(linhas)
