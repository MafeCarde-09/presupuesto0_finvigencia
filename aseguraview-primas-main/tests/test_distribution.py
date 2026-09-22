import unittest
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UTILS_DIR = ROOT / 'utils'

utils_pkg = types.ModuleType('utils')
utils_pkg.__path__ = [str(UTILS_DIR)]
sys.modules.setdefault('utils', utils_pkg)

for module_name in ('formatters', 'performance'):
    module_path = UTILS_DIR / f'{module_name}.py'
    module_spec = spec_from_file_location(f'utils.{module_name}', module_path)
    module = module_from_spec(module_spec)
    assert module_spec.loader is not None
    sys.modules[f'utils.{module_name}'] = module
    module_spec.loader.exec_module(module)

MODULE_PATH = UTILS_DIR / 'distribution.py'
SPEC = spec_from_file_location('utils.distribution', MODULE_PATH)
distribution_module = module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules['utils.distribution'] = distribution_module
SPEC.loader.exec_module(distribution_module)

build_distribution_html = distribution_module.build_distribution_html
build_monthly_distribution = distribution_module.build_monthly_distribution


class DistributionTests(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range('2026-01-01', '2026-12-01', freq='MS')
        self.df = pd.DataFrame({
            'FECHA': dates,
            'Suc_agrupada': ['BOGOTÁ'] * len(dates),
            'LINEA_PLUS': ['AUTOS'] * len(dates),
            'PRESUPUESTO': [100_000_000] * len(dates),
            'IMP_PRIMA': [60_000_000] * 5 + [0] * 7,
        })
        self.cutoff_date = pd.Timestamp('2026-06-01')

    def test_presupuesto_total_anio_uses_real_production_ytd(self):
        distribution, remaining_months = build_monthly_distribution(
            df_filtered=self.df,
            ref_year=2026,
            cutoff_date=self.cutoff_date,
            meses_quarter=tuple(range(1, 13)),
        )

        self.assertEqual(remaining_months, tuple(range(6, 13)))
        self.assertEqual(len(distribution), 1)
        row = distribution.iloc[0]
        self.assertEqual(row['Faltante_Proyectado'], 200_000_000)
        self.assertAlmostEqual(row['Presupuesto_Total_Anio'], 1_200_000_000)
        self.assertAlmostEqual(
            sum(row[f'{month}_Objetivo_Nuevo'] for month in ['Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']),
            900_000_000,
            places=2,
        )

    def test_distribution_html_includes_top_navigation_controls(self):
        distribution, remaining_months = build_monthly_distribution(
            df_filtered=self.df,
            ref_year=2026,
            cutoff_date=self.cutoff_date,
            meses_quarter=tuple(range(1, 13)),
        )

        html = build_distribution_html(
            df_distribution=distribution,
            remaining_months=remaining_months,
            ref_year=2026,
            cutoff_date=self.cutoff_date,
        )

        self.assertIn('distribution-top-scroll', html)
        self.assertIn('distribution-scroll-left', html)
        self.assertIn('distribution-scroll-right', html)
        self.assertIn('scrollBy({ left: scrollStep(), behavior: \'smooth\' })', html)
        self.assertIn('title="Suma de la producción real acumulada hasta el mes anterior al corte', html)


if __name__ == '__main__':
    unittest.main()
