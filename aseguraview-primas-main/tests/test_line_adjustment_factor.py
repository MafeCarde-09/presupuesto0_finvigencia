import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / 'app.py'


def get_line_adjustment_factor_returns():
    source = APP_PATH.read_text(encoding='utf-8')
    module = ast.parse(source, filename=str(APP_PATH))

    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == '_line_adjustment_factor':
            conditional_returns = {}
            default_return = None

            for statement in node.body:
                if (
                    isinstance(statement, ast.If)
                    and isinstance(statement.test, ast.Compare)
                    and isinstance(statement.test.left, ast.Name)
                    and statement.test.left.id == 'linea'
                    and len(statement.test.ops) == 1
                    and isinstance(statement.test.ops[0], ast.Eq)
                    and len(statement.test.comparators) == 1
                    and isinstance(statement.test.comparators[0], ast.Constant)
                    and statement.body
                    and isinstance(statement.body[0], ast.Return)
                    and isinstance(statement.body[0].value, ast.Constant)
                ):
                    conditional_returns[statement.test.comparators[0].value] = statement.body[0].value.value
                elif isinstance(statement, ast.Return) and isinstance(statement.value, ast.Constant):
                    default_return = statement.value.value

            return conditional_returns, default_return

    raise AssertionError('No se encontró _line_adjustment_factor en app.py')


class LineAdjustmentFactorTests(unittest.TestCase):
    def test_line_adjustment_factor_returns_expected_values(self):
        conditional_returns, default_return = get_line_adjustment_factor_returns()

        self.assertEqual(conditional_returns['FIANZAS'], 0.97)
        self.assertEqual(conditional_returns['SOAT'], 1.0)
        self.assertEqual(default_return, 0.995)

    def test_app_uses_centralized_adjustment_helper_in_forecast_views(self):
        source = APP_PATH.read_text(encoding='utf-8')

        expected_snippets = [
            "pronostico_mes_full = pronostico_mes_full * _line_adjustment_factor(linea)",
            "fc_valores_list = [v * _line_adjustment_factor(linea) for v in fc_valores_list]",
            "proy_total = proy_total * _line_adjustment_factor(filters['linea_plus'])",
            "fc_display['Pronostico_mensual'] = fc_display['Pronostico_mensual'] * _line_adjustment_factor(filters['linea_plus'])",
            "factor_sel = _line_adjustment_factor(linea_seleccionada)",
        ]

        for snippet in expected_snippets:
            self.assertIn(snippet, source)


if __name__ == '__main__':
    unittest.main()
