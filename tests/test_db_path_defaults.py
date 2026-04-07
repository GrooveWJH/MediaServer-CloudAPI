import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DB_PATH = "/opt/mediaserver/data/media.db"


def _load_ast(relative_path: str) -> ast.AST:
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    return ast.parse(source, filename=relative_path)


def _literal_value(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _find_argparse_db_default(relative_path: str) -> str:
    tree = _load_ast(relative_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        arg_values = [_literal_value(arg) for arg in node.args]
        if "--db-path" not in arg_values:
            continue
        for keyword in node.keywords:
            if keyword.arg == "default":
                return _literal_value(keyword.value)
    raise AssertionError(f"--db-path default not found in {relative_path}")


def _find_typer_db_default(relative_path: str) -> str:
    tree = _load_ast(relative_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in {"run", "main"}:
            continue
        args = node.args.args
        defaults = node.args.defaults
        offset = len(args) - len(defaults)
        for arg, default in zip(args[offset:], defaults):
            if arg.arg != "db_path":
                continue
            if not isinstance(default, ast.Call):
                raise AssertionError(f"db_path default is not a call in {relative_path}")
            if not isinstance(default.func, ast.Attribute) or default.func.attr != "Option":
                raise AssertionError(f"db_path default is not typer.Option in {relative_path}")
            if not default.args:
                raise AssertionError(f"typer.Option missing default in {relative_path}")
            return _literal_value(default.args[0])
    raise AssertionError(f"db_path typer.Option default not found in {relative_path}")


class DbPathDefaultsTest(unittest.TestCase):
    def test_runtime_defaults_use_absolute_db_path(self):
        self.assertEqual(
            _find_typer_db_default("src/media_server/server.py"),
            EXPECTED_DB_PATH,
        )
        self.assertEqual(
            _find_argparse_db_default("src/media_server/config/app.py"),
            EXPECTED_DB_PATH,
        )
        self.assertEqual(
            _find_typer_db_default("web/app.py"),
            EXPECTED_DB_PATH,
        )
        self.assertEqual(
            _find_argparse_db_default("web/fetch_one.py"),
            EXPECTED_DB_PATH,
        )


if __name__ == "__main__":
    unittest.main()
