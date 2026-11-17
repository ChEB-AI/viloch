"""``viloch`` command line.

    viloch explain-rule DEF.lp [-o rule.png]
    viloch explain-molecule DEF.lp --smiles "CC(=O)O" [-o why.png]
    viloch explain-molecule DEF.lp --batch molecules.tsv --out-dir out/
    viloch convert DEF.lp --to model > model.json
    viloch serve --port 8000

``DEF.lp`` is a definition: the rule plus the auxiliary predicates it defines (see
:mod:`viloch.definition`). Auxiliary predicates it only uses are read from ``--library``.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

from viloch.definition import DEFAULT_TARGET


def _add_definition_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "definition", help="definition file (rule + aux predicates), or - for stdin"
    )
    p.add_argument(
        "--target", help="head predicate of the main rule (default: inferred)"
    )
    p.add_argument(
        "--library",
        help="aux rule library directory (<dir>/programs/<name>.pl) for aux_* "
        "predicates the definition uses but does not define",
    )
    names = p.add_mutually_exclusive_group()
    names.add_argument(
        "--chebi-graph", help="pickled ChEBI graph, for class and parent names"
    )
    names.add_argument("--class-name", help="name of the class the rule defines")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="viloch", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "explain-rule", help="global explanation: what the rule asks for"
    )
    _add_definition_args(p)
    p.add_argument("-o", "--output", help="PNG file for the picture")

    p = sub.add_parser(
        "explain-molecule",
        help="local explanation: why the rule accepts a molecule or not",
    )
    _add_definition_args(p)
    mol = p.add_mutually_exclusive_group(required=True)
    mol.add_argument("--smiles", help="SMILES or InChI")
    mol.add_argument("--molfile", help="file with a SMILES, InChI or molblock")
    mol.add_argument(
        "--batch",
        help="TSV/CSV of molecules: columns 'name' and 'smiles' (or the first two)",
    )
    p.add_argument("--name", help="molecule name for the title")
    p.add_argument("-o", "--output", help="PNG file for the picture (single molecule)")
    p.add_argument("--out-dir", help="directory for one PNG per molecule (--batch)")

    p = sub.add_parser(
        "convert", help="convert between ASP text and the editor model (JSON)"
    )
    p.add_argument("input", help="ASP definition or model JSON file, or - for stdin")
    p.add_argument("--to", choices=["model", "asp"], required=True)
    p.add_argument(
        "--target", default=None, help="head predicate (default: inferred / concept)"
    )

    p = sub.add_parser("serve", help="the standalone ASP <-> block editor page")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--library", help="aux rule library directory")
    p.add_argument(
        "--target", default=DEFAULT_TARGET, help="head predicate of edited rules"
    )
    return parser


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _definition(args):
    from viloch.api import as_definition

    return as_definition(_read(args.definition), args.target)


def _names(args) -> dict:
    from viloch.api import load_chebi_graph

    return {
        "chebi_graph": load_chebi_graph(args.chebi_graph),
        "class_name": args.class_name,
    }


def _save(image, path: str | None) -> str | None:
    if not path:
        return None
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    image.save(path)
    return path


def _emit(args, record: dict) -> None:
    if args.json:
        print(json.dumps(record, ensure_ascii=False))
        return
    prefix = ""
    if record.get("molecule"):
        verdict = "accepted" if record["fires"] else "rejected"
        prefix = f"{record['molecule']}: {verdict}. "
    print(prefix + record["text"])
    if record.get("image"):
        print(f"  picture: {record['image']}", file=sys.stderr)


def cmd_explain_rule(args) -> int:
    from viloch.api import explain_rule

    expl = explain_rule(_definition(args), library_dir=args.library, **_names(args))
    _emit(args, {"text": expl.text, "image": _save(expl.image, args.output)})
    return 0


def _batch(path: str) -> list[tuple[str, str]]:
    text = _read(path)
    dialect = "excel-tab" if "\t" in text.splitlines()[0] else "excel"
    rows = list(csv.reader(text.splitlines(), dialect=dialect))
    header = [h.strip().lower() for h in rows[0]]
    if "smiles" in header:
        si = header.index("smiles")
        ni = header.index("name") if "name" in header else None
        rows = rows[1:]
    else:
        ni, si = (0, 1) if len(rows[0]) > 1 else (None, 0)
    out = []
    for i, r in enumerate(rows, 1):
        if r and r[si].strip():
            out.append(
                (r[ni].strip() if ni is not None else f"molecule_{i}", r[si].strip())
            )
    return out


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "molecule"


def cmd_explain_molecule(args) -> int:
    from viloch.api import explain_molecule, prepare

    defn = prepare(_definition(args), args.library)  # resolve once for a batch
    names = _names(args)
    if args.batch:
        molecules = _batch(args.batch)
    else:
        source = args.smiles if args.smiles else _read(args.molfile)
        molecules = [(args.name, source)]
    failed = 0
    for name, source in molecules:
        try:
            expl = explain_molecule(source, defn, name=name, **names)
        except ValueError as e:
            failed += 1
            print(f"{name or source}: {e}", file=sys.stderr)
            continue
        path = args.output
        if args.batch:
            path = (
                os.path.join(args.out_dir, _slug(name) + ".png")
                if args.out_dir
                else None
            )
        record = {
            "molecule": name or source,
            "fires": expl.fires,
            "text": expl.text,
            "image": _save(expl.image, path),
        }
        _emit(args, record)
    return 1 if failed else 0


def cmd_convert(args) -> int:
    from viloch.definition import AuxProgram, Definition
    from viloch.editor.asp import from_asp, to_asp

    text = _read(args.input)
    if args.to == "model":
        defn = Definition.parse(text, args.target)
        target = defn.target or DEFAULT_TARGET
        out = {
            "target": target,
            "model": from_asp(defn.rule, target),
            "aux": defn.programs(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        data = json.loads(text)
        model = data.get("model", data)
        target = args.target or data.get("target") or DEFAULT_TARGET
        aux = tuple(AuxProgram.from_dict(p) for p in data.get("aux", []))
        defn = Definition(to_asp(model, target), aux, target).prune()
        print(defn.to_text(), end="")
    return 0


def cmd_serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "viloch serve needs the web extra: pip install 'viloch[web]'",
            file=sys.stderr,
        )
        return 2
    from viloch.web.app import create_app

    uvicorn.run(
        create_app(library_dir=args.library, target=args.target),
        host=args.host,
        port=args.port,
    )
    return 0


COMMANDS = {
    "explain-rule": cmd_explain_rule,
    "explain-molecule": cmd_explain_molecule,
    "convert": cmd_convert,
    "serve": cmd_serve,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (ValueError, OSError) as e:
        print(f"viloch: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
