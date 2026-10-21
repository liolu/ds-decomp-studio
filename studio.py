#!/usr/bin/env python3
"""DS Decomp Studio: Nintendo DS decompilation projects, blocks of 50 functions, a shared work queue.

    python studio.py                          open the web app (http://127.0.0.1:8765)
    python studio.py games                    list the games and their progress
    python studio.py blocks <game> [--level N] [--free]
    python studio.py claim <game> [<block>|next] [--level N] --who NAME [--kind human|claude|qwen|auto]
    python studio.py brief <game> <block>     work sheet for a person or an AI (markdown)
    python studio.py touch <game> <block> [--note TEXT]   still working on it
    python studio.py done <game> <block>      finished (moved to .studio/finished/)
    python studio.py release <game> <block>   give it back to the queue
    python studio.py rebuild <game>           recompute the blocks (claimed blocks are kept)
    python studio.py queue                    who works on what, every game
    python studio.py readme                  table of every game (progress, ROM, repo) in README.md
    python studio.py bytematch <game> [--token bm_...]   ByteMatch: save the upload token / upload the report
    python studio.py progress [--game G] [--no-push]   progress in the README of every published game + Studio, pushed
    python studio.py sync-tools [<game>] [--no-push]  latest tools of rayman-rr (auto_match...) into one or every game
    python studio.py publish <game> [--private] [--yes]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsstudio import blocks, brief, config, difficulty, games, projects  # noqa: E402


def out(obj):
    if isinstance(obj, dict) and obj.get("error"):
        print("ERREUR :", obj["error"])
        sys.exit(1)
    print(json.dumps(obj, indent=1, ensure_ascii=False) if not isinstance(obj, str) else obj)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve"); s.add_argument("--no-browser", action="store_true")
    sub.add_parser("games")
    sub.add_parser("queue")
    s = sub.add_parser("blocks"); s.add_argument("game"); s.add_argument("--level", type=int); s.add_argument("--free", action="store_true")
    s = sub.add_parser("claim"); s.add_argument("game"); s.add_argument("block", nargs="?", default="next")
    s.add_argument("--level", type=int); s.add_argument("--who"); s.add_argument("--kind", default="human", choices=list(blocks.KINDS))
    s.add_argument("--note", default="")
    s = sub.add_parser("brief"); s.add_argument("game"); s.add_argument("block")
    s = sub.add_parser("touch"); s.add_argument("game"); s.add_argument("block"); s.add_argument("--note")
    s = sub.add_parser("done"); s.add_argument("game"); s.add_argument("block"); s.add_argument("--who")
    s = sub.add_parser("release"); s.add_argument("game"); s.add_argument("block"); s.add_argument("--who")
    s = sub.add_parser("rebuild"); s.add_argument("game")
    s = sub.add_parser("sync-tools"); s.add_argument("game", nargs="?"); s.add_argument("--no-progress", action="store_true", help="do not update README/ByteMatch afterwards")
    s.add_argument("--no-push", action="store_true", help="commit in each game but do not push")
    sub.add_parser("readme", help="update the table of every game in README.md")
    s = sub.add_parser("progress", help="progress of every published game in its README, then the Studio's table, pushed")
    s.add_argument("--game", default="")
    s.add_argument("--no-push", action="store_true")
    s = sub.add_parser("bytematch", help="ByteMatch: remember a game's upload token (--token), else upload its report now")
    s.add_argument("game"); s.add_argument("--token", default="")
    s = sub.add_parser("publish"); s.add_argument("game"); s.add_argument("--private", action="store_true")
    s.add_argument("--yes", action="store_true")
    sub.add_parser("mcp-config", help="the command that gives Claude Code (or any MCP client) the studio's tools")
    a = ap.parse_args()

    if a.cmd in (None, "serve"):
        from dsstudio import server
        server.serve(open_browser=not getattr(a, "no_browser", False))
    elif a.cmd == "games":
        for g in games.all_games():
            i = g.info()
            rom = "ROM OK" if i["rom"]["ok"] else "ROM KO"
            print(f"{g.id:42} {i['matched']:5}/{i['functions']:<5} {i['pct_code']:6.2f}%  {rom:6}  {i['remote'] or '(local)'}")
    elif a.cmd == "queue":
        for c in blocks.queue_overview():
            print(f"{c['game']:30} {c['block']:10} {c['who']:15} {c['kind']:7} {'EXPIRE' if c['expired'] else ''} {c.get('note', '')}")
    elif a.cmd == "blocks":
        for b in blocks.view(games.get(a.game)):
            if (a.level is None or b["level"] == a.level) and (not a.free or b["state"] in ("free", "expired")):
                who = b["claim"]["who"] if b["claim"] else ""
                print(f"{b['id']:10} {difficulty.LEVELS[b['level']]['label']:11} {b['state']:8} "
                      f"{b['left']:3}/{b['count']:<3} left {b['left_bytes']:6} bytes  {who}")
    elif a.cmd == "claim":
        out(blocks.claim(games.get(a.game), a.block, a.who, a.kind, a.level, a.note))
    elif a.cmd == "brief":
        print(brief.brief(games.get(a.game), a.block))
    elif a.cmd == "touch":
        out(blocks.touch(games.get(a.game), a.block, note=a.note))
    elif a.cmd == "done":
        out(blocks.release(games.get(a.game), a.block, a.who, finished_=True))
    elif a.cmd == "release":
        out(blocks.release(games.get(a.game), a.block, a.who))
    elif a.cmd == "rebuild":
        d = blocks.rebuild(games.get(a.game))
        print(f"{len(d['blocks'])} blocs (generation {d['generation']})")
    elif a.cmd == "sync-tools":
        from dsstudio import toolsync
        targets = [games.get(a.game)] if a.game else [g for g in games.all_games() if g.ready]
        for g in targets:
            r = toolsync.sync(g, push=not a.no_push)
            print(f"{g.id}: " + (r.get("error") or (", ".join(r["changed"]) + " mis a jour" if r["changed"] else "a jour"))
                  + (f" ({r['warning']})" if r.get("warning") else ""))
        if not a.no_progress:  # update protocol: README progress + ByteMatch report follow every tool update
            from dsstudio import progress
            for g in targets:
                if g.remote():
                    progress.run(g.id, push=not a.no_push)
    elif a.cmd == "progress":
        from dsstudio import progress
        progress.run(a.game, push=not a.no_push)
    elif a.cmd == "readme":
        from dsstudio import readme
        readme.update()
        print("README.md: table of every game updated")
    elif a.cmd == "bytematch":
        from dsstudio import bytematch
        g = games.get(a.game)
        if a.token:
            print(f"jeton ByteMatch enregistre pour {bytematch.set_token(g, a.token)} (data/bytematch.json)")
        else:
            bytematch.upload(g)
    elif a.cmd == "publish":
        g = games.get(a.game)
        if not a.yes:
            bad = projects.unsafe_files(g)
            print(f"{g.id} -> github {'prive' if a.private else 'PUBLIC'}; fichiers interdits : {bad or 'aucun'}")
            if input("Continuer ? [o/N] ").strip().lower() not in ("o", "oui", "y"):
                return
        out(projects.publish(a.game, public=not a.private))
    elif a.cmd == "mcp-config":
        from dsstudio import gameenv
        server = Path(__file__).resolve().parent / "workers" / "mcp_server.py"
        print(f'claude mcp add --scope user ds-studio -- "{gameenv.PYTHON}" "{server}"')
        print(json.dumps({"mcpServers": {"ds-studio": {"command": str(gameenv.PYTHON), "args": [str(server)]}}},
                         indent=2))


if __name__ == "__main__":
    main()
