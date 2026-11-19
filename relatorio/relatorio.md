# Bairro em Dia · Fábrica de Corpus CitizenTech

**GS 2027 · Processamento de Linguagem Natural**
**Integrantes:**

| Nome | RM |
|---|---|
| Gabriel Tonelli Avelino dos Santos | 564705 |
| Marcelo Roberto Maso Junior | 562163 |
| Vinícius Adrian Siqueira de Oliveira | 564962 |

**Repositório:** https://github.com/Tonelli2003/GS-PLN

---

## 1. Problema e persona

**Persona:** morador de bairro urbano do estado de São Paulo, com pouca familiaridade com a burocracia municipal.

**Problema:** o morador vê buraco na rua, poste apagado, lixo acumulado ou barulho excessivo, mas não sabe a qual órgão recorrer, que informações fornecer nem como acompanhar o pedido. O relato se perde e o problema continua.

**Solução:** o app **Bairro em Dia** recebe o relato (local, descrição, foto ou áudio), organiza e classifica com IA e gera um protocolo que o morador e o gestor acompanham. Um **assistente** orienta o cidadão sobre como buscar atendimento. Este trabalho produz o corpus que ensina esse assistente a se comportar como um bom atendente do serviço público: tom simples e educado, orientação sobre o caminho do pedido, recusa de assuntos fora do tema, encaminhamento a profissionais e, nas urgências, 192 (SAMU), 193 (Bombeiros) ou 199 (Defesa Civil).

## 2. ODS apoiado

- **ODS 11, Cidades e Comunidades Sustentáveis:** bairros mais seguros e bem cuidados, com resposta a problemas de infraestrutura, resíduos e risco.
- **ODS 16, Instituições Eficazes, Responsáveis e Inclusivas (apoio):** acompanhamento por protocolo e direito de resposta do usuário de serviço público.

## 3. Fontes

Sete documentos oficiais, todos públicos, com foco no estado de São Paulo e na legislação que se aplica a ele. Total: **54.799 palavras**, mais de 3 vezes o mínimo de ~15 mil exigido. A ficha de atendimento fictícia serve só para demonstrar a anonimização e **não entra** nos corpus.

| Documento | Órgão | Publicação | Palavras | Trechos |
|---|---|---|---|---|
| Lei Estadual nº 10.294/1999 (defesa do usuário do serviço público de SP) | Assembleia Legislativa de SP | 20/04/1999 | 2.930 | 13 |
| Lei nº 13.460/2017 (direitos do usuário de serviços públicos) | Presidência da República | 26/06/2017 | 2.768 | 10 |
| Lei nº 12.527/2011 (Lei de Acesso à Informação) | Presidência da República | 18/11/2011 | 6.266 | 23 |
| Lei nº 12.305/2010 (Política Nacional de Resíduos Sólidos) | Presidência da República | 02/08/2010 | 9.470 | 37 |
| Lei nº 12.608/2012 (Proteção e Defesa Civil) | Presidência da República | 10/04/2012 | 6.810 | 26 |
| Lei nº 9.503/1997 (Código de Trânsito Brasileiro, texto compilado) | Presidência da República | 23/09/1997 | 22.668 | 87 |
| Decreto-Lei nº 3.688/1941 (Contravenções Penais) | Presidência da República | 03/10/1941 | 3.887 | 15 |
| **Total** | | | **54.799** | **211** |

Links de origem, data de publicação e data de consulta (16/11/2026) estão em `dados/manifesto_documentos.csv`. A data de vigência registrada em cada trecho é a de publicação da lei.

## 4. Informações estáveis × voláteis

