# Bairro em Dia · Fábrica de Corpus (GS 2027 · CitizenTech)

Ferramenta em Python que transforma documentos públicos do **estado de São Paulo** em corpus para ajustar um modelo de linguagem pequeno (SLM) que será o **assistente do app Bairro em Dia**: orienta moradores sobre como relatar buraco, iluminação com defeito, lixo acumulado e barulho, e a quem recorrer.

**Integrantes (nomes completos):**

| Nome | RM |
|---|---|
| Gabriel Tonelli Avelino dos Santos | 564705 |
| Marcelo Roberto Maso Junior | 562163 |
| Vinícius Adrian Siqueira de Oliveira | 564962 |


## Como executar

### Opção 1 – Google Colab (recomendada)
1. Repositório: https://github.com/Tonelli2003/GS-PLN (ou envie os arquivos ao Colab).
2. Abra `gs_fabrica_corpus_bairro_em_dia.ipynb` no Colab e escolha **GPU (T4)**.
3. Execute as células em ordem. Não há chave de API.
4. Os arquivos saem em `saida/`.

Sem GPU, é possível reproduzir os corpus usando o cache de geração: mantenha `saida/geracao/raw_qa.jsonl` e `raw_chat.jsonl` e defina `GERAR_COM_LLM = False`.

### Opção 2 – Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m spacy download pt_core_news_lg
jupyter notebook gs_fabrica_corpus_bairro_em_dia.ipynb
```

## Bibliotecas
`pypdf`, `python-docx`, `beautifulsoup4`, `ftfy`, `spaCy` (`pt_core_news_lg`), `transformers` (tokenizador `Qwen/Qwen2.5-0.5B-Instruct`; geração com `Qwen/Qwen2.5-3B-Instruct`), `sentence-transformers` (quase-duplicatas), `gradio` (interface), `pandas`.

## Estrutura
| Caminho | Conteúdo |
|---|---|
| `gs_fabrica_corpus_bairro_em_dia.ipynb` | Notebook com todas as etapas e a interface Gradio |
| `corpus_factory.py` | Funções do pipeline (ingestão, limpeza, anonimização, segmentação, geração, qualidade) |
| `dados/manifesto_documentos.csv` | Metadados: arquivo, título, órgão, link, data, tipo da data |
| `dados/entrada/` | Documentos de entrada (baixados pelo notebook) e a **ficha fictícia** de teste de anonimização |
| `dados/seeds/corpus_teste.jsonl` | Conjunto de teste, escrito à mão **antes** dos corpus de treino |
| `dados/seeds/chat_seed.jsonl` | 30 diálogos escritos à mão (recusa, encaminhamento, urgência e orientação com base nas leis) |
| `saida/` | `corpus_texto.jsonl`, `corpus_qa.jsonl`, `corpus_chat.jsonl`, `corpus_teste.jsonl`, `revisao.csv`, `estatisticas.json`, `geracao/` |
| `relatorio/` | Rascunho do relatório |

## Documentos usados (fontes oficiais, estado de SP e legislação aplicável)
Lei Estadual 10.294/1999 (SP) · Lei 13.460/2017 · Lei 12.527/2011 (LAI) · Lei 12.305/2010 (PNRS) · Lei 12.608/2012 (Defesa Civil) · Lei 9.503/1997 (CTB) · Decreto-Lei 3.688/1941 (Contravenções Penais). Links e datas em `dados/manifesto_documentos.csv`. **Confira cada link antes da entrega** (coluna `link_verificado`).

## Auditoria e entrega offline
- A seção **8b** do notebook confere contagem de linhas, codificação, falsos positivos do NER, dados pessoais residuais (CPF, RG, telefone, e-mail, endereço e nomes) e a fatia do Código de Trânsito.
- A seção **11** baixa `saida/` (corpus, `revisao.csv`, `estatisticas.json`, `amostra_fidelidade_20.csv` e o cache `geracao/`). Com o cache no repositório, `GERAR_COM_LLM = False` reproduz tudo **sem GPU e sem API**.
- `FILTRAR_CTB_NO_TEXTO = True` mantém do Código de Trânsito só os trechos ligados ao tema.

## Decisões importantes
- **Forma se treina, fato se consulta:** o corpus ensina tom, formato e quando recusar/encaminhar. Telefones, prazos por órgão, multas e leis municipais ficam para o RAG.
- **Anonimização irreversível** (sem tabela de correspondência), com exceções para leis e instituições.
- **Sem stop words nem stemming.**
- **Fidelidade:** cada par de Q&A guarda o `trecho` de apoio; filtro automático + revisão humana (`revisao.csv`).
- Campos extras nos JSONL (`id`, `titulo`, `orgao`, `link` no texto puro; `lingua_real` no teste) existem para rastreabilidade e podem ser ignorados.

## Revisão humana (passo a passo)
1. Preencha `decisao_final` (manter, corrigir, remover ou aceito) em todas as linhas de `revisao/revisao_sugerida.csv`.
2. Com a pasta `saida/` do Colab no projeto, rode: `python aplicar_revisao.py --saida saida --csv revisao/revisao_sugerida.csv`
3. Saídas: `saida/corpus_qa_revisado.jsonl`, `saida/corpus_chat_revisado.jsonl` e `saida/revisao.csv`.
