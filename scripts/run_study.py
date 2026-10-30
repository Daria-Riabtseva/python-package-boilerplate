"""Execute the Kemerovo notebook in the foreground, saving each cell's outputs."""
from pathlib import Path
import argparse
import asyncio
import os
import sys

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


class ProgressClient(NotebookClient):
    def process_message(self, msg, cell, cell_index):
        if msg.get('msg_type') == 'stream':
            print(msg['content']['text'], end='', flush=True)
        return super().process_message(msg, cell, cell_index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--until-blocks', action='store_true', help='Stop after the blocks section')
    args = parser.parse_args()
    if os.name == 'nt':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    runtime = ROOT / '.venv' / 'local_jupyter'
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ['IPYTHONDIR'] = str(runtime / 'ipython')
    os.environ['JUPYTER_RUNTIME_DIR'] = str(runtime)
    path = ROOT / 'examples' / 'kemerovo_pipeline.ipynb'
    notebook = nbformat.read(path, as_version=4)
    client = ProgressClient(notebook, timeout=900, kernel_name='python3',
                            resources={'metadata': {'path': str(ROOT)}})
    with client.setup_kernel():
        for i, cell in enumerate(notebook.cells):
            if args.until_blocks and i > 10:
                break
            if cell.cell_type != 'code':
                continue
            print(f'Ячейка {i}: {cell.source.splitlines()[0]}', flush=True)
            try:
                client.execute_cell(cell, i)
            except Exception:
                for output in cell.get('outputs', []):
                    if output.output_type == 'error':
                        print(output.ename + ': ' + output.evalue, flush=True)
                raise
            finally:
                nbformat.write(notebook, path)
    print('Готово. Ноутбук сохранён с результатами выполненных ячеек.')


if __name__ == '__main__':
    main()
