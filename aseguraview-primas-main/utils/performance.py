# -*- coding: utf-8 -*-
"""Helpers de performance para cálculos vectorizados."""

from __future__ import annotations

import numpy as np

try:
    from numba import jit
except ModuleNotFoundError:  # pragma: no cover - fallback para entornos sin numba
    def jit(*_args, **_kwargs):
        def decorator(func):
            return func
        return decorator


@jit(nopython=True, cache=True, parallel=True)
def fast_proportional_distribution(deficit_array, budget_matrix):
    """Distribuye cada déficit de fila según el peso presupuestal mensual."""
    n_sucursales, n_meses = budget_matrix.shape
    result = np.zeros((n_sucursales, n_meses), dtype=np.float64)

    for i in range(n_sucursales):
        total_budget_sucursal = np.sum(budget_matrix[i, :])
        if total_budget_sucursal > 0:
            for j in range(n_meses):
                peso_mes = budget_matrix[i, j] / total_budget_sucursal
                result[i, j] = deficit_array[i] * peso_mes

    return result


@jit(nopython=True, cache=True)
def calculate_increments(deficit_array, budget_array):
    """Calcula incrementos porcentuales evitando divisiones inválidas."""
    result = np.zeros_like(deficit_array)
    for i in range(len(deficit_array)):
        if budget_array[i] > 0:
            result[i] = (deficit_array[i] / budget_array[i]) * 100.0
    return result