| Estável (aprendida no treino) | Volátil (fica no RAG) |
|---|---|
| Tom de atendente: simples, educado e direto | Telefones e canais do município (ex.: 156) |
| Estrutura de um bom relato: local, descrição, foto/áudio, protocolo | Prazos de atendimento por órgão e carta de serviços |
| Direitos do usuário e existência de ouvidoria | Valores de multas e horários de coleta |
| Prazos legais estáveis: LAI (20 dias + 10; recurso em 10) e Lei 13.460 (30 dias, prorrogáveis uma vez) | Leis e decretos municipais |
| Quando recusar, encaminhar a profissional ou órgão e quando acionar 192, 193 ou 199 | Nomes de secretarias e contatos que mudam de gestão |

**Justificativa:** o treino ensina bem forma, tom e comportamento, e ensina mal fatos que mudam ou que precisam ser citados. Por isso os corpus ensinam o comportamento do atendente, e os fatos continuam vindo dos documentos por RAG. O `corpus_texto.jsonl`, com origem, seção e data em cada trecho, já é a base pronta para esse RAG. Como o tema se apoia em leis (regras estáveis), a única informação marcada como volátil é a que depende do município.

## 5. Decisões de limpeza e normalização

**Extração:** HTML (BeautifulSoup), PDF (pypdf), DOCX (python-docx), TXT e texto colado, todos aceitos. Cada trecho guarda arquivo, seção (capítulo ou seção da lei), data e link. As quebras de linha dentro dos parágrafos do HTML do Planalto são tratadas como espaço.

**Limpeza:** removidos cabeçalhos e rodapés repetidos, numeração de páginas, URLs, caracteres estranhos, **anotações legislativas** ("Redação dada pela…", "Vide…", "Incluído pela…"), **texto revogado** (tachado no Planalto) e os **blocos de assinatura** (nomes de autoridades). Palavras quebradas por hífen no fim da linha foram unidas.

**Normalização:** UTF-8, NFC e `ftfy`, aspas retas, espaços e quebras padronizados, `Art. 5o` corrigido para `Art. 5º`. Acentos, pontuação e maiúsculas foram **preservados**. **Não** foram removidas stop words nem feito stemming, porque o modelo precisa do texto natural para aprender a escrever.

**Segmentação:** trechos de 256 a 512 tokens pelo tokenizador do `Qwen/Qwen2.5-0.5B-Instruct`, sem cortar frases. Resultado: 211 trechos, **0 fora da faixa** (259 a 503 tokens, média 465,1). O Código de Trânsito foi filtrado já no texto para manter só o conteúdo ligado ao tema (87 trechos, antes 149).

## 6. Anonimização e LGPD

**Técnica:** expressões regulares para CPF, e-mail, telefone, RG e endereço, e NER (spaCy `pt_core_news_lg`) para nomes de pessoas, mais regras por rótulo ("Nome do solicitante:", "a moradora…", "o atendente…"). Cada dado vira um marcador do seu tipo (`[CPF]`, `[EMAIL]`, `[TELEFONE]`, `[NOME]`, `[RG]`, `[ENDERECO]`). **Nenhuma tabela de correspondência é guardada**: a troca é irreversível, então o dado fica anonimizado, e não apenas pseudonimizado.

**Exceções (não mascarados):** nomes de leis (ex.: Lei Maria da Penha), instituições (Fiocruz, Defesa Civil, SAMU, Corpo de Bombeiros, Defensoria Pública, Ministério Público, Poder Executivo, Tribunal) e termos institucionais (Estado, Município, Código, Estatuto, Constituição etc.).

**Exemplo antes e depois (ficha fictícia):**

| Antes | Depois |
|---|---|
| Nome do solicitante: Carlos Eduardo Figueiredo Santos | Nome do solicitante: [NOME] |
| CPF: 123.456.789-09 | CPF: [CPF] |
| RG: 12.345.678-9 | RG: [RG] |
| E-mail: carlos.santos@exemplo.com.br | E-mail: [EMAIL] |
| Telefone: (11) 91234-5678 | Telefone: [TELEFONE] |
| Rua das Acácias, 120, Jardim Primavera, Cotia/SP | [ENDERECO], Jardim Primavera, Cotia/SP |
| A moradora Maria Aparecida de Souza avisou… | A moradora [NOME] avisou… |
| …seguem a Lei Maria da Penha. Material da Fiocruz… | **(mantidos)** |
| CPF da moradora é 98765432100, celular 11 98877-6655 | CPF da moradora é [CPF], celular [TELEFONE] |

