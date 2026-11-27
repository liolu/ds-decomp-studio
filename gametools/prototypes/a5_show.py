"""Hunt agent a5 helper: print the asm lines and m2c draft of several functions
compactly (uses workbench.py info). Usage: python a5_show.py NAME [NAME ...]
"""
import json
import subprocess
import sys

G = "../../studio/gametools"


def main():
    for name in sys.argv[1:]:
        out = subprocess.run([sys.executable, G + "/workbench.py", "info", name],
                             capture_output=True, text=True).stdout
        d = json.loads(out[out.find("{"):])
        print("=====", name, d.get("size"), d.get("profiles", [""])[0])
        for line in d.get("lines", []):
            print("   ", line)
        print("--- draft:")
        print(d.get("draft", ""))


if __name__ == "__main__":
    main()
