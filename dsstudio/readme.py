"""The table of every game in the Studio's README.md (`python studio.py readme`): progress, ROM state, repo link.

Written between <!-- games:start --> and <!-- games:end --> (the section is added after the introduction when
missing). Progress comes from the projects themselves (delinks.txt + symbols.txt, like the Games tab).
"""
import datetime
import re

from . import config, games

START, END = "<!-- games:start -->", "<!-- games:end -->"


def bar(percent: float, width: int = 10) -> str:
    full = round(percent / 100 * width)
    return "`" + "█" * full + "░" * (width - full) + "`"


def table() -> str:
    rows = [g.info() for g in games.all_games()]
    rows.sort(key=lambda r: (-r["pct_code"], r["title"]))
    total_fn = sum(r["functions"] for r in rows)
    total_ok = sum(r["matched"] for r in rows)
    published = sum(1 for r in rows if r["remote"])
    lines = [START,
             f"{len(rows)} jeux, {published} publiés · {total_ok}/{total_fn} fonctions matchées au total "
             f"· mis à jour le {datetime.date.today().isoformat()} par le bouton « Publier l'avancement sur GitHub » "
             f"(onglet Jeux) ou `python studio.py progress`",
             "",
             "| Jeu | Version | Studio | Code matché | Fonctions | Sous les règles | ROM | Dépôt |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        remote = r["remote"] or ""
        url = re.sub(r"\.git$", "", remote)
        repo = f"[{url.rsplit('/', 1)[-1]}]({url})" if url.startswith("http") else "local (pas encore de match)"
        rom = "✅" if r["rom"]["ok"] else "❌ " + r["rom"]["note"]
        t = r.get("rules") or {}
        rules = f"{t['rules_matched']}/{t['functions'] - t['original_asm']}" if t else "—"
        lines.append(f"| {r['title']} | {r['version']} {r['code']} | {r['studio']} | {bar(r['pct_code'])} "
                     f"{r['pct_code']:.2f}% | {r['matched']}/{r['functions']} | {rules} | {rom} | {repo} |")
    lines += ["",
              "*Code matché : part du code des fonctions (ARM9, ITCM, DTCM, overlays) qui recompile à l'octet près. "
              "Sous les règles : fonctions identiques à l'octet près ET dont la source passe toutes les règles [match] "
              "de [CODE-RULES.md](CODE-RULES.md) (les autres sont MATCH-PENDING ; — : jamais compté, "
              "`python studio.py rules <jeu>`). ROM ✅ : la ROM se reconstruit identique à l'originale.*",
              END]
    return "\n".join(lines)


def update() -> str:
    p = config.STUDIO / "README.md"
    text = p.read_text(encoding="utf-8")
    block = table()
    if START in text:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _m: block, text, flags=re.S)
    else:
        m = re.search(r"^## ", text, re.M)
        at = m.start() if m else len(text)
        new = text[:at].rstrip("\n") + "\n\n## Avancement des jeux\n\n" + block + "\n\n" + text[at:]
    p.write_text(new, encoding="utf-8", newline="\n")
    return block