Dados trocados na ficha: 2 e-mails, 2 CPFs, 1 RG, 3 telefones, 1 endereço e 4 nomes.

**Documentos oficiais:** a anonimização mascarou 4 ocorrências de `[NOME]` nos textos de lei, todas falsos positivos do NER (por exemplo, o título "Dolo e culpa" do art. 3º das Contravenções Penais virou `[NOME] e culpa`). Como documentos oficiais raramente trazem dados pessoais, a conferência manual mostrou que nenhuma era dado real nos textos de lei. Documentos oficiais raramente trazem dados pessoais, então essas ocorrências devem ser conferidas: [descrever o resultado da conferência, indicando quantas eram falsos positivos do NER].

**Cuidados com a LGPD:**
- Nenhum dado pessoal real entra nos corpus. Há uma **varredura automática final** (CPF, RG, e-mail, telefone) nos três corpus de treino, que passou sem achados.
- A ficha fictícia, com dados sintéticos, não entra nos corpus.
- Dados de saúde são sensíveis (LGPD, art. 5º, II). O assistente é treinado para **não diagnosticar** nem indicar remédio, e para encaminhar a um profissional ou ao 192.
- Os documentos são todos públicos e oficiais, com origem e data registradas.

## 7. Corpus gerados e estatísticas

| Corpus | Exemplos | Média de tokens | Faixa de tokens | Duplicatas removidas | Recusas/encaminhamentos |
|---|---|---|---|---|---|
| Texto puro | 211 | 465,1 | 259–503 | 0 | – |
| Perguntas e respostas | 135 gerados; **127 após a revisão** | 50,5 | 24–121 | 0 | 0 |
| Conversacional | **41** (nenhum removido na revisão) | 94,6 | 60–141 | 0 | 18 |
| Teste | 24 | 15,6 | 8–25 | – | – |

**Perguntas e respostas:** 135 pares gerados (127 após a revisão humana), de 7 documentos, em formato Alpaca com o campo `trecho` copiando a passagem de apoio. Gerados com `Qwen/Qwen2.5-3B-Instruct` (modelo aberto, sem API), a partir de 211 dos 273 trechos. Do Código de Trânsito, que é muito amplo, só entraram trechos ligados ao tema (conservação de vias, responsabilidade por dano, resíduos, ruído). Foram descartadas 98 saídas pelo filtro automático (89 infiéis ao trecho, 7 respostas do tipo "não especificado" e 2 JSON inválidos).

**Conversacional:** 41 diálogos (a segunda pergunta depende da primeira): **30 escritos à mão** (`dados/seeds/chat_seed.jsonl`: recusas, encaminhamentos, diagnóstico, orientação jurídica, urgências 192/193/199 e orientação baseada nas leis) e **11 gerados** pelo modelo. O modelo de 3B rendeu pouco no chat: muitas saídas foram descartadas por infidelidade ao trecho ou JSON inválido, por isso a base é escrita à mão. São **18 recusas e encaminhamentos**, acima do mínimo de 10, cobrindo fora do tema, diagnóstico, orientação jurídica individual e urgência.

**Teste:** 24 perguntas escritas à mão **antes** de gerar qualquer corpus de treino e não alteradas depois (SHA-256 `0d9d07a4dab60c2b…`): 13 diretas, 4 fora do tema, 4 de urgência e 3 pegadinhas.

**Língua real:** perguntas do usuário com erros de digitação, caixa alta, abreviações e informalidade: **35%** no Q&A e **46%** no chat, após a revisão e **38%** no teste (mínimo exigido: 30%). As respostas do assistente seguem sempre em português correto e acessível.

**Vazamento do teste para o treino:** 0 perguntas do teste apareceram nos corpus de treino (verificação por texto normalizado e similaridade de palavras).

