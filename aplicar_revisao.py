# -*- coding: utf-8 -*-
"""
aplicar_revisao.py - aplica as DECISÕES HUMANAS da revisão aos corpus gerados pelo notebook.

Coloque este arquivo na raiz do projeto (junto de corpus_factory.py) e rode:
    python aplicar_revisao.py --saida saida --csv revisao/revisao_sugerida.csv

Antes, o grupo preenche `decisao_final` em TODAS as linhas do CSV com:
    manter | corrigir | remover | aceito   ("aceito" = concordo com `veredito_sugerido`)
Linhas em branco são recusadas: a decisão é sempre de uma pessoa.

Gera em saida/: corpus_qa_revisado.jsonl, corpus_chat_revisado.jsonl e revisao.csv
(colunas: arquivo, linha, alterado, comentário). `linha` = linha do arquivo ANTES da revisão.
"""
import argparse, csv, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import corpus_factory as cf  # noqa: E402


def ler(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="saida")
    ap.add_argument("--csv", default="revisao/revisao_sugerida.csv")
    a = ap.parse_args()
    saida = Path(a.saida)

    with open(a.csv, encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f))
    vazias = [(r["arquivo"], r["linha"]) for r in linhas if not r["decisao_final"].strip()]
    if vazias:
        sys.exit(f"ERRO: {len(vazias)} linhas sem `decisao_final` (ex.: {vazias[:3]}).")

    qa, chat = ler(saida / "corpus_qa.jsonl"), ler(saida / "corpus_chat.jsonl")
    remover = {"corpus_qa.jsonl": set(), "corpus_chat.jsonl": set()}
    rev = []
    for r in linhas:
        arq, ln = r["arquivo"], int(r["linha"])
        dec = r["decisao_final"].strip().lower()
        if dec == "aceito":
            dec = r["veredito_sugerido"]
        if dec not in ("manter", "corrigir", "remover"):
            sys.exit(f"ERRO: decisão inválida {dec!r} em {arq} linha {ln}")
        if arq == "corpus_qa.jsonl":
            d = qa[ln - 1]
            if d["instruction"] != r["pergunta_original"]:
                sys.exit(f"ERRO: a linha {ln} do corpus_qa.jsonl não é a revisada. "
                         "Use o mesmo saida/ que gerou o CSV.")
            if dec == "corrigir":
                d["instruction"] = r["pergunta_corrigida_sugerida"].strip() or d["instruction"]
                d["output"] = r["resposta_corrigida_sugerida"].strip() or d["output"]
        else:
            if next(m["content"] for m in chat[ln - 1]["messages"] if m["role"] == "user") != r["pergunta_original"]:
                sys.exit(f"ERRO: a linha {ln} do corpus_chat.jsonl não é a revisada.")
            if dec == "corrigir":
                sys.exit("ERRO: no chat só há manter/remover.")
        if dec == "remover":
            remover[arq].add(ln)
        rot = {"manter": "mantido sem alteração", "corrigir": "corrigido", "remover": "removido"}[dec]
        rev.append({"arquivo": arq, "linha": ln, "alterado": "não" if dec == "manter" else "sim",
                    "comentário": f"{rot}: {r['motivo']}"})

    qa_f = [d for i, d in enumerate(qa, 1) if i not in remover["corpus_qa.jsonl"]]
    chat_f = [d for i, d in enumerate(chat, 1) if i not in remover["corpus_chat.jsonl"]]
    qa_f, dup = cf.deduplicar(qa_f, lambda r: r["instruction"] + " " + r["output"])
    cf.salvar_jsonl(qa_f, saida / "corpus_qa_revisado.jsonl")
    cf.salvar_jsonl(chat_f, saida / "corpus_chat_revisado.jsonl")
    with open(saida / "revisao.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["arquivo", "linha", "alterado", "comentário"])
        w.writeheader()
        w.writerows(rev)

    n_qa = sum(r["arquivo"] == "corpus_qa.jsonl" for r in rev)
    print(f"Q&A:  {len(qa)} -> {len(qa_f)} (removidos {len(remover['corpus_qa.jsonl'])}, duplicatas {dup}); "
          f"revisados {n_qa} ({n_qa / len(qa):.0%})")
    print(f"Chat: {len(chat)} -> {len(chat_f)} (removidos {len(remover['corpus_chat.jsonl'])})")
    us = [d["instruction"] for d in qa_f]
    uc = [m["content"] for d in chat_f for m in d["messages"] if m["role"] == "user"]
    print(f"Língua real: Q&A {sum(map(cf.eh_lingua_real, us)) / len(us):.0%} | "
          f"chat {sum(map(cf.eh_lingua_real, uc)) / len(uc):.0%} (mínimo 30%)")
    if len(qa_f) < 100 or len(chat_f) < 30:
        print("ATENÇÃO: abaixo do mínimo (Q&A >= 100, chat >= 30).")


if __name__ == "__main__":
    main()
