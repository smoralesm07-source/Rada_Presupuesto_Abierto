"""Calcula concentración de proveedores por organismo.

Genera provider_concentration_v1.json con agregados de:
- provider_rut: RUT del proveedor
- organization_id: ID de la organización compradora
- periodo: año de la transacción
- monto_total_usd: suma de montos
- n_transacciones: cantidad de señales/transacciones

Se usa para evaluar TIP-04.I03 (concentración de contraparte) en CLAUDE Cockpit.
"""

import json
from collections import defaultdict
from pathlib import Path


def compute_provider_concentration(queue_path: Path) -> list[dict]:
    """Agrupa transacciones por (provider_rut, organization, periodo).

    Retorna array de dicts con monto total y contador por grupo.
    """
    data = json.loads(queue_path.read_text(encoding='utf-8'))

    aggregates = defaultdict(lambda: {'monto_total_usd': 0.0, 'n_transacciones': 0})

    for item in data.get('queue', []):
        provider_id = item.get('provider_id', '')
        org_id = item.get('organization_id', '')
        periodo = item.get('periodo')
        amount = item.get('transaction_amount', 0.0)

        if not provider_id or not org_id or periodo is None:
            continue

        # Extraer RUT del formato "PRV-RUT-{RUT}"
        rut = provider_id.replace('PRV-RUT-', '').upper() if 'PRV-RUT-' in provider_id else provider_id

        key = (rut, org_id, periodo)
        aggregates[key]['monto_total_usd'] += float(amount or 0)
        aggregates[key]['n_transacciones'] += 1

    # Convertir a lista de dicts ordenada por monto
    result = []
    for (rut, org_id, periodo), stats in aggregates.items():
        result.append({
            'provider_rut': rut,
            'organization_id': org_id,
            'periodo': periodo,
            'monto_total_usd': round(stats['monto_total_usd'], 2),
            'n_transacciones': stats['n_transacciones']
        })

    return sorted(result, key=lambda x: -x['monto_total_usd'])


def write_concentration_file(output_path: Path, concentrations: list[dict]) -> None:
    """Escribe provider_concentration_v1.json con metadata."""
    payload = {
        'format': 'provider_concentration_v1',
        'description': 'Agregados de transacciones por (provider_rut, organization_id, periodo). Usado para evaluar TIP-04.I03 (concentración de contraparte) en CLAUDE Cockpit.',
        'items': concentrations,
        'total_aggregates': len(concentrations)
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )


def main(queue_path: Path | None = None, output_dir: Path | None = None) -> None:
    """Genera provider_concentration_v1.json desde investigation_queue.json.

    Args:
        queue_path: path a investigation_queue.json (default: docs/data/investigation_queue.json)
        output_dir: carpeta de salida (default: docs/data/)
    """
    queue_path = queue_path or Path('docs/data/investigation_queue.json')
    output_dir = output_dir or Path('docs/data')

    if not queue_path.exists():
        print(f'ERROR: No encontrado {queue_path}')
        return

    print(f'Leyendo {queue_path}')
    concentrations = compute_provider_concentration(queue_path)

    output_file = output_dir / 'provider_concentration_v1.json'
    write_concentration_file(output_file, concentrations)

    stats = {
        'grupos_proveedor_organismo_periodo': len(concentrations),
        'monto_total': sum(x['monto_total_usd'] for x in concentrations),
        'transacciones_totales': sum(x['n_transacciones'] for x in concentrations),
        'monto_maximo': max((x['monto_total_usd'] for x in concentrations), default=0),
        'transacciones_maximo': max((x['n_transacciones'] for x in concentrations), default=0)
    }

    print(f'Escrito {output_file}')
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