**Duplicatas:** removidas as exatas após a normalização e as quase-duplicatas por similaridade de cosseno entre embeddings (limiar 0,95). Total removido: 0 no texto, 1 no Q&A e 0 no chat.

## 8. Conferência de fidelidade e revisão humana

**Filtro automático:** cada resposta gerada só é aceita se os números e a maior parte das palavras dela aparecerem no trecho de apoio, e se não for do tipo "não especificado no trecho". É um filtro heurístico, e **não substitui a revisão humana**: ele deixa passar pares com palavras do trecho mas sentido errado.

**Revisão humana:** `revisao.csv` registra a decisão do grupo para cada par (`aplicar_revisao.py` aplica as decisões e gera os corpus `*_revisado.jsonl`). Foram revisados 35 pares gerados por IA (27 de Q&A e 8 de chat, 20% de cada corpus), comparando cada um com o trecho de origem. **Q&A (27):** 8 mantidos, 11 corrigidos e 8 removidos, o que deixa 127 pares. **Chat (8):** os 8 foram mantidos, e o corpus continua com 41 diálogos. Os problemas encontrados foram resposta que contradiz o artigo (prazo de 30 dias da ouvidoria trocado por 20), regra de um caso específico generalizada, pergunta sem resposta no trecho e perguntas fora do tema do app.

**Conferência de uma amostra de 20 pares** (`amostra_fidelidade_20.csv`): **17 de 20 [conferir com o grupo]** estavam fiéis ao trecho que os sustenta.

**Modelo e prompt:** `Qwen/Qwen2.5-3B-Instruct`, temperatura 0,3, 3 pares por trecho. Os prompts completos estão em `PROMPT_QA` e `PROMPT_CHAT` no `corpus_factory.py`. Regras principais: usar **somente** informações do trecho, perguntas que façam sentido sozinhas, respostas de até 3 frases em português simples e correto, sem jargão jurídico, e devolver lista vazia se o trecho não servir ao morador.

## 9. Dificuldades encontradas

- **Extração de HTML:** o HTML do Planalto quebra linhas dentro dos parágrafos, o que gerava trechos começando no meio da frase e anotações legislativas cortadas. Corrigido tratando a quebra como espaço.
- **Código de Trânsito dominava o corpus:** 149 dos 273 trechos (55%) na primeira versão vêm dele, com muito conteúdo sobre CNH e crimes de trânsito, fora do tema do app. A geração de Q&A e chat passou a usar só os trechos relevantes ao tema.
- **Rendimento do modelo pequeno:** o modelo de 3B respeita pouco o formato JSON e inventa conteúdo nos diálogos (primeira rodada: só 27 diálogos válidos, abaixo do mínimo de 30). Solução: diálogos escritos à mão como base, filtros e prompts melhores e revisão humana dos gerados.
- **Qualidade do Q&A gerado:** a revisão encontrou pares com pergunta e resposta incompatíveis ou fora do tema do app. Exemplo: o par da linha 120 respondia "como recorrer se meu pedido de informação for negado" com a regra do art. 17 da LAI, que trata só de pedido de desclassificação negado em órgão federal. A pergunta e a resposta foram reescritas para esse caso.
- **Falsos positivos do NER:** o NER marcou como nome de pessoa títulos de seção das leis (ex.: "Dolo e culpa"). Foram 4 ocorrências no texto final, conferidas à mão; a lista de termos institucionais e as regras do módulo foram estendidas para evitar casos assim.
- **Infraestrutura:** o modelo de 3B (~6 GB) demorou a carregar no Colab. O cache em arquivo das saídas geradas permite retomar a geração e rodar o notebook sem GPU e sem chave de API.

**Trabalhos futuros:** treinar um adapter LoRA com o `corpus_chat.jsonl` e comparar, no `corpus_teste.jsonl`, o modelo base com prompt curto, o modelo base com o melhor prompt e o modelo ajustado (bônus do enunciado).
